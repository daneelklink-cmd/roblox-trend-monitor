import csv
import io
import json
from datetime import timedelta
import pandas as pd
import pytest
from sqlalchemy import select,func
from app.analytics.research import CANDIDATES,previous_local_hour,compare_controls,candidate_metrics
from app.database.models import Game,Snapshot,ResearchControlGroup,PlaytestNote,WatchEntry,CollectionRun
from app.database.session import database
from app.services.research import initialize_research,load_research,playtest_template,import_playtests,NOTE_COLUMNS
from app.services.research_exports import research_bundle
from app.reports.research import generate_research_report
from app.scheduler import startup_collection_due


def seed(settings,now):
    engine,Session=database(settings)
    with Session.begin() as s:
        for index,uid in enumerate([*CANDIDATES,*range(100,130)]):
            s.add(Game(universe_id=uid,name=CANDIDATES.get(uid,f'Control {uid}'),first_seen_at=now-timedelta(days=4),
                last_seen_at=now,created_at=now-timedelta(days=20),primary_genre='Simulation',metadata_json={'genre_l1':'Simulation'}))
        s.flush()
        for uid in [*CANDIDATES,*range(100,130)]:
            for hour in range(73):
                stamp=now-timedelta(hours=72-hour)
                s.add(Snapshot(universe_id=uid,cycle_key=stamp.strftime('%Y-%m-%dT%H:00:00Z'),timestamp=stamp,
                    playing=100+hour,visits=1000+hour*10,favorites=hour,game_name_at_time='Synthetic research fixture'))
    engine.dispose()


def test_frozen_groups_watchlist_idempotence_and_explicit_version(settings,now,monkeypatch):
    seed(settings,now);monkeypatch.setattr('app.services.research.utcnow',lambda:now)
    first=initialize_research(settings)
    assert len(first)==5 and all(row['controls']==20 for row in first)
    groups,_,watch,_=load_research(settings)
    original={g['candidate_id']:[m['universe_id'] for m in g['members']] for g in groups}
    assert not any(set(ids)&set(CANDIDATES) for ids in original.values())
    assert set(CANDIDATES).issubset(set(watch[watch.active].universe_id))
    assert all(row['reused'] for row in initialize_research(settings))
    assert len(load_research(settings)[0])==5
    initialize_research(settings,new_version=True)
    assert len(load_research(settings)[0])==10


def test_berlin_calendar_hours_and_dst_ambiguity():
    assert previous_local_hour(pd.Timestamp('2026-10-20 08:00'),1)==pd.Timestamp('2026-10-19 08:00')
    assert previous_local_hour(pd.Timestamp('2026-10-25 09:00'),1)==pd.Timestamp('2026-10-24 08:00')
    assert pd.isna(previous_local_hour(pd.Timestamp('2026-10-26 01:30'),1))


def test_display_timezone_never_mutates_stored_utc_frames():
    from app.dashboard.timezone import berlin,local_frame
    original=pd.DataFrame({'as_of_utc':[pd.Timestamp('2026-10-20 08:00')]})
    displayed=local_frame(original)
    assert displayed.as_of_berlin.iloc[0].hour==10
    assert original.as_of_utc.iloc[0].hour==8 and original.as_of_utc.dt.tz is None
    assert 'CET' in berlin('2026-01-01 08:00')
    assert 'CEST' in berlin('2026-07-01 08:00')


def test_paired_controls_missing_and_zero_do_not_trigger_replacement(now):
    uid=next(iter(CANDIDATES));records=[]
    for member in [uid,*range(100,120)]:
        for hours,playing in [(24,100),(0,200)]:
            if member==119 and hours==0:continue
            records.append({'universe_id':member,'timestamp':now-timedelta(hours=hours),'playing':0 if member==118 and hours==24 else playing})
    snapshots=pd.DataFrame(records)
    groups=[{'id':'fixed','candidate_id':uid,'members':[{'universe_id':mid} for mid in range(100,120)]}]
    compared,details=compare_controls(snapshots,groups,now)
    row=compared[compared.horizon=='24h'].iloc[0]
    assert row.fixed_controls==20 and row.matched_controls==18 and row.missing_current_controls==1
    assert row.zero_baseline_controls==1 and row.relative_performance_pp==0
    assert set(details.control_id)==set(range(100,120))
    partial=snapshots[~snapshots.universe_id.isin(range(110,120))]
    compared,_=compare_controls(partial,groups,now)
    row=compared[compared.horizon=='24h'].iloc[0]
    assert row.status=='insufficient_controls' and pd.isna(row.relative_performance_pp)


