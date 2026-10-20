"""Daily 72-hour research briefing, called by the existing hourly pipeline."""
import json
import uuid
from pathlib import Path
import pandas as pd
from sqlalchemy import select
from app.config import ROOT
from app.database.session import database,utcnow
from app.database.models import ResearchReportRun,CollectionAttempt,MissingObservation
from app.analytics.queries import load_data
from app.analytics.research import CANDIDATES,candidate_metrics,compare_controls,BERLIN
from app.services.research import load_research,latest_groups


def shown(value,percent=False):
    if value is None or pd.isna(value):return 'insufficient data'
    return f'{value:+.1f}%' if percent else f'{value:,.0f}'


def collection_health(settings=None):
    engine,_=database(settings)
    try:
        with engine.connect() as connection:
            attempts=pd.read_sql(select(CollectionAttempt).order_by(CollectionAttempt.started_at.desc()).limit(30),connection)
            missing=pd.read_sql(select(MissingObservation).order_by(MissingObservation.timestamp.desc()).limit(1000),connection)
        return attempts,missing
    finally:engine.dispose()


def generate_research_report(settings=None,output=None,now=None,force=False):
    now=now or utcnow();engine,Session=database(settings)
    try:
        with Session() as session:
            last=session.scalar(select(ResearchReportRun).order_by(ResearchReportRun.generated_at.desc()).limit(1))
            if last and not force and now-last.generated_at<pd.Timedelta(hours=24):return None
        games,snapshots,appearances,_=load_data(settings,include_archived=True)
        groups,notes,_,_=load_research(settings)
        if not groups:return None  # Explicit init freezes controls; reports never select them.
        asof=snapshots.timestamp.max().floor('h') if len(snapshots) else pd.Timestamp(now).floor('h')
        metrics=candidate_metrics(games,snapshots,asof)
        comparison,_=compare_controls(snapshots,latest_groups(groups),asof)
        local=pd.Timestamp(now).tz_localize('UTC').tz_convert(BERLIN)
        lines=[f'# 72-hour Research Briefing — {local:%d.%m.%Y %H:%M %Z}', '',
            f'Observation cutoff: {asof} UTC. Requested lookback: 72h; only actual collected history is used.',
            'Fixed observational controls, not a randomized experiment. Relative performance is not a causal effect.', '', '## OBSERVED FACTS','']
        for _,row in metrics.iterrows():
            lines += [f'### {CANDIDATES[row.universe_id]} — Universe {row.universe_id}',
                f'- Current CCU: {shown(row.ccu)}; signal: {row.signal}. Historical observed peak: {shown(row.historical_observed_peak_ccu)}; drawdown: {shown(row.drawdown_pct,True)}.',
                f'- Growth: 1h {shown(row.pct_1h,True)}, 6h {shown(row.pct_6h,True)}, same Berlin hour yesterday {shown(row.pct_24h,True)}, same hour 3 days ago {shown(row.pct_72h,True)}.',
                f'- 24h observed mean/peak: {shown(row.avg_24h)} / {shown(row.peak_24h)}; occupied hourly bins: {row.observations_24h}/25.',
                f'- Visits growth 6h/24h: {shown(row.visits_growth_6h)} / {shown(row.visits_growth_24h)}; favorites growth 6h/24h: {shown(row.favorites_growth_6h)} / {shown(row.favorites_growth_24h)}.',
                f'- Sustained 24h growth: {"insufficient data" if pd.isna(row.sustained_growth_24h) else bool(row.sustained_growth_24h)}. A temporary spike cannot be ruled out from a short series.']
            for _,control in comparison[comparison.candidate_id==row.universe_id].iterrows():
                lines.append(f'- Controls {control.horizon}: candidate {shown(control.candidate_pct_change,True)}, median {shown(control.control_median_pct_change,True)}, relative {shown(control.relative_performance_pp)} percentage points; {control.matched_controls}/{control.fixed_controls} paired; missing current/baseline {control.missing_current_controls}/{control.missing_baseline_controls}; status {control.status}.')
            h=appearances[(appearances.universe_id==row.universe_id)&(appearances.timestamp>=asof-pd.Timedelta(hours=72))]
            for source,records in h.groupby('source'):
                ordered=records.sort_values('timestamp')
                if len(ordered)>=2:
                    lines.append(f'- Ranking {source}: {ordered.iloc[0]["rank"]} at {ordered.iloc[0].timestamp} UTC → {ordered.iloc[-1]["rank"]} at {ordered.iloc[-1].timestamp} UTC; {len(ordered)} appearances. Missing list observations are not rank zero.')
            window=snapshots[(snapshots.universe_id==row.universe_id)&(snapshots.timestamp>=asof-pd.Timedelta(hours=72))]
            lines.append(f'- Actual 72h-window coverage: {window.timestamp.dt.floor("h").nunique()}/73 hourly bins. Significant observed 6h decline (≤−20%): {"insufficient data" if pd.isna(row.pct_6h) else row.pct_6h<=-20}.')
        lines += ['', '## VERIFIED GAMEPLAY INFORMATION','', 'Human-entered playtest observations with researcher/date/evidence; these are researcher claims, not independent verification. They are kept separate from automated classifications.']
        if notes.empty:lines.append('No manual playtests entered. Gameplay mechanics remain unknown.')
        else:
            for _,note in notes.tail(25).iterrows():
                lines += ['',f'Universe {note.universe_id}, researcher {note.researcher}, observed {note.observed_at_utc} UTC:',
                    '```json',json.dumps(note.to_dict(),ensure_ascii=False,default=str,indent=2),'```']
        lines += ['', '## HYPOTHESES','',
            '- Does candidate growth persist at equivalent local hours after 24/72h, and exceed the frozen controls?',
            '- Is a rise a recovery below an earlier high, or a new observed peak followed by sustained activity?',
            '- Which manually played core loops, mobile strengths and differentiation ideas warrant a small prototype? No mechanics are inferred from names.',
            '', '## INSUFFICIENT DATA','',
            '- Blank historical comparisons are unavailable, not zero growth or failure. Missing controls are never replaced.',
            '- Controls were selected after the initial signal; historical pre-selection comparisons are retrospective and selection-biased.',
            '- A 24h sustained-growth flag requires a valid baseline, ≥75% hourly coverage and no gap >1.5h; it is not retention.',
            '- No measured retention, acquisition attribution, competitor revenue, profitability or exhaustive launch coverage is available.']
        attempts,missing=collection_health(settings)
        latest=attempts.iloc[0] if len(attempts) else None
        lines += ['', '## COLLECTION INTEGRITY','',f'Latest attempt: {latest.status if latest is not None else "unknown"}; {latest.started_at if latest is not None else "unknown"} UTC. Last observation: {snapshots.timestamp.max() if len(snapshots) else "none"} UTC.',
            f'Recent explicit missing-observation records (up to 1000): {len(missing)}. API errors and source coverage are retained in collection summaries.']
        path=Path(output or ROOT/'reports')/'research'/f'{local:%Y-%m-%d-%H%M%S}.md'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        with Session.begin() as session:
            session.add(ResearchReportRun(id=str(uuid.uuid4()),generated_at=now,path=str(path)))
        return path
    finally:engine.dispose()
