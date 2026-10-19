from datetime import timedelta
import sqlite3
import pandas as pd
import pytest
from sqlalchemy import inspect, select, func
from app.analytics.cohorts import milestone_events, cohort_analysis
from app.analytics.opportunities import concentration, enrich_market, niche_metrics
from app.analytics.queries import load_data, build_market
from app.collectors.discovery import SearchDiscovery, select_candidates
from app.collectors.providers import Appearance
from app.database.models import Game, MissingObservation, WatchEntry, Snapshot
from app.database.session import database
from app.services.classification import classify, export_csv, import_csv
from tests.test_collection import run, Discovery, Metadata


def test_search_pagination_and_sponsored_exclusion():
    class Client:
        def get(self, url, params):
            assert 'search-api/omni-search' in url
            return {'searchResults':[{'contents':[{'universeId':2 if 'pageToken' in params else 1}, {'universeId':3,'isSponsored':True}]}],
                    'nextPageToken':None if 'pageToken' in params else 'next'}
    cfg={'core_queries':['beta'],'rotating_queries':[],'queries_per_cycle':1,'search_pages':3}
    scout=SearchDiscovery(Client(),cfg)
    assert {a.universe_id for a in scout.discover()}=={1,2}
    assert scout.coverage[0]['pages']==2
    assert 'relevance' in scout.coverage[0]['scope']


def test_admission_prioritizes_young_small_watchlist(settings,now):
    entries=[Appearance(i,'source',i) for i in range(1,502)]
    rows={i:{'created':'2020-01-01T00:00:00Z','playing':10000} for i in range(1,502)}
    rows[500]={'created':'2026-10-18T00:00:00Z','playing':10}
    rows[501]={'created':'2020-01-01T00:00:00Z','playing':50}
    ids,reasons=select_candidates(entries,rows,settings,now,[999])
    assert len(ids)==400 and {500,501,999}.issubset(ids)
    assert reasons[500]=='young_creation_date' and reasons[501]=='small_ccu'


def test_additive_old_schema_migration_preserves_rows(settings):
    with sqlite3.connect(settings.database) as c:
        c.execute('CREATE TABLE games (universe_id BIGINT PRIMARY KEY,name TEXT NOT NULL,first_seen_at DATETIME NOT NULL,last_seen_at DATETIME NOT NULL,archived BOOLEAN NOT NULL)')
        c.execute("INSERT INTO games VALUES (123,'Retained','2026-01-01','2026-01-01',0)")
    engine,Session=database(settings)
    with Session() as s:
        assert s.get(Game,123).name=='Retained'
        assert s.get(Game,123).public_launch_at is None
    assert 'missing_observations' in inspect(engine).get_table_names()
    engine.dispose()


def test_missing_distinguished_from_zero_and_watchlist(settings,now):
    run(settings,now)
    run(settings,now+timedelta(hours=1),Discovery([]),Metadata(omit=True))
    engine,Session=database(settings)
    with Session.begin() as s:
        assert s.scalar(select(func.count()).select_from(MissingObservation))==1
        assert s.scalar(select(func.count()).select_from(Snapshot))==1
        s.add(WatchEntry(universe_id=42,added_at=now,note='Manual',active=True))
    engine.dispose()
    class Zero(Metadata):
        def fetch(self,ids):
            rows=super().fetch(ids)
            for row in rows.values():row['playing']=0
            return rows
    run(settings,now+timedelta(hours=2),Discovery([]),Zero())
    engine,Session=database(settings)
    with Session() as s:
        assert s.get(Game,42) is not None
        assert s.scalar(select(Snapshot).where(Snapshot.universe_id==42)).playing==0
    engine.dispose()


