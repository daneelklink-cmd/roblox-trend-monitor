"""Foreground hourly scheduler. Keep this process running for continuous collection."""
from datetime import timezone
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from app.collect import setup_logging
from app.services.collection import collect


def startup_collection_due(settings=None,now=None):
    """Avoid redundant same-hour API traffic during an idle deployment restart."""
    from sqlalchemy import select
    from app.database.models import CollectionRun,WatchEntry,Snapshot
    from app.database.session import database,utcnow
    now=now or utcnow();key=now.strftime('%Y-%m-%dT%H:00:00Z')
    engine,Session=database(settings)
    try:
        with Session() as session:
            run=session.get(CollectionRun,key)
            if run is None or run.status!='complete':return True
            watched=set(session.scalars(select(WatchEntry.universe_id).where(WatchEntry.active.is_(True))))
            observed=set(session.scalars(select(Snapshot.universe_id).where(Snapshot.cycle_key==key)))
            return not watched.issubset(observed)
    finally:engine.dispose()


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
    if startup_collection_due():run_cycle()
    else:logging.info('Current hour already complete with all watchlist measurements; keeping the next UTC hourly collection')
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        if scheduler.running:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
