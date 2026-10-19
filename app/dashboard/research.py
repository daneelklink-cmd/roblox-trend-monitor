"""Research pages extend the existing terminal; all public controls are read-only."""
import json
from types import SimpleNamespace
import pandas as pd
import streamlit as st
from app.analytics.cohorts import cohort_analysis
from app.analytics.opportunities import enrich_market,niche_metrics,DIMENSIONS
from app.analytics.queries import load_research_data
from app.services.classification import export_csv


def cohort_page(games,snapshots,market):
    st.subheader("Launch-cohort research · observed sample")
    st.warning("Creation date is not public launch date. These cohorts describe tracked games only, with visibility-selected admission and delayed observation.")
    followup=st.selectbox("Equal observation-age follow-up",[24,72,168,720],format_func=lambda h:f"{h} hours after tracking began")
    summary,rates,events=cohort_analysis(games,snapshots,market,followup)
    st.dataframe(summary,hide_index=True,width="stretch")
    cohort=st.selectbox("Inspect cohort",summary.cohort.tolist())
    st.markdown("**Milestone outcomes and denominators**")
    st.dataframe(rates[rates.cohort==cohort],hide_index=True,width="stretch")
    st.caption("Ever-observed shares include baseline achievements and mixed follow-up. Equal-age crossing shares exclude baseline-already-above games and require ≥75% hourly coverage plus completed follow-up. Unobserved crossings may still occur between samples. Insufficient follow-up is not failure.")
    st.caption("Peak is the maximum single-game CCU observed in the cohort. Current median/mean use fresh observations only. Created ≤7/30/90d windows overlap; first-observed-week cohorts use Monday UTC.")
    with st.expander("Observed milestone timing intervals / recrossings"):
        st.dataframe(events.merge(games[["universe_id","name"]],on="universe_id"),hide_index=True,width="stretch")
    with st.expander("Creation, first observation and verified launch evidence"):
        st.dataframe(games[["universe_id","name","created_at","first_discovered_at","first_seen_at","public_launch_at","launch_verification","launch_evidence_url"]],hide_index=True,width="stretch")
        st.caption("Public launch stays unknown unless a human supplies verified evidence. Milestone timing starts at the first tracked CCU observation, not an assumed release date.")


def opportunities_page(games,market):
    st.subheader("Market Opportunities")
    st.caption("Observed metrics → research hypotheses. No revenue or profitability estimates.")
    enriched=enrich_market(market,games)
    dimension=st.selectbox("Concept dimension",list(DIMENSIONS))
    horizon=st.selectbox("Opportunity comparison horizon",["24h","72h","7d","30d"])
    classified=enriched[dimension].notna().sum()
    st.caption(f"Classification coverage for {dimension}: {classified}/{len(enriched)} tracked games. Source/confidence are shown below; unverified tags remain hypotheses.")
    niches=niche_metrics(enriched,dimension,horizon)
    st.markdown("**A · Emerging categories**")
    if niches.empty:
        st.info("No classifications for this dimension. Add evidence-labeled manual tags or import a CSV; no gameplay loops are inferred from names.")
    else:
        st.dataframe(niches.sort_values("matched_aggregate_growth_pct",ascending=False),hide_index=True,width="stretch")
        st.caption("Growth and HHI change compare the same games at both endpoints; minimum 3 matched games. Coverage must reach 60% for a supported comparison. Shares/HHI describe this tracked, classified sample, not the Roblox population.")
    st.markdown("**B · Smaller / recently created breakout candidates**")
    emerging=enriched[(enriched.ccu<1000)|(enriched.age_days<=90)]
    st.dataframe(emerging[["universe_id","name","age_days","ccu","pct_6h","pct_24h","pct_72h","pct_7d","pct_30d","drawdown_pct","breakout_score","source"]].sort_values("breakout_score",ascending=False),hide_index=True,width="stretch")
    st.markdown("**C · Competition and D · potential saturation**")
    if len(niches):
        st.dataframe(niches[["niche","tracked_games","fresh_games","matched_games","aggregate_current_ccu","top5_share_pct","hhi","matched_hhi_change","smaller_competitor_growth_pct","recent_games_at_100_ccu","dominant_game_ids","potential_saturation_indicator"]],hide_index=True,width="stretch")
    st.caption("Potential saturation is a hypothesis requiring ≥3 matched competitors, ≥60% history coverage, ≥3 newly observed members, non-positive matched CCU growth and weak current CCU among ≥3 recent games. Discovery expansion is not proof of increasing platform supply or saturation.")
    st.markdown("**E · Opportunity Explorer**")
    genre=st.multiselect("Opportunity genres",sorted(enriched.primary_genre.dropna().unique()))
    loops=st.multiselect("Opportunity core loops",sorted(enriched.core_loop.dropna().unique()))
    age=st.number_input("Opportunity maximum age (days; 0 = any)",min_value=0,value=90)
    minimum=st.number_input("Opportunity minimum CCU",min_value=0,value=0)
    maximum=st.number_input("Opportunity maximum CCU",min_value=0,value=10000)
    competitors=st.number_input("Maximum observed competitors per selected concept (0 = any)",min_value=0,value=0)
    growth_filter=st.checkbox("Require observed positive opportunity growth")
    selected=enriched[(enriched.ccu>=minimum)&(enriched.ccu<=maximum)]
    if age: selected=selected[selected.age_days<=age]
    if genre: selected=selected[selected.primary_genre.isin(genre)]
    if loops: selected=selected[selected.core_loop.isin(loops)]
    if growth_filter: selected=selected[selected[f"pct_{horizon}"]>0]
    if competitors and len(niches): selected=selected[selected[dimension].isin(niches[niches.tracked_games<=competitors].niche)]
    st.dataframe(selected[["universe_id","name","primary_genre","core_loop","trend_family","age_days","ccu",f"pct_{horizon}","drawdown_pct","classification_source","classification_confidence"]],hide_index=True,width="stretch")
    st.caption(f"{len(selected)} selected games. Confidence is a source/annotator label, not a statistically calibrated probability.")


