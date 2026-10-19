import pandas as pd
from app.analytics.queries import load_data, build_market, comparison_market
from app.database.session import database
from app.database.models import Snapshot
from datetime import timedelta
from app.reports.generate import generate_reports
from tests.test_collection import run


def test_first_run_reports_have_no_fake_breakouts(settings, now, tmp_path):
    run(settings, now)
    paths = generate_reports(settings, tmp_path / "reports")
    assert len(paths) == 3
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "Insufficient history" in text
        assert "No inferred genre" in text


def test_first_run_numeric_columns_and_history(settings, now):
    run(settings, now)
    games, snapshots, appearances, _ = load_data(settings)
    market = build_market(games, snapshots, appearances, now)
    assert pd.api.types.is_numeric_dtype(market.breakout_score)
    assert market.breakout_score.isna().all()
    assert market.pct_24h.isna().all()
    assert market.iloc[0].ccu == 100


def test_empty_reports(settings, tmp_path):
    paths = generate_reports(settings, tmp_path / "reports")
    assert all("No observations" in path.read_text(encoding="utf-8") for path in paths)


def test_full_week_history_and_market_comparison(settings, now, tmp_path):
    # Deliberately synthetic data stays exclusively in pytest's temporary database.
    run(settings, now)
    engine, Session = database(settings)
    with Session.begin() as session:
        for hours in range(1, 169):
            stamp = now + timedelta(hours=hours)
            session.add(Snapshot(cycle_key=stamp.isoformat(), timestamp=stamp, universe_id=1,
                                 playing=100+hours*10, visits=1000+hours*100, favorites=50+hours,
                                 game_name_at_time="Test experience", trending_rank=max(1, 100-hours//2)))
    engine.dispose()
    games, snapshots, appearances, _ = load_data(settings)
    market = build_market(games, snapshots, appearances, now + timedelta(hours=168))
    row = market.iloc[0]
    assert row.delta_7d == 1680
    assert row.pct_7d == 1680
    assert row.peak_24h == 1780
    assert pd.notna(row.avg_72h) and pd.notna(row.breakout_score)
    assert comparison_market(market, snapshots, 168).iloc[0].share_change_pp == 0
    paths = generate_reports(settings, tmp_path / "reports")
    assert len(paths) == 3
