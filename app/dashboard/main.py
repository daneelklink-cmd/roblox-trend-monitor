"""Launch from the project root: streamlit run app/dashboard/main.py."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
import plotly.express as px
import streamlit as st
from app.analytics.queries import load_data, build_market, entrants, comparison_market
from app.database.session import utcnow
from app.dashboard.research import cohort_page,opportunities_page,coverage_page

st.set_page_config(page_title="Roblox / Market Intelligence", page_icon="↗", layout="wide")
st.markdown("""<style>
.block-container {padding-top:1.8rem; max-width:1800px}
div[data-testid="stMetricValue"] {font-variant-numeric:tabular-nums}
h1 {letter-spacing:-.035em} .stCaption {color:#8b9caf}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def data():
    games, snapshots, appearances, runs = load_data()
    market = build_market(games, snapshots, appearances)
    return games, snapshots, appearances, runs, market


def table(frame, columns=None, key=None, select=False):
    if frame.empty:
        st.info("No matching observations yet. Historical signals need more collection cycles.")
        return None
    columns = columns or ["name", "ccu", "pct_1h", "pct_24h", "pct_72h", "pct_7d", "pct_30d", "breakout_score", "age_days", "trending_rank", "stale"]
    sort_column = st.session_state.get("ranking_sort", "View default")
    if sort_column in frame.columns:
        frame = frame.sort_values(sort_column, ascending=st.session_state.get("ranking_ascending", False), na_position="last")
    shown = frame[[c for c in columns if c in frame]].copy()
    shown = shown.rename(columns={"name": "Game", "ccu": "CCU", "breakout_score": "Breakout Score", "age_days": "Age / days", "trending_rank": "Trending Rank", "pct_1h": "1h %", "pct_6h": "6h %", "pct_24h": "24h %", "pct_72h": "3d %", "pct_7d": "7d %"})
    # Streamlit renders Arrow nulls as "None" even with Styler.na_rep. Use explicit
    # text labels; the sidebar sort runs on the untouched numeric source frame.
    for column in shown:
        if shown[column].isna().any():
            missing = "not listed" if column == "Trending Rank" else "insufficient history"
            shown[column] = shown[column].map(lambda x: missing if pd.isna(x) else (f"{x:,.2f}" if isinstance(x, float) else str(x)))
    options = {"hide_index": True, "width": "stretch", "key": key}
    if select:
        options.update(on_select="rerun", selection_mode="single-row")
    return st.dataframe(shown, **options)


def explorer(games, snapshots, appearances, market):
    if market.empty:
        return
    ids = market.universe_id.tolist()
    remembered = st.session_state.get("selected_universe")
    index = ids.index(remembered) if remembered in ids else 0
    names = market.set_index("universe_id")["name"].to_dict()
    uid = st.selectbox("Select an experience", ids, index=index, format_func=lambda x: f"{names[x]} · {x}")
    game = games[games.universe_id == uid].iloc[0]
    row = market[market.universe_id == uid].iloc[0]
    history = snapshots[snapshots.universe_id == uid].sort_values("timestamp")
    ranks = appearances[appearances.universe_id == uid].sort_values("timestamp")
    c = st.columns(4)
    c[0].metric("Current CCU", f"{row.ccu:,}")
    c[1].metric("Observed all-time peak", f"{int(history.playing.max()):,}")
    c[2].metric("Breakout Score", "insufficient history" if pd.isna(row.breakout_score) else row.breakout_score)
    c[3].metric("Snapshots", len(history))
    if row.stale:
        st.warning("Latest observation is more than two hours old; excluded from breakout rankings.")
    st.caption(f"First seen: {game.first_seen_at} UTC | Created: {game.created_at} | Updated: {game.updated_at} | Latest snapshot: {row.as_of} UTC")
    if pd.notna(game.place_id):
        st.link_button("Open Roblox experience", f"https://www.roblox.com/games/{int(game.place_id)}")
    st.plotly_chart(px.line(history, x="timestamp", y="playing", title="Concurrent players · observed UTC", markers=len(history) < 5), width="stretch")
    if not ranks.empty:
        fig = px.line(ranks, x="timestamp", y="rank", color="source", title="Discovery rank history · each list tracked separately", markers=True)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(px.line(history, x="timestamp", y="visits", title="Cumulative visits", markers=len(history) < 5), width="stretch")
    with right:
        st.plotly_chart(px.line(history, x="timestamp", y="favorites", title="Favorites", markers=len(history) < 5), width="stretch")
    st.subheader("Growth and observation quality")
    table(market[market.universe_id == uid], ["name", "pct_1h", "pct_6h", "pct_24h", "pct_72h", "pct_7d", "pct_30d", "visit_velocity_1h", "visit_velocity_24h", "drawdown_pct", "sustained_growth_24h", "coverage_24h", "avg_24h", "avg_72h", "avg_7d", "avg_30d", "peak_24h", "peak_7d", "rank_change_1h", "rank_change_24h", "best_discovery_rank", "appearance_count", "update_age_days"], key="detail_metrics")
    title_changes = history.loc[history.game_name_at_time.ne(history.game_name_at_time.shift()), ["timestamp", "game_name_at_time"]]
    st.subheader("Observed title history")
    st.dataframe(title_changes, hide_index=True, width="stretch")
    with st.expander("Metadata / classification foundation"):
        st.write(game.description or "No description exposed.")
        st.json({k: None if pd.isna(game[k]) else game[k] for k in ["primary_genre", "secondary_genre", "core_loop", "theme", "trend_family", "social_mechanic", "monetization_style"]})
        st.write("Classification source:",game.classification_source,"Confidence:",game.classification_confidence)
        st.caption("Official genres are Roblox taxonomy. Manual tags require source/confidence labels; hypotheses are unverified.")


def main():
    st.title("ROBLOX / MARKET INTELLIGENCE")
    st.caption("ACCELERATION FIRST · PUBLIC OBSERVATIONS · LOCAL SQLITE · ALL TIMES UTC")
    if st.sidebar.button("Refresh observations"):
        st.cache_data.clear()
        st.rerun()
    games, snapshots, appearances, runs, market = data()
    if market.empty:
        st.info("No observations yet. Run `python -m app.collect` from the project folder, then refresh.")
        if not runs.empty:
            st.dataframe(runs, width="stretch")
        return
    latest = pd.Timestamp(snapshots.timestamp.max())
    st.caption(f"Latest collection: {latest} UTC · {len(games):,} tracked games · cache TTL 60s · use Refresh observations")
    if utcnow() - latest.to_pydatetime() > pd.Timedelta(hours=2):
        st.warning("Collection is stale. Start `python -m app.scheduler` to collect hourly while the process runs.")
    if not runs.empty and runs.iloc[0].status != "complete":
        st.warning(f"Latest collection status: {runs.iloc[0].status}. See collection health below.")
    with st.sidebar:
        st.header("Signal filters")
        name = st.text_input("Game name")
        creator = st.text_input("Creator")
        min_ccu = st.number_input("Minimum CCU", min_value=0, value=0, step=1000)
        max_age = st.number_input("Created within last X days (0 = any)", min_value=0, value=0)
        min_age = st.number_input("Minimum game age / days", min_value=0, value=0)
        score = st.slider("Minimum Breakout Score", 0, 100, 0)
        apply_growth = st.checkbox("Require minimum growth")
        horizon = st.selectbox("Growth horizon", ["24h", "72h", "7d", "30d", "6h", "1h"])
        min_growth = st.number_input("Minimum growth %", value=0.0)
        source_options = sorted(appearances.source.unique().tolist())
        sources = st.multiselect("Discovery source (latest snapshot)", source_options)
        include_stale = st.checkbox("Include stale observations", value=False)
        st.selectbox("Numeric ranking sort", ["View default", "breakout_score", "ccu", "pct_1h", "pct_6h", "pct_24h", "pct_72h", "pct_7d", "age_days", "trending_rank"], key="ranking_sort")
        st.checkbox("Sort ascending", key="ranking_ascending")
        st.caption("Missing history is never treated as zero growth. Filters apply to rankings; Market Overview uses the full tracked cohort.")
    filtered = market[market.ccu >= min_ccu].copy()
    if name:
        filtered = filtered[filtered.name.str.contains(name, case=False, regex=False, na=False)]
    if creator:
        filtered = filtered[filtered.creator.str.contains(creator, case=False, regex=False, na=False)]
    if max_age:
        filtered = filtered[filtered.age_days <= max_age]
    if min_age:
        filtered = filtered[filtered.age_days >= min_age]
    if score:
        filtered = filtered[filtered.breakout_score >= score]
    if apply_growth:
        filtered = filtered[filtered[f"pct_{horizon}"] >= min_growth]
    if sources:
        filtered = filtered[filtered.source.map(lambda s: bool(set(s.split(",")) & set(sources)))]
    if not include_stale:
        filtered = filtered[~filtered.stale]
    tabs = st.tabs(["BREAKOUTS", "TOP PLAYING", "NEW ENTRANTS", "SUSTAINED WINNERS", "DECLINING", "GAME EXPLORER", "MARKET OVERVIEW", "COHORTS", "MARKET OPPORTUNITIES", "DISCOVERY & CLASSIFICATION"])
    with tabs[0]:
        st.subheader("What is accelerating right now?")
        scored = filtered[filtered.breakout_score.notna()].sort_values("breakout_score", ascending=False)
        if scored.empty:
            st.info("Insufficient history for breakout rankings. At least six hours and a valid 6h baseline are required. Current observations are available in Top Playing.")
        event = table(scored, key="breakout_table", select=True)
        if event and event.selection.rows:
            sort_column = st.session_state.get("ranking_sort")
            ordered = scored.sort_values(sort_column, ascending=st.session_state.get("ranking_ascending", False), na_position="last") if sort_column in scored else scored
            st.session_state.selected_universe = int(ordered.iloc[event.selection.rows[0]].universe_id)
            st.caption("Selected game is available in GAME EXPLORER.")
        st.markdown("**Very new experiences · created within 30 days**")
        table(filtered[filtered.age_days <= 30].sort_values("ccu", ascending=False), key="very_new")
    with tabs[1]:
        st.subheader("Current scale · market context")
        table(filtered.sort_values("ccu", ascending=False), key="top_playing")
    with tabs[2]:
        st.subheader("Observed threshold crossings")
        events = entrants(snapshots, games)
        period = st.selectbox("Recent crossing window", [24, 72, 168], format_func=lambda h: f"Last {h} hours")
        events = events[(events.timestamp >= pd.Timestamp(utcnow()) - pd.Timedelta(hours=period)) & events.universe_id.isin(filtered.universe_id)]
        observed = events[events.kind == "observed upward crossing"]
        st.dataframe(observed.sort_values("timestamp", ascending=False), hide_index=True, width="stretch")
        st.caption("First observation already above a threshold is not proof of a new crossing. Crossing times are observation times, not precise real-world event times.")
        with st.expander("Already above threshold when tracking began"):
            st.dataframe(events[events.kind != "observed upward crossing"], hide_index=True, width="stretch")
    with tabs[3]:
        st.subheader("Positive growth across 24h, 3d and 7d")
        winners = filtered[(filtered.pct_24h > 0) & (filtered.pct_72h > 0) & (filtered.pct_7d > 0)]
        table(winners.sort_values("breakout_score", ascending=False), key="winners")
    with tabs[4]:
        st.subheader("Losing players and share in a comparable cohort")
        hours = st.selectbox("Decline horizon", [24, 72, 168, 720])
        label = {24: "24h", 72: "72h", 168: "7d", 720:"30d"}[hours]
        matched = comparison_market(market, snapshots, hours)
        if matched.empty:
            st.info("Insufficient history for matched-cohort player share comparisons.")
        else:
            losers = matched[(matched[f"pct_{label}"] <= -10) & (matched.share_change_pp < 0) & matched.universe_id.isin(filtered.universe_id)]
            table(losers.sort_values(f"delta_{label}"), ["name", "ccu", f"delta_{label}", f"pct_{label}", "share_change_pp"], key="declining")
    with tabs[5]:
        explorer(games, snapshots, appearances, market)
    with tabs[6]:
        st.subheader("Tracked market · not the whole Roblox platform")
        today = pd.Timestamp(utcnow()).normalize()
        fresh = market[~market.stale]
        first_trending = appearances[appearances.source == "top-trending"].groupby("universe_id").timestamp.min()
        cols = st.columns(4)
        cols[0].metric("Tracked CCU (fresh observations)", f"{int(fresh.ccu.sum()):,}")
        cols[1].metric("Tracked games", len(games))
        cols[2].metric("Discovered today", int((games.first_seen_at >= today).sum()))
        cols[3].metric("First observed in Trending today", int((first_trending >= today).sum()))
        hours = st.selectbox("Market comparison", [24, 72, 168, 720], format_func=lambda h: {24: "24h", 72: "3d", 168: "7d", 720:"30d"}[h])
        label = {24: "24h", 72: "72h", 168: "7d", 720:"30d"}[hours]
        matched = comparison_market(market, snapshots, hours)
        if matched.empty:
            st.info("Insufficient history for this market comparison.")
        else:
            st.caption(f"Comparable cohort: {len(matched)} games. Unmatched or stale games are excluded.")
            left, right = st.columns(2)
            with left:
                st.markdown("**Largest CCU gainers**")
                table(matched[matched[f"delta_{label}"] > 0].nlargest(10, f"delta_{label}"), ["name", "ccu", f"delta_{label}", f"pct_{label}"], key="gainers")
            with right:
                st.markdown("**Largest CCU losers**")
                table(matched[matched[f"delta_{label}"] < 0].nsmallest(10, f"delta_{label}"), ["name", "ccu", f"delta_{label}", f"pct_{label}"], key="losers")
            st.markdown("**Fastest-growing new experiences · age ≤30 days**")
            table(matched[(matched.age_days <= 30) & (matched[f"pct_{label}"] > 0)].nlargest(10, f"pct_{label}"), key="new_fastest")
        with st.expander("Collection health / recent runs"):
            st.dataframe(runs, hide_index=True, width="stretch")
        st.caption("Discovery lists are a sampled, potentially regional/device-specific view. No whole-platform market-share claims or inferred genre trends.")
    with tabs[7]: cohort_page(games,snapshots,market)
    with tabs[8]: opportunities_page(games,market)
    with tabs[9]: coverage_page(games)


main()
