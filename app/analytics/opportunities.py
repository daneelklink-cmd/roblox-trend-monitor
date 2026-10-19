"""Opportunity indicators describe the tracked sample, never demand or profit."""
import json
import pandas as pd
from app.database.session import utcnow

WINDOWS={"24h":24,"72h":72,"7d":168,"30d":720}
DIMENSIONS=("primary_genre","secondary_genre","core_loop","theme","trend_family")


def enrich_market(market,games):
    if market.empty: return market
    columns=["universe_id",*DIMENSIONS,"social_mechanic","progression_system","monetization_style","classification_source","classification_confidence","classification_meta","public_launch_at","launch_evidence_url","launch_verification","created_at"]
    return market.merge(games[columns],on="universe_id",how="left")


def concentration(values):
    total=values.sum()
    if total<=0: return None,None
    shares=values/total
    return float((shares**2).sum()*10000),float(shares.nlargest(5).sum()*100)


def niche_metrics(market,dimension="primary_genre",horizon="24h",now=None):
    if market.empty or dimension not in market: return pd.DataFrame()
    now=pd.Timestamp(now or utcnow());records=[];hours=WINDOWS[horizon]
    for name,g in market.dropna(subset=[dimension]).groupby(dimension):
        if not str(name).strip(): continue
        fresh=g[~g.stale]
        matched=fresh[fresh[f"delta_{horizon}"].notna()]
        hhi,share=concentration(fresh.ccu)
        change,median,smaller,delta_hhi=None,None,None,None
        if len(matched)>=3:
            prior=matched.ccu-matched[f"delta_{horizon}"]
            if prior.sum()>0: change=(matched.ccu.sum()/prior.sum()-1)*100
            median=matched[f"pct_{horizon}"].median()
            small=matched[matched.ccu<1000]
            prev=small.ccu-small[f"delta_{horizon}"]
            if len(small)>=3 and prev.sum()>0: smaller=(small.ccu.sum()/prev.sum()-1)*100
            old_hhi,_=concentration(prior);new_hhi,_=concentration(matched.ccu)
            if old_hhi is not None and new_hhi is not None: delta_hhi=new_hhi-old_hhi
        young=fresh[fresh.age_days<=30]
        new_members=int((g.first_seen_at>=now-pd.Timedelta(hours=hours)).sum())
        enough=len(matched)>=3 and len(fresh)>0 and len(matched)/len(fresh)>=0.6
        saturation=bool(enough and change is not None and change<=0 and new_members>=3 and len(young)>=3 and young.ccu.median()<500)
        evidence=[]
        for _,row in g.iterrows():
            meta=row.classification_meta
            if isinstance(meta,str): meta=json.loads(meta)
            evidence.append((meta or {}).get(dimension,{}).get("source","unknown"))
        records.append({"niche":name,"dimension":dimension,"tracked_games":len(g),"fresh_games":len(fresh),"matched_games":len(matched),
            "history_coverage_pct":100*len(matched)/len(fresh) if len(fresh) else 0,"aggregate_current_ccu":int(fresh.ccu.sum()),
            "median_current_ccu":fresh.ccu.median() if len(fresh) else None,"matched_aggregate_growth_pct":change,
            "median_game_growth_pct":median,"smaller_competitor_growth_pct":smaller,"newly_observed_members":new_members,
            "recently_created_games":len(young),"recent_game_median_ccu":young.ccu.median() if len(young) else None,
            "recent_games_at_100_ccu":int((young.ccu>=100).sum()),"hhi":hhi,"top5_share_pct":share,
            "matched_hhi_change":delta_hhi,"potential_saturation_indicator":saturation,"adequate_comparison":enough,
            "classification_sources":", ".join(sorted(set(evidence))),
            "dominant_game_ids":", ".join(str(int(x)) for x in fresh.nlargest(5,"ccu").universe_id),
            "horizon":horizon})
    return pd.DataFrame(records)
