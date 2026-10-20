"""Read-only measurement verification plus generation of the requested research artifacts."""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from sqlalchemy import select,text
from app.config import ROOT
from app.database.session import database,utcnow
from app.database.models import CollectionRun
from app.analytics.queries import load_data
from app.analytics.research import CANDIDATES,candidate_metrics,compare_controls
from app.services.research import load_research,latest_groups
from app.services.research_exports import research_bundle
from app.reports.research import generate_research_report

games,snapshots,appearances,_=load_data(include_archived=True)
groups,notes,watch,reports=load_research()
active=latest_groups(groups)
assert {g['candidate_id'] for g in active}==set(CANDIDATES)
engine,Session=database()
with Session() as session:
    latest=session.scalar(select(CollectionRun).where(CollectionRun.status.in_(['complete','partial'])).order_by(CollectionRun.started_at.desc()).limit(1))
    asof=pd.Timestamp(latest.started_at).floor('h')
    duplicates=session.execute(text('SELECT count(*) FROM (SELECT universe_id,cycle_key FROM snapshots GROUP BY universe_id,cycle_key HAVING count(*)>1)')).scalar()
engine.dispose()
assert duplicates==0
metrics=candidate_metrics(games,snapshots,asof)
comparison,_=compare_controls(snapshots,active,asof)
assert metrics.ccu.notna().all()
assert set(CANDIDATES).issubset(set(watch[watch.active].universe_id))
for group in active:
    assert len({m['universe_id'] for m in group['members']})==len(group['members'])
    assert all(m['universe_id'] not in CANDIDATES for m in group['members'])
    assert {m['universe_id'] for m in group['members']}.issubset(set(watch[watch.active].universe_id))
files,bundle=research_bundle(asof=asof)
assert len(pd.read_csv(io.BytesIO(files['ResearchCandidates.csv'])))==5
assert len(pd.read_csv(io.BytesIO(files['ControlMembers.csv'])))==sum(len(g['members']) for g in groups)
path=ROOT/'data/ResearchCandidates.zip';path.write_bytes(bundle)
report=generate_research_report()
if report is None:report=Path(load_research()[3][0]['path'])
body=report.read_text(encoding='utf-8')
assert all(section in body for section in ['OBSERVED FACTS','VERIFIED GAMEPLAY INFORMATION','HYPOTHESES','INSUFFICIENT DATA'])
result={'verified_at_utc':utcnow().isoformat()+'Z','comparison_hour_utc':str(asof),'games_in_database':len(games),
    'snapshots':len(snapshots),'duplicate_game_cycles':duplicates,'playtests_entered':len(notes),
    'control_groups':[{'candidate_id':g['candidate_id'],'id':g['id'],'count':len(g['members']),
        'tiers':pd.Series([m['selection_tier'] for m in g['members']]).value_counts().to_dict()} for g in active],
    'candidate_metrics':json.loads(metrics.to_json(orient='records',date_format='iso')),
    'control_comparisons':json.loads(comparison.to_json(orient='records',date_format='iso')),
    'research_zip':str(path),'report':str(report),'last_completed_collection_status':latest.status,
    'last_completed_summary':latest.summary}
(ROOT/'data/research-verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
