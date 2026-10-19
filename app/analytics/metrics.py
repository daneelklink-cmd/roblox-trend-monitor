"""Clock-time comparisons, never arbitrary previous-row comparisons."""
from datetime import timedelta
import math
import pandas as pd
from app.config import scoring_config

HORIZONS = {"1h": 1, "6h": 6, "24h": 24, "72h": 72, "7d": 168}


def nearest_snapshot(history, current_time, hours, tolerance_minutes=90):
    target = pd.Timestamp(current_time) - pd.Timedelta(hours=hours)
    tolerance = pd.Timedelta(minutes=min(tolerance_minutes, hours * 30))
    # A current sample must never act as its own historical baseline.
    eligible = history[history.timestamp < pd.Timestamp(current_time)].copy()
    if eligible.empty:
        return None
    eligible["distance"] = (eligible.timestamp - target).abs()
    eligible = eligible[eligible.distance <= tolerance].sort_values(["distance", "timestamp"])
    return None if eligible.empty else eligible.iloc[0]


def growth(current, previous):
    if previous is None or pd.isna(previous) or current is None or pd.isna(current):
        return None, None
    delta = float(current) - float(previous)
    # Percentage growth from zero is undefined, not infinity or a fabricated 100%.
    return delta, (delta / previous * 100 if previous > 0 else None)


def window_stats(history, now, hours):
    target = pd.Timestamp(now) - pd.Timedelta(hours=hours)
    values = history[(history.timestamp >= target) & (history.timestamp <= pd.Timestamp(now))]
    baseline = nearest_snapshot(history, now, hours)
    # Reject partial-day averages/peaks and sparse intervals disguised as complete windows.
    if baseline is None or len(values) < max(2, math.ceil(hours * 0.75)):
        return None, None
    return float(values.playing.mean()), int(values.playing.max())


def threshold_crossings(snapshots, thresholds=(1000, 5000, 10000, 50000)):
    events = []
    if snapshots.empty:
        return pd.DataFrame(columns=["universe_id", "threshold", "timestamp", "playing", "kind"])
    for uid, history in snapshots.groupby("universe_id"):
        history = history.sort_values("timestamp")
        for threshold in thresholds:
            for i in range(1, len(history)):
                previous, current = history.iloc[i - 1], history.iloc[i]
                if previous.playing < threshold <= current.playing:
                    events.append({"universe_id": uid, "threshold": threshold, "timestamp": current.timestamp,
                                   "playing": current.playing, "kind": "observed upward crossing"})
                    break
            else:
                if history.iloc[0].playing >= threshold:
                    # Baseline is reported separately; it was NOT a newly witnessed crossing.
                    first = history.iloc[0]
                    events.append({"universe_id": uid, "threshold": threshold, "timestamp": first.timestamp,
                                   "playing": first.playing, "kind": "already above at first observation"})
    return pd.DataFrame(events, columns=["universe_id", "threshold", "timestamp", "playing", "kind"])


def breakout_score(row, config=None):
    config = config or scoring_config()
    def valid(value):
        return value is not None and not pd.isna(value)
    if row.get("stale") or row.get("history_hours", 0) < config["minimum_history_hours"] or not valid(row.get("pct_6h")):
        return None
    def clamp(n):
        return max(0.0, min(1.0, n))
    def pct(key):
        value = row.get(key)
        return float(value) if valid(value) else None
    saturation = config["growth_saturation_percent"]
    g6, g24, g72 = (pct(f"pct_{h}") for h in ("6h", "24h", "72h"))
    acceleration = (g6 / 6 - g24 / 24) if g24 is not None else 0
    components = {
        "ccu": clamp(math.log1p(row.get("ccu", 0)) / math.log1p(100000)),
        "growth_6h": clamp(g6 / saturation),
        "growth_24h": clamp((g24 or 0) / saturation),
        "growth_72h": clamp((g72 or 0) / saturation),
        "acceleration": clamp(acceleration / config["acceleration_saturation_percent_per_hour"]),
        "rank_improvement": clamp((row.get("rank_change_24h") or 0) / 25) if valid(row.get("rank_change_24h")) else 0,
        "appearances": clamp(row.get("appearance_cycles_24h", 0) / 24),
        "age": clamp(1 - row.get("age_days", 365) / 90) if valid(row.get("age_days")) else 0,
        "sustained": clamp(row.get("positive_steps", 0) / 6),
    }
    weights = config["weights"]
    score = sum(weights.get(k, 0) * v for k, v in components.items()) / sum(weights.values()) * 100
    g1 = pct("pct_1h")
    observed_peak = row.get("recent_observed_peak", row.get("peak_24h"))
    if g1 is not None and g1 < -20 and valid(observed_peak) and observed_peak > 0 and row["ccu"] < observed_peak * 0.7:
        score -= config["collapse_penalty"]
    return round(max(0, min(100, score)), 1)


def game_metrics(game, history, appearances, now):
    history = history.sort_values("timestamp")
    current = history.iloc[-1]
    asof = current.timestamp
    row = {"universe_id": game.universe_id, "name": game["name"], "creator": game.creator_name,
           "ccu": int(current.playing), "visits": current.visits, "favorites": current.favorites,
           "like_ratio": current.like_ratio, "as_of": asof, "stale": (pd.Timestamp(now) - asof) > pd.Timedelta(hours=2),
           "age_days": (pd.Timestamp(now) - game.created_at).total_seconds() / 86400 if pd.notna(game.created_at) else None,
           "update_age_days": (pd.Timestamp(now) - game.updated_at).total_seconds() / 86400 if pd.notna(game.updated_at) else None,
           "first_seen_at": game.first_seen_at, "source": current.discovery_source or "off discovery lists",
           "trending_rank": current.trending_rank, "top_playing_rank": current.top_playing_rank,
           "history_hours": (asof - history.timestamp.min()).total_seconds() / 3600}
    for label, hours in HORIZONS.items():
        previous = nearest_snapshot(history, asof, hours)
        row[f"delta_{label}"], row[f"pct_{label}"] = growth(current.playing, None if previous is None else previous.playing)
        row[f"baseline_{label}"] = None if previous is None else previous.timestamp
        if label in ("1h", "24h"):
            # Rank improvement uses the same list on both ends; missing is not rank zero.
            a, b = current.trending_rank, None if previous is None else previous.trending_rank
            row[f"rank_change_{label}"] = b - a if pd.notna(a) and pd.notna(b) else None
        if label in ("24h", "72h", "7d"):
            row[f"avg_{label}"], row[f"peak_{label}"] = window_stats(history, asof, hours)
            for metric in ("visits", "favorites"):
                row[f"{metric}_growth_{label}"] = growth(current[metric], None if previous is None else previous[metric])[0]
    row["appearance_count"] = len(appearances)
    row["best_discovery_rank"] = appearances["rank"].min() if not appearances.empty else None
    row["appearance_cycles_24h"] = appearances[appearances.timestamp >= asof - pd.Timedelta(hours=24)].timestamp.nunique() if not appearances.empty else 0
    recent = history[history.timestamp >= asof - pd.Timedelta(hours=6)]
    changes = recent.playing.diff().dropna()
    # Ignore repeated forced/manual observations within minutes as sustained hourly growth.
    gaps = recent.timestamp.diff().dt.total_seconds().iloc[1:]
    row["positive_steps"] = int(((changes > 0) & (gaps >= 1800) & (gaps <= 5400)).sum())
    row["recent_observed_peak"] = int(history[history.timestamp >= asof - pd.Timedelta(hours=24)].playing.max())
    row["breakout_score"] = breakout_score(row)
    return row