def test_recovery_new_high_and_missing_hour_are_distinct(settings,now):
    seed(settings,now)
    from app.analytics.queries import load_data
    games,_,_,_=load_data(settings)
    uid=next(iter(CANDIDATES))
    h=pd.DataFrame([{'universe_id':uid,'timestamp':now-timedelta(hours=hour),'playing':ccu,'visits':1000,'favorites':10}
        for hour,ccu in [(6,100),(3,500),(0,300)]])
    row=candidate_metrics(games,h,now).iloc[0]
    assert row.signal=='recovery_below_observed_peak' and row.drawdown_pct==-40
    assert row.pct_6h==200 and pd.isna(row.pct_1h) and pd.isna(row.avg_24h)
    h.loc[h.timestamp==now,'playing']=600
    assert candidate_metrics(games,h,now).iloc[0].signal=='new_observed_high'


def test_playtest_import_evidence_scores_idempotence_and_no_auto_classification(settings,now):
    seed(settings,now);engine,Session=database(settings)
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=NOTE_COLUMNS);writer.writeheader()
    writer.writerow({'universe_id':next(iter(CANDIDATES)),'researcher':'Tester','observed_at_utc':now.isoformat()+'Z',
        'evidence':'Played on Android for 15 minutes','core_loop':'Observed fixture loop','mobile_usability':'Readable',
        'development_complexity':3,'marketing_potential':4})
    content=stream.getvalue()
    with Session.begin() as s:assert import_playtests(s,content,now)==1
    with Session.begin() as s:
        assert import_playtests(s,content,now)==0
        assert s.get(Game,next(iter(CANDIDATES))).core_loop is None
        assert s.scalar(select(PlaytestNote)).source_type=='human_playtest'
    with pytest.raises(ValueError):
        with Session.begin() as s:import_playtests(s,content.replace('Android','').replace(',3,4,',',6,4,'),now)
    with pytest.raises(ValueError):
        with Session.begin() as s:import_playtests(s,content.replace(now.isoformat()+'Z',now.isoformat()),now)
    with Session.begin() as s:assert import_playtests(s,playtest_template(),now)==0
    offset=(now-timedelta(hours=4)).isoformat()+'-04:00'
    with Session.begin() as s:assert import_playtests(s,content.replace(now.isoformat()+'Z',offset),now)==0
    data=list(csv.DictReader(io.StringIO(content)))[0]
    data.update(development_complexity='3.0',marketing_potential='4.0',source_type='human_playtest')
    extra=io.StringIO();writer=csv.DictWriter(extra,fieldnames=[*NOTE_COLUMNS,'source_type']);writer.writeheader();writer.writerow(data)
    with Session.begin() as s:assert import_playtests(s,extra.getvalue(),now)==0
    with pytest.raises(ValueError):
        with Session.begin() as s:import_playtests(s,extra.getvalue().replace('human_playtest','ai_generated'),now)
    engine.dispose()


def test_report_due_time_sections_and_research_export(settings,now,tmp_path,monkeypatch):
    seed(settings,now);monkeypatch.setattr('app.services.research.utcnow',lambda:now)
    initialize_research(settings)
    path=generate_research_report(settings,tmp_path,now)
    report=path.read_text(encoding='utf-8')
    for heading in ['OBSERVED FACTS','VERIFIED GAMEPLAY INFORMATION','HYPOTHESES','INSUFFICIENT DATA']:
        assert heading in report
    assert generate_research_report(settings,tmp_path,now+timedelta(hours=23)) is None
    assert generate_research_report(settings,tmp_path,now+timedelta(hours=24)) is not None
    files,bundle=research_bundle(settings,now)
    assert len(pd.read_csv(io.BytesIO(files['ResearchCandidates.csv'])))==5
    assert len(pd.read_csv(io.BytesIO(files['ControlMembers.csv'])))==100
    assert pd.read_csv(io.BytesIO(files['Playtests.csv'])).empty
    assert json.loads(files['Manifest.json'])['research']['candidate_ids']==list(CANDIDATES)


def test_restart_skips_complete_hour_unless_watchlist_reading_missing(settings,now):
    seed(settings,now)
    assert startup_collection_due(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:
        s.add(CollectionRun(cycle_key=now.strftime('%Y-%m-%dT%H:00:00Z'),started_at=now,status='complete'))
    assert not startup_collection_due(settings,now)
    with Session.begin() as s:s.add(WatchEntry(universe_id=9999,added_at=now,active=True))
    assert startup_collection_due(settings,now)
    engine.dispose()
