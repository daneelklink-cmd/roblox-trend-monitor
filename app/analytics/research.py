"""Fixed observational controls and exact-hour comparisons; never causal effects."""
import math
import pandas as pd
from app.database.session import utcnow

CANDIDATES = {10769259605:'Solve The Cube',10770251720:'Get A Grip [BETA]',
    10764412489:'Waddle Obby',10701680071:'SUNYI [HORROR]',10769465606:'ScootX – Build & Ride'}
BERLIN = 'Europe/Berlin'


def utc_stamp(value):
    stamp=pd.Timestamp(value)
    return stamp.tz_convert('UTC').tz_localize(None) if stamp.tzinfo else stamp


def previous_local_hour(value, days):
    local=utc_stamp(value).tz_localize('UTC').tz_convert(BERLIN).tz_localize(None)
    # A repeated or nonexistent DST wall hour has no unique matched-hour baseline.
    prior=(local-pd.DateOffset(days=days)).tz_localize(BERLIN,ambiguous='NaT',nonexistent='NaT')
    return pd.NaT if pd.isna(prior) else prior.tz_convert('UTC').tz_localize(None)


def hour_row(history, target):
    if history.empty or pd.isna(target): return None
    rows=history[history.timestamp.dt.floor('h')==utc_stamp(target).floor('h')]
    return None if rows.empty else rows.sort_values('timestamp').iloc[-1]


def finite(value):
    return value is not None and pd.notna(value)


def change(current, previous, field='playing', percent=False):
    if current is None or previous is None: return None
    a,b=current.get(field),previous.get(field)
    if not finite(a) or not finite(b): return None
    if field!='playing' and a<b: return None  # Counter reset is not negative traffic.
    return (a/b-1)*100 if percent and b>0 else None if percent else a-b


