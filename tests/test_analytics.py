from datetime import timedelta
import pandas as pd
import pytest
from app.analytics.metrics import growth, nearest_snapshot, window_stats, breakout_score, threshold_crossings
from app.config import scoring_config


def test_growth_and_zero_denominator():
    assert growth(150, 100) == (50, 50)
    assert growth(0, 100) == (-100, -100)
    assert growth(10, 0) == (10, None)
    assert growth(10, None) == (None, None)


def test_nearest_clock_time_not_previous_row(now):
    history = pd.DataFrame({"timestamp": [now, now - timedelta(hours=1), now - timedelta(hours=24, minutes=20), now - timedelta(hours=26)], "playing": [200, 190, 100, 20]})
    assert nearest_snapshot(history, now, 24).playing == 100
    assert nearest_snapshot(history, now, 72) is None
    assert nearest_snapshot(history.iloc[:1], now, 1) is None


def test_one_hour_does_not_use_nearly_current_baseline(now):
    h = pd.DataFrame({"timestamp": [now - timedelta(minutes=5)], "playing": [100]})
    assert nearest_snapshot(h, now, 1) is None


def test_tolerance_boundaries_and_tie_prefers_earlier(now):
    h = pd.DataFrame({"timestamp": [now - timedelta(hours=24, minutes=90), now - timedelta(hours=22, minutes=30)], "playing": [10, 20]})
    assert nearest_snapshot(h, now, 24).playing == 10
    h.timestamp -= pd.Timedelta(days=1)
    assert nearest_snapshot(h, now, 24) is None


def test_window_rejects_partial_or_sparse_history(now):
    h = pd.DataFrame({"timestamp": [now - timedelta(hours=24), now], "playing": [100, 300]})
    assert window_stats(h, now, 24) == (None, None)
    h = pd.DataFrame({"timestamp": pd.date_range(now - timedelta(hours=24), now, freq="h"), "playing": range(25)})
    assert window_stats(h, now, 24) == (12, 24)


def base_row(**changes):
    row = {"history_hours": 168, "ccu": 5000, "pct_1h": 10, "pct_6h": 150, "pct_24h": 200,
           "pct_72h": 400, "rank_change_24h": 20, "appearance_cycles_24h": 20, "age_days": 20, "positive_steps": 6, "peak_24h": 5000}
    row.update(changes)
    return row


def test_score_rewards_acceleration_not_scale():
    small = breakout_score(base_row())
    huge = breakout_score(base_row(ccu=1_000_000, pct_6h=0, pct_24h=0, pct_72h=0, rank_change_24h=0, positive_steps=0, age_days=1000))
    assert 0 <= huge < small <= 100


def test_score_insufficient_history_stale_and_collapse():
    assert breakout_score(base_row(history_hours=1)) is None
    assert breakout_score(base_row(stale=True)) is None
    assert breakout_score(base_row(pct_6h=None)) is None
    assert breakout_score(base_row(pct_1h=-50, ccu=1000, peak_24h=5000)) < breakout_score(base_row(pct_1h=5, ccu=1000, peak_24h=5000))


def test_score_weights_configurable():
    cfg = scoring_config()
    cfg["weights"] = {"growth_6h": 100}
    assert breakout_score(base_row(pct_6h=200), cfg) == 100


def test_collapse_penalty_also_applies_to_shorter_observed_history():
    collapsed = base_row(history_hours=6, pct_1h=-50, ccu=1000, peak_24h=None, recent_observed_peak=5000)
    assert breakout_score(collapsed) < breakout_score({**collapsed, "pct_1h": 0})


def test_crossings_are_observed_not_baseline(now):
    h = pd.DataFrame({"universe_id": [1, 1, 1, 2], "timestamp": [now-timedelta(hours=2), now-timedelta(hours=1), now, now], "playing": [900, 1200, 6000, 8000]})
    events = threshold_crossings(h)
    actual = events[events.kind == "observed upward crossing"]
    assert len(actual) == 2
    assert actual[actual.threshold == 1000].iloc[0].timestamp == now-timedelta(hours=1)
    assert (events[events.universe_id == 2].kind == "already above at first observation").all()
