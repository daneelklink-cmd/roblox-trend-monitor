"""Foreground hourly scheduler. Keep this process running for continuous collection."""
from datetime import timezone
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from app.collect import setup_logging
from app.services.collection import collect


def run_cycle():
    try:
        collect()
        from app.reports.generate import generate_reports
        generate_reports()
    except Exception:
        logging.exception("Scheduled cycle failed; next hourly run remains scheduled")


def create_scheduler():
    scheduler = BlockingScheduler(timezone=timezone.utc)
    scheduler.add_job(run_cycle, "cron", minute=0, max_instances=1, coalesce=True, misfire_grace_time=900)
    return scheduler


def main():
    setup_logging()
    scheduler = create_scheduler()
    run_cycle()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        if scheduler.running:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
