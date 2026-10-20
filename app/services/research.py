"""Watchlist-backed research, immutable control manifests, append-only playtests."""
import csv
import hashlib
import io
import json
import uuid
import pandas as pd
from sqlalchemy import select
from app.analytics.research import CANDIDATES,select_controls
from app.analytics.queries import load_data
from app.database.session import database,utcnow,parse_time
from app.database.models import WatchEntry,Game,ResearchControlGroup,PlaytestNote,ResearchReportRun

NOTE_FIELDS=('core_loop','first_minute','progression','social_mechanics','monetization_observed',
    'mobile_usability','development_complexity','marketing_potential','strengths','weaknesses','differentiation')
NOTE_COLUMNS=('universe_id','researcher','observed_at_utc','evidence',*NOTE_FIELDS)


def initialize_research(settings=None,new_version=False):
    games,snapshots,_,_=load_data(settings,include_archived=True)
    now=utcnow();engine,Session=database(settings);result=[]
    try:
        with Session.begin() as session:
            for uid in CANDIDATES:
                if not session.get(Game,uid): raise ValueError(f'Candidate {uid} is not tracked; add it through watch first')
                session.get(Game,uid).archived=False
                watch=session.get(WatchEntry,uid)
                if watch is None:
                    watch=WatchEntry(universe_id=uid,added_at=now,note='Research candidate');session.add(watch)
                watch.active=True
                old=session.scalar(select(ResearchControlGroup).where(ResearchControlGroup.candidate_id==uid).order_by(ResearchControlGroup.version.desc()).limit(1))
                if old is not None and not new_version:
                    result.append({'candidate_id':uid,'group_id':old.id,'controls':len(old.members),'reused':True});continue
                members,method=select_controls(uid,games,snapshots,now)
                group=ResearchControlGroup(id=str(uuid.uuid4()),candidate_id=uid,version=old.version+1 if old else 1,
                    selected_at=now,selection_as_of=now,methodology=method,members=members)
                session.add(group)
                for member in members:
                    mid=member['universe_id'];session.get(Game,mid).archived=False
                    control=session.get(WatchEntry,mid)
                    if control is None:
                        control=WatchEntry(universe_id=mid,added_at=now,note='Frozen research control');session.add(control)
                    control.active=True
                result.append({'candidate_id':uid,'group_id':group.id,'controls':len(members),'reused':False})
        return result
    finally:engine.dispose()


def load_research(settings=None):
    engine,Session=database(settings)
    try:
        with Session() as session:
            groups=[{'id':g.id,'candidate_id':g.candidate_id,'version':g.version,'selected_at':g.selected_at,
                'selection_as_of':g.selection_as_of,'methodology':g.methodology,'members':g.members}
                for g in session.scalars(select(ResearchControlGroup).order_by(ResearchControlGroup.version))]
            notes=[{'id':n.id,'universe_id':n.universe_id,'researcher':n.researcher,'observed_at_utc':n.observed_at,
                'entered_at_utc':n.entered_at,'source_type':n.source_type,'evidence':n.evidence,**n.observations}
                for n in session.scalars(select(PlaytestNote).order_by(PlaytestNote.observed_at))]
            watch=pd.read_sql(select(WatchEntry),session.connection())
            reports=[{'generated_at':r.generated_at,'path':r.path} for r in session.scalars(select(ResearchReportRun).order_by(ResearchReportRun.generated_at.desc()).limit(1))]
        return groups,pd.DataFrame(notes,columns=['id',*NOTE_COLUMNS,'entered_at_utc','source_type']),watch,reports
    finally:engine.dispose()


def latest_groups(groups):
    selected={}
    for group in groups:
        if group['candidate_id'] not in selected or group['version']>selected[group['candidate_id']]['version']:
            selected[group['candidate_id']]=group
    return list(selected.values())


def playtest_template():
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=NOTE_COLUMNS);writer.writeheader()
    for uid in CANDIDATES:writer.writerow({'universe_id':uid})
    return stream.getvalue()


def import_playtests(session,content,now=None):
    reader=csv.DictReader(io.StringIO(content));count=0;now=now or utcnow()
    if not reader.fieldnames or not set(NOTE_COLUMNS).issubset(reader.fieldnames):
        raise ValueError('Use the downloadable playtest CSV template with all column headers')
    for number,row in enumerate(reader,2):
        if not any(str(row.get(k) or '').strip() for k in NOTE_COLUMNS if k!='universe_id'):continue
        uid=int(row['universe_id'])
        if row.get('source_type') and row['source_type']!='human_playtest':
            raise ValueError(f'Row {number}: AI/unverified notes cannot be imported as human playtests')
        if uid not in CANDIDATES or not session.get(Game,uid):raise ValueError(f'Row {number}: unknown research candidate')
        researcher=(row.get('researcher') or '').strip();evidence=(row.get('evidence') or '').strip()
        raw_date=(row.get('observed_at_utc') or '').strip()
        if not raw_date.endswith('Z') and not any(sign in raw_date[10:] for sign in '+-'):
            raise ValueError(f'Row {number}: observed_at_utc needs Z or an explicit timezone offset')
        observed=parse_time(raw_date)
        values={k:(row.get(k) or '').strip() for k in NOTE_FIELDS}
        observed_fields=[value for key,value in values.items() if key not in ('development_complexity','marketing_potential')]
        if not researcher or not evidence or not any(observed_fields) or not observed or observed>now:
            raise ValueError(f'Row {number}: researcher, evidence, at least one observed field and a past observation date are required')
        for key in ('development_complexity','marketing_potential'):
            if values[key]:
                score=float(values[key])
                if not score.is_integer() or not 1<=score<=5:raise ValueError(f'Row {number}: {key} must be an integer 1–5')
                values[key]=int(score)
            else:values[key]=None
        canonical={'universe_id':uid,'researcher':researcher,'observed_at':observed.isoformat(),'evidence':evidence,'observations':values}
        identifier=hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if session.get(PlaytestNote,identifier):continue
        session.add(PlaytestNote(id=identifier,universe_id=uid,researcher=researcher,observed_at=observed,
            entered_at=now,source_type='human_playtest',evidence=evidence,observations=values))
        count+=1
    return count