def coverage_page(games):
    st.subheader("Discovery Coverage & Classification")
    st.warning("No exhaustive chronological public new-release feed is integrated. Keyword search is relevance-ranked and queries rotate; games absent from lists/search remain unseen. Population launch counts and success probabilities are unknown.")
    attempts,sources,missing,watch,candidates=load_research_data()
    if len(attempts):
        latest=attempts.iloc[0]
        st.caption(f"Latest attempt: {latest.started_at} UTC · {latest.status} · {latest.id}")
        st.dataframe(attempts,hide_index=True,width="stretch")
    if len(sources):
        details=[dict(x) if isinstance(x,dict) else json.loads(x) for x in sources.details]
        st.dataframe(pd.DataFrame(details),hide_index=True,width="stretch")
    if len(candidates):
        c=st.columns(3);c[0].metric("Scouted candidates",len(candidates));c[1].metric("Candidates with metadata",int(candidates.created_at.notna().sum()));c[2].metric("In tracked set",int(candidates.admitted.sum()))
        st.dataframe(candidates[["universe_id","created_at","playing","admitted","reason"]],hide_index=True,width="stretch")
    with st.expander("Missing observations (not zero CCU)"):
        st.dataframe(missing,hide_index=True,width="stretch")
    with st.expander("Manual watchlist"):
        st.dataframe(watch,hide_index=True,width="stretch")
        st.code("python -m app.manage watch add UNIVERSE_ID --note 'Research candidate'\npython -m app.manage watch remove UNIVERSE_ID",language="bash")
        st.caption("Removing a watchlist entry does not archive or delete its tracked game.")
    st.markdown("**Manual classifications / CSV workflow**")
    st.code("python -m app.manage export-classifications classifications.csv\npython -m app.manage import-classifications classifications.csv\npython -m app.manage classify UNIVERSE_ID --core-loop 'Plant → Harvest → Sell → Upgrade' --source manual_hypothesis --confidence 0.5",language="bash")
    csv=export_csv([SimpleNamespace(**row) for row in games.to_dict("records")])
    st.download_button("Export classification CSV",csv,file_name="roblox-classifications.csv",mime="text/csv")
    st.caption("Updates/imports run through authenticated SSH/CLI. Public viewers cannot alter classifications, watchlists or launch dates. Official genres are source-provided taxonomy; manual hypotheses and imported unverified labels are never presented as verified gameplay facts.")
