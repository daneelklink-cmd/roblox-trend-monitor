import io
import json
import zipfile
import pandas as pd
from sqlalchemy import select
from app.analytics.research import CANDIDATES,candidate_metrics,compare_controls
from app.analytics.queries import load_data
from app.database.session import database,utcnow
from app.database.models import MissingObservation
from app.services.research import load_research,latest_groups,playtest_template
from app.services.exports import build_exports,csv_bytes


def research_bundle(settings=None,asof=None):
    games,snapshots,appearances,_=load_data(settings,include_archived=True)
    groups,notes,watch,_=load_research(settings)
    active=latest_groups(groups)
    asof=pd.Timestamp(asof if asof is not None else snapshots.timestamp.max() if len(snapshots) else utcnow()).floor('h')
    # Include sub-hour jitter in the selected hourly bin, never later bins.
    history=snapshots[snapshots.timestamp.dt.floor('h')<=asof]
    ids=set(CANDIDATES)|{m['universe_id'] for g in groups for m in g['members']}
    selected=games[games.universe_id.isin(ids)]
    files,_,manifest=build_exports(selected,history[history.universe_id.isin(ids)],
        appearances[appearances.universe_id.isin(ids)],end=min(pd.Timestamp(utcnow()),asof+pd.Timedelta(hours=1)-pd.Timedelta(microseconds=1)))
    metrics=candidate_metrics(games,history,asof)
    comparison,details=compare_controls(history,active,asof)
    files['ResearchCandidates.csv']=csv_bytes(metrics)
    files['ControlComparisons.csv']=csv_bytes(comparison)
    files['ControlObservations.csv']=csv_bytes(details)
    files['ControlGroups.csv']=csv_bytes(pd.DataFrame([{k:v for k,v in g.items() if k!='members'} for g in groups],columns=['id','candidate_id','version','selected_at','selection_as_of','methodology']))
    files['ControlMembers.csv']=csv_bytes(pd.DataFrame([{'group_id':g['id'],'candidate_id':g['candidate_id'],'version':g['version'],**m} for g in groups for m in g['members']],columns=['group_id','candidate_id','version','universe_id','name_at_selection','ccu_at_selection','age_days_at_selection','official_genre','selection_tier','distance','observation_at_selection_utc']))
    files['Playtests.csv']=csv_bytes(notes)
    files['PlaytestTemplate.csv']=playtest_template().encode('utf-8-sig')
    files['Watchlist.csv']=csv_bytes(watch[watch.universe_id.isin(ids)])
    engine,_=database(settings)
    try:
        with engine.connect() as connection:
            missing=pd.read_sql(select(MissingObservation).where(MissingObservation.universe_id.in_(ids)),connection)
        files['MissingObservations.csv']=csv_bytes(missing)
    finally:engine.dispose()
    manifest['research']={'candidate_ids':list(CANDIDATES),'active_control_groups':[g['id'] for g in active],
        'analysis_hour_utc':asof.isoformat()+'Z','notes':'Candidates and all versioned control members included. ResearchCandidates uses exact hourly bins and local-calendar matched hours. General Analytics uses existing elapsed-time baselines. Relative performance is percentage points, observational, not causal. Frozen controls were selected after discovery: pre-selection comparisons are retrospective.'}
    files['Manifest.json']=json.dumps(manifest,indent=2,default=str).encode()
    files['README.txt']+=b'\nRESEARCH: ResearchCandidates.csv is the authoritative candidate comparison table. Control groups are fixed/versioned; absent members are never replaced. ControlObservations contains each paired endpoint and blank missing values. Playtests are human-reported evidence, separate from classifications. Blank notes are unknown, not inferred mechanics. Timestamps in exports remain UTC. 24h/72h candidate comparisons use the same Berlin wall hour on earlier local dates; DST-ambiguous baselines remain unavailable. General Analytics uses elapsed-time baselines.\n'
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,content in files.items():archive.writestr(name,content)
    return files,buffer.getvalue()
