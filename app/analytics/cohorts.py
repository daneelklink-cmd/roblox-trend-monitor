"""Descriptive observed cohorts. No all-launch probability estimates."""
import math
import pandas as pd
from app.database.session import utcnow

THRESHOLDS=(100,500,1000,5000,10000)


def milestone_events(snapshots):
    records=[]
    if not snapshots.empty:
        for uid,h in snapshots.groupby("universe_id"):
            h=h.sort_values("timestamp");first=h.iloc[0]
            for threshold in THRESHOLDS:
                ups=[i for i in range(1,len(h)) if h.iloc[i-1].playing<threshold<=h.iloc[i].playing]
                base={"universe_id":uid,"threshold":threshold,"first_observation":first.timestamp,
                      "status":"not_observed","timestamp":pd.NaT,"lower_timestamp":pd.NaT,
                      "elapsed_lower_hours":None,"elapsed_upper_hours":None,"gap_hours":None,"recrossings":0}
                if first.playing>=threshold:
                    base.update(status="baseline_already_above",timestamp=first.timestamp,recrossings=len(ups))
                elif ups:
                    i=ups[0];prior,current=h.iloc[i-1],h.iloc[i]
                    gap=(current.timestamp-prior.timestamp).total_seconds()/3600
                    base.update(status="observed_crossing" if gap<=1.5 else "crossing_after_gap",timestamp=current.timestamp,
                        lower_timestamp=prior.timestamp,elapsed_lower_hours=(prior.timestamp-first.timestamp).total_seconds()/3600,
                        elapsed_upper_hours=(current.timestamp-first.timestamp).total_seconds()/3600,gap_hours=gap,recrossings=len(ups)-1)
                records.append(base)
    frame=pd.DataFrame(records,columns=["universe_id","threshold","first_observation","status","timestamp","lower_timestamp","elapsed_lower_hours","elapsed_upper_hours","gap_hours","recrossings"])
    for c in ("timestamp","lower_timestamp","first_observation"): frame[c]=pd.to_datetime(frame[c])
    return frame


def cohort_members(games,now=None):
    now=pd.Timestamp(now or utcnow())
    result={f"Created ≤{days}d":games[(games.created_at>=now-pd.Timedelta(days=days)) & (games.created_at<=now)].universe_id.tolist() for days in (7,30,90)}
    if not games.empty:
        weeks=games.first_seen_at.dt.to_period("W-SUN").dt.start_time
        for week in sorted(weeks.dropna().unique()):
            result["First observed week "+pd.Timestamp(week).strftime("%Y-%m-%d")]=games.loc[weeks==week,"universe_id"].tolist()
    return result


def cohort_analysis(games,snapshots,market,followup_hours=24,now=None):
    now=pd.Timestamp(now or utcnow()); events=milestone_events(snapshots)
    histories={uid:h.sort_values("timestamp") for uid,h in snapshots.groupby("universe_id")}
    summaries,rates=[],[]
    for cohort,ids in cohort_members(games,now).items():
        selected=market[market.universe_id.isin(ids)] if not market.empty else market
        fresh=selected[~selected.stale] if not selected.empty else selected
        h=snapshots[snapshots.universe_id.isin(ids)]
        summaries.append({"cohort":cohort,"tracked_games":len(ids),"observed_games":len(selected),"fresh_current_games":len(fresh),
            "median_current_ccu":fresh.ccu.median() if len(fresh) else None,"mean_current_ccu":fresh.ccu.mean() if len(fresh) else None,
            "peak_observed_single_game_ccu":h.playing.max() if len(h) else None,
            "median_observed_drawdown_pct":selected.drawdown_pct.median() if len(selected) else None,
            "sustained_growth_24h_games":int((selected.sustained_growth_24h==True).sum()) if len(selected) else 0,
            "sustained_growth_24h_eligible":int(selected.sustained_growth_24h.notna().sum()) if len(selected) else 0})
        for threshold in THRESHOLDS:
            es=events[(events.universe_id.isin(ids)) & (events.threshold==threshold)]
            baselines=int((es.status=="baseline_already_above").sum())
            crossed=es[es.status.isin(["observed_crossing","crossing_after_gap"])]
            eligible,success,missing_followup=0,0,0
            for uid in ids:
                hist=histories.get(uid)
                if hist is None or hist.empty: continue
                if hist.iloc[0].playing>=threshold: continue
                end=hist.iloc[0].timestamp+pd.Timedelta(hours=followup_hours)
                window=hist[hist.timestamp<=end]
                mature=now>=end and hist.timestamp.max()>=end and window.timestamp.dt.floor("h").nunique()>=max(2,math.ceil((followup_hours+1)*0.75))
                if not mature:
                    missing_followup+=1;continue
                eligible+=1
                event=crossed[crossed.universe_id==uid]
                if len(event) and event.iloc[0].timestamp<=end: success+=1
            rates.append({"cohort":cohort,"threshold":threshold,"observed_games":len(es),"baseline_already_above":baselines,
                "ever_observed_reaching":baselines+len(crossed),"share_ever_observed_pct":100*(baselines+len(crossed))/len(es) if len(es) else None,
                "observed_crossings":len(crossed),"crossings_after_gaps":int((crossed.status=="crossing_after_gap").sum()),
                "median_crossing_upper_hours":crossed[crossed.status=="observed_crossing"].elapsed_upper_hours.median() if len(crossed) else None,
                "followup_hours":followup_hours,"eligible_nonbaseline_games":eligible,"crossed_by_followup":success,
                "observed_crossing_share_by_followup_pct":100*success/eligible if eligible else None,
                "insufficient_followup_games":missing_followup,"no_observations_games":len(ids)-len(es)})
    return pd.DataFrame(summaries),pd.DataFrame(rates),events
