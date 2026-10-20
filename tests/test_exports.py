from datetime import timedelta
import io
import json
import zipfile
import pandas as pd
import pytest
from app.analytics.queries import load_data
from app.database.models import Game, Snapshot
from app.database.session import database
from app.services.exports import build_exports
from tests.test_collection import run


def read(files,name):
    return pd.read_csv(io.BytesIO(files[name]),encoding='utf-8-sig')


def test_complete_export_preserves_metadata_unknowns_and_zip(settings,now):
    run(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:
        game=s.get(Game,1)
        game.name='Mining, "new"\n🎮'
        game.classification_meta={'theme':{'source':'manual_hypothesis','confidence':.5}}
        s.add(Game(universe_id=2,name='Metadata only',first_seen_at=now,last_seen_at=now))
    engine.dispose()
    games,snapshots,appearances,_=load_data(settings,include_archived=True)
    files,bundle,manifest=build_exports(games,snapshots,appearances,now=now)
    exported=read(files,'Games.csv')
    assert len(exported)==2
    assert exported.iloc[0]['name']=='Mining, "new"\n🎮'
    assert json.loads(exported.iloc[0].classification_meta)['theme']['source']=='manual_hypothesis'
    analytics=read(files,'Analytics.csv')
    assert pd.isna(analytics[analytics.universe_id==2].iloc[0].ccu)
    assert pd.isna(analytics[analytics.universe_id==1].iloc[0].pct_24h)
    assert read(files,'Snapshots.csv').iloc[0].playing==100
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read('Manifest.json'))==manifest
        assert {'Games.csv','Snapshots.csv','Analytics.csv','Cohorts.csv','CohortMilestones.csv','MilestoneEvents.csv','MarketAnalyses.csv','README.txt'}.issubset(archive.namelist())


def test_range_retains_real_pre_window_baselines_and_no_future_rows(settings,now):
    run(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:
        for hour,ccu in [(6,200),(7,900)]:
            stamp=now+timedelta(hours=hour)
            s.add(Snapshot(universe_id=1,cycle_key=stamp.isoformat(),timestamp=stamp,playing=ccu,
                visits=2000,game_name_at_time='Fixture'))
    engine.dispose()
    games,snapshots,appearances,_=load_data(settings)
    stamp=now+timedelta(hours=6)
    files,_,manifest=build_exports(games,snapshots,appearances,start=stamp,end=stamp,now=now+timedelta(hours=8))
    assert len(read(files,'Snapshots.csv'))==1
    metrics=read(files,'Analytics.csv').iloc[0]
    assert metrics.ccu==200 and metrics.delta_6h==100 and metrics.pct_6h==100
    assert manifest['analysis_as_of_utc'].startswith(stamp.isoformat())


def test_genre_age_filters_unknown_age_and_empty_exports(settings,now):
    run(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:
        game=s.get(Game,1);game.primary_genre='Simulator';game.created_at=now-timedelta(days=2)
        s.add(Game(universe_id=2,name='Unknown age',primary_genre='Simulator',first_seen_at=now,last_seen_at=now))
    engine.dispose()
    games,snapshots,appearances,_=load_data(settings)
    files,_,_=build_exports(games,snapshots,appearances,genres=['Simulator'],min_age=1,max_age=7,now=now)
    assert read(files,'Games.csv').universe_id.tolist()==[1]
    files,_,_=build_exports(games,snapshots,appearances,genres=['Other'],now=now)
    assert read(files,'Games.csv').empty and read(files,'Analytics.csv').empty
    assert read(files,'Snapshots.csv').empty
    with pytest.raises(ValueError):build_exports(games,snapshots,appearances,min_age=10,max_age=5,now=now)
    with pytest.raises(ValueError):build_exports(games,snapshots,appearances,start=now+timedelta(days=1),now=now)


def test_archived_games_are_available_only_when_requested(settings,now):
    run(settings,now)
    engine,Session=database(settings)
    with Session.begin() as s:s.get(Game,1).archived=True
    engine.dispose()
    assert load_data(settings)[0].empty
    games,snapshots,appearances,_=load_data(settings,include_archived=True)
    assert len(games)==len(snapshots)==1
    files,_,manifest=build_exports(games,snapshots,appearances,now=now,include_archived=True)
    assert read(files,'Games.csv').iloc[0].archived
    assert manifest['filters']['include_archived']