def candidate_metrics(games,snapshots,asof=None):
    asof=utc_stamp(asof or utcnow()).floor('h')
    records=[]
    for uid,name in CANDIDATES.items():
        game=games[games.universe_id==uid]
        history=snapshots[(snapshots.universe_id==uid)&(snapshots.timestamp.dt.floor('h')<=asof)].sort_values('timestamp')
        current=hour_row(history,asof)
        row={'universe_id':uid,'name':game.iloc[0]['name'] if len(game) else name,'as_of_utc':asof,
            'current_missing':current is None,'ccu':None if current is None else current.playing,
            'created_at':game.iloc[0].created_at if len(game) else pd.NaT,
            'first_observed_at':game.iloc[0].first_seen_at if len(game) else pd.NaT,
            'latest_observation_utc':history.timestamp.max() if len(history) else pd.NaT}
        for label,hours in [('1h',1),('6h',6),('24h',24),('72h',72)]:
            target=asof-pd.Timedelta(hours=hours) if hours<24 else previous_local_hour(asof,hours//24)
            prior=hour_row(history,target)
            row[f'baseline_{label}_utc']=target
            row[f'delta_{label}']=change(current,prior)
            row[f'pct_{label}']=change(current,prior,percent=True)
            row[f'visits_growth_{label}']=change(current,prior,'visits')
            row[f'favorites_growth_{label}']=change(current,prior,'favorites')
        peak=history.playing.max() if len(history) else None
        row['historical_observed_peak_ccu']=peak
        row['drawdown_pct']=(current.playing/peak-1)*100 if current is not None and finite(peak) and peak>0 else None
        prior_high=history[history.timestamp.dt.floor('h')<asof].playing.max()
        row['signal']='missing_current' if current is None else 'first_observation' if pd.isna(prior_high) else 'new_observed_high' if current.playing>prior_high else 'at_observed_high' if current.playing==peak else 'recovery_below_observed_peak' if finite(row['delta_6h']) and row['delta_6h']>0 else 'below_observed_peak'
        window=history[history.timestamp.dt.floor('h')>=asof-pd.Timedelta(hours=24)]
        row['observations_24h']=window.timestamp.dt.floor('h').nunique()
        enough=hour_row(history,asof-pd.Timedelta(hours=24)) is not None and current is not None and row['observations_24h']>=19
        row['avg_24h']=float(window.playing.mean()) if enough else None
        row['peak_24h']=int(window.playing.max()) if enough else None
        steps=window.playing.diff(); gaps=window.timestamp.diff().dt.total_seconds()
        row['sustained_growth_24h']=bool(row['delta_24h']>0 and (steps.iloc[1:]>0).mean()>=.6) if enough and finite(row['delta_24h']) and gaps.iloc[1:].max()<=5400 else None
        records.append(row)
    return pd.DataFrame(records)


def official_genre(game):
    raw=game.get('metadata_json')
    return raw.get('genre_l1') if isinstance(raw,dict) else None


def select_controls(candidate_id,games,snapshots,asof,count=20):
    """Select once; no future performance or dynamic substitution enters selection."""
    asof=utc_stamp(asof)
    eligible_snapshots=snapshots[snapshots.timestamp<=asof].sort_values('timestamp').groupby('universe_id').tail(1)
    candidates=games.merge(eligible_snapshots[['universe_id','playing','timestamp']],on='universe_id')
    candidates=candidates[(candidates.timestamp>=asof-pd.Timedelta(hours=2))&(~candidates.archived)&(candidates.playing>0)].copy()
    candidates['official_genre']=candidates.apply(official_genre,axis=1)
    candidates['age_days']=(asof-candidates.created_at).dt.total_seconds()/86400
    target=candidates[candidates.universe_id==candidate_id]
    if target.empty: raise ValueError(f'Candidate {candidate_id} has no fresh positive CCU for control selection')
    target=target.iloc[0]
    pool=candidates[(~candidates.universe_id.isin(CANDIDATES))&(candidates.age_days>=0)].copy()
    records=[]
    for _,game in pool.iterrows():
        if not finite(game.age_days) or not finite(target.age_days): continue
        ratio=game.playing/target.playing
        age_gap=abs(game.age_days-target.age_days)
        same=bool(target.official_genre and game.official_genre==target.official_genre)
        tier=0 if same and .2<=ratio<=5 and age_gap<=90 else 1 if same and .1<=ratio<=10 and age_gap<=365 else 2 if .2<=ratio<=5 and age_gap<=90 else None
        if tier is None: continue
        distance=abs(math.log2(ratio))+.4*min(age_gap/90,5)+(0 if same else 3)
        records.append({'universe_id':int(game.universe_id),'name_at_selection':game['name'],
            'ccu_at_selection':int(game.playing),'age_days_at_selection':float(game.age_days),
            'official_genre':game.official_genre,'selection_tier':tier,'distance':distance,
            'observation_at_selection_utc':game.timestamp.isoformat()+'Z'})
    selected=sorted(records,key=lambda x:(x['selection_tier'],x['distance'],x['universe_id']))[:count]
    method={'target_count':count,'selected_count':len(selected),'candidate_ccu':int(target.playing),
        'candidate_age_days':float(target.age_days),'candidate_official_genre':target.official_genre,
        'rule':'Exclude all five candidates and archived/stale/zero-CCU games. Tier 0: same official genre, CCU ratio 0.2–5, age gap <=90d. Tier 1: same genre, ratio 0.1–10, age gap <=365d. Tier 2: other genre, ratio 0.2–5, age gap <=90d. Sort by tier then abs(log2(CCU ratio)) + 0.4*min(age gap/90,5) + 3 for genre mismatch; tie-break Universe ID.',
        'limitations':'Frozen observational matches selected after candidate discovery. Selection/survivorship bias and regression to mean remain. Not randomized; no causal interpretation. Missing controls are never replaced.'}
    return selected,method


def compare_controls(snapshots,groups,asof=None):
    asof=utc_stamp(asof or utcnow()).floor('h')
    rows,details=[],[]
    histories={uid:h for uid,h in snapshots.groupby('universe_id')}
    empty=snapshots.iloc[:0]
    for group in groups:
        uid=group['candidate_id']; members=group['members']
        for label,hours in [('1h',1),('6h',6),('24h',24),('72h',72)]:
            baseline=asof-pd.Timedelta(hours=hours) if hours<24 else previous_local_hour(asof,hours//24)
            current=hour_row(histories.get(uid,empty),asof)
            previous=hour_row(histories.get(uid,empty),baseline)
            changes=[];missing_current=missing_previous=invalid_baseline=0
            for member in members:
                mid=member['universe_id']; h=histories.get(mid,empty)
                a,b=hour_row(h,asof),hour_row(h,baseline)
                value=change(a,b,percent=True)
                missing_current+=int(a is None);missing_previous+=int(b is None)
                invalid_baseline+=int(b is not None and b.playing==0)
                if value is not None: changes.append(value)
                details.append({'group_id':group['id'],'candidate_id':uid,'control_id':mid,'horizon':label,
                    'as_of_utc':asof,'baseline_utc':baseline,'current_ccu':None if a is None else a.playing,
                    'baseline_ccu':None if b is None else b.playing,'pct_change':value})
            median=float(pd.Series(changes).median()) if changes else None
            candidate_change=change(current,previous,percent=True)
            adequate=len(changes)>=max(10,math.ceil(.75*len(members)))
            rows.append({'group_id':group['id'],'candidate_id':uid,'horizon':label,'as_of_utc':asof,
                'baseline_utc':baseline,'candidate_delta_ccu':change(current,previous),'candidate_pct_change':candidate_change,
                'control_median_pct_change':median,'relative_performance_pp':candidate_change-median if adequate and candidate_change is not None else None,
                'fixed_controls':len(members),'matched_controls':len(changes),'missing_current_controls':missing_current,
                'missing_baseline_controls':missing_previous,'zero_baseline_controls':invalid_baseline,
                'candidate_current_missing':current is None,'candidate_baseline_missing':previous is None,
                'adequate_control_coverage':adequate,'status':'insufficient_candidate_data' if candidate_change is None else 'insufficient_controls' if not adequate else 'observed_comparison',
                'comparison_type':'same Berlin wall hour on previous local date' if hours>=24 else 'elapsed-hour comparison'})
    return pd.DataFrame(rows,columns=['group_id','candidate_id','horizon','as_of_utc','baseline_utc','candidate_delta_ccu','candidate_pct_change','control_median_pct_change','relative_performance_pp','fixed_controls','matched_controls','missing_current_controls','missing_baseline_controls','zero_baseline_controls','candidate_current_missing','candidate_baseline_missing','adequate_control_coverage','status','comparison_type']),pd.DataFrame(details,columns=['group_id','candidate_id','control_id','horizon','as_of_utc','baseline_utc','current_ccu','baseline_ccu','pct_change'])