def test_classification_roundtrip_evidence_and_atomic_import(settings,now):
    run(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:
        game=s.get(Game,1)
        classify(s,game,{'core_loop':'Plant / harvest'},'manual_observation',.8,'Played tutorial')
        content=export_csv([game])
    with Session.begin() as s:
        assert import_csv(s,content)==1
        assert s.get(Game,1).classification_meta['core_loop']['evidence']=='Played tutorial'
    with pytest.raises(ValueError):
        with Session.begin() as s:
            import_csv(s,'universe_id,core_loop\n1,Overwrite\n999,Invalid\n')
    with Session() as s:
        assert s.get(Game,1).core_loop=='Plant / harvest'
        with pytest.raises(ValueError):classify(s,s.get(Game,1),{'theme':'Farm'},'manual_observation',1)
    engine.dispose()


def test_milestones_baseline_recross_gap_and_immaturity(settings,now):
    h=pd.DataFrame([{'universe_id':uid,'timestamp':now+timedelta(hours=t),'playing':ccu}
        for uid,points in [(1,[(0,110),(1,20),(2,200)]),(2,[(0,10),(8,600)])] for t,ccu in points])
    events=milestone_events(h)
    baseline=events[(events.universe_id==1)&(events.threshold==100)].iloc[0]
    assert baseline.status=='baseline_already_above' and baseline.recrossings==1
    gap=events[(events.universe_id==2)&(events.threshold==500)].iloc[0]
    assert gap.status=='crossing_after_gap' and gap.elapsed_lower_hours==0 and gap.elapsed_upper_hours==8
    run(settings,now)
    games,snapshots,appearances,_=load_data(settings)
    games['created_at']=pd.Timestamp(now)
    market=build_market(games,snapshots,appearances,now)
    _,rates,_=cohort_analysis(games,snapshots,market,24,now)
    rate=rates[(rates.cohort=='Created ≤7d')&(rates.threshold==500)].iloc[0]
    assert rate.eligible_nonbaseline_games==0 and pd.isna(rate.observed_crossing_share_by_followup_pct)
    assert rate.insufficient_followup_games==1


def test_concentration_and_insufficient_niche_history(settings,now):
    assert concentration(pd.Series([100,100]))==(5000,100)
    assert concentration(pd.Series([0,0]))==(None,None)
    run(settings,now)
    games,snapshots,appearances,_=load_data(settings)
    games['primary_genre']='Test taxonomy'
    market=enrich_market(build_market(games,snapshots,appearances,now),games)
    niches=niche_metrics(market,now=now)
    assert niches.iloc[0].matched_games==0
    assert not niches.iloc[0].potential_saturation_indicator
    assert pd.isna(niches.iloc[0].matched_aggregate_growth_pct)


def test_rate_limit_defers_endpoint_for_cycle():
    import httpx
    from app.collectors.http import PublicClient, SourceError
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'300'})
    client=PublicClient(transport=httpx.MockTransport(handler),sleep=lambda _:None)
    with pytest.raises(SourceError):client.get('https://example.test/games')
    with pytest.raises(SourceError):client.get('https://example.test/games')
    assert len(calls)==1
    client.close()


def test_mature_cohort_and_30day_baseline(settings,now):
    run(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:
        for hour in range(1,721):
            stamp=now+timedelta(hours=hour)
            s.add(Snapshot(cycle_key=stamp.isoformat(),timestamp=stamp,universe_id=1,playing=100+hour*20,
                visits=1000+hour*100,game_name_at_time='Synthetic fixture only'))
    engine.dispose()
    games,snapshots,appearances,_=load_data(settings)
    market=build_market(games,snapshots,appearances,now+timedelta(hours=720))
    assert market.iloc[0].delta_30d==14400
    assert market.iloc[0].visit_velocity_30d==100
    _,rates,_=cohort_analysis(games,snapshots,market,24,now+timedelta(hours=720))
    rate=rates[(rates.cohort.str.startswith('First observed'))&(rates.threshold==500)].iloc[0]
    assert rate.eligible_nonbaseline_games==1 and rate.crossed_by_followup==1
    assert rate.observed_crossing_share_by_followup_pct==100
