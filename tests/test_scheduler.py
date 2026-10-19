from datetime import datetime, timezone
from unittest.mock import Mock
from app import scheduler


def test_hourly_utc_trigger_and_single_instance():
    service = scheduler.create_scheduler()
    job = service.get_jobs()[0]
    assert job.max_instances == 1
    assert job.coalesce is True
    next_fire = job.trigger.get_next_fire_time(None, datetime(2026, 10, 19, 12, 31, tzinfo=timezone.utc))
    assert next_fire == datetime(2026, 10, 19, 13, 0, tzinfo=timezone.utc)


def test_scheduled_cycle_collects_and_generates_reports(monkeypatch):
    collect, report = Mock(), Mock()
    monkeypatch.setattr(scheduler, "collect", collect)
    monkeypatch.setattr("app.reports.generate.generate_reports", report)
    scheduler.run_cycle()
    collect.assert_called_once()
    report.assert_called_once()


def test_failed_scheduled_cycle_is_logged_and_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(scheduler, "collect", Mock(side_effect=RuntimeError("network offline")))
    scheduler.run_cycle()
    assert "Scheduled cycle failed" in caplog.text
