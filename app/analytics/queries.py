import pandas as pd
from sqlalchemy import select
from app.database.models import Game, Snapshot, DiscoveryAppearance, CollectionRun
from app.database.session import database, utcnow
from app.analytics.metrics import game_metrics, threshold_crossings


def load_data(settings=None):
    engine, _ = database(settings)
    try:
        with engine.connect() as connection:
            games = pd.read_sql(select(Game).where(Game.archived.is_(False)), connection)
            snapshots = pd.read_sql(select(Snapshot).join(Game).where(Game.archived.is_(False)), connection)
            appearances = pd.read_sql(select(DiscoveryAppearance).join(Game).where(Game.archived.is_(False)), connection)
            runs = pd.read_sql(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(24), connection)
        for frame, columns in ((games, ["created_at", "updated_at", "first_seen_at", "last_seen_at"]),
                               (snapshots, ["timestamp", "game_updated_at"]), (appearances, ["timestamp"])):
            for column in columns:
                frame[column] = pd.to_datetime(frame[column])
        return games, snapshots, appearances, runs
    finally:
        engine.dispose()


def build_market(games, snapshots, appearances, now=None):
    if snapshots.empty:
        return pd.DataFrame()
    now = now or utcnow()
    grouped = {uid: h for uid, h in snapshots.groupby("universe_id")}
    appearances_by_game = {uid: h for uid, h in appearances.groupby("universe_id")}
    records = []
    for _, game in games.iterrows():
        if game.universe_id in grouped:
            records.append(game_metrics(game, grouped[game.universe_id], appearances_by_game.get(game.universe_id, appearances.iloc[:0]), now))
    frame = pd.DataFrame(records)
    non_numeric = {"name", "creator", "as_of", "stale", "first_seen_at", "source"}
    for column in frame:
        if column not in non_numeric and not column.startswith("baseline_"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def entrants(snapshots, games):
    events = threshold_crossings(snapshots)
    return events.merge(games[["universe_id", "name"]], on="universe_id", how="left")


def comparison_market(market, snapshots, hours, now=None):
    """Compare only a matched cohort; discovery expansion cannot masquerade as share loss."""
    label = {24: "24h", 72: "72h", 168: "7d"}[hours]
    matched = market[(~market.stale) & market[f"delta_{label}"].notna()].copy()
    if matched.empty:
        return matched
    current_total = matched.ccu.sum()
    prior = matched.ccu - matched[f"delta_{label}"]
    prior_total = prior.sum()
    matched["share_change_pp"] = (matched.ccu / current_total - prior / prior_total) * 100 if current_total > 0 and prior_total > 0 else None
    return matched
