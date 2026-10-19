from datetime import datetime, timezone
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.config import Settings
from app.database.models import Base


def utcnow():
    # SQLite stores naive timestamps; every stored timestamp is explicitly UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def database(settings=None):
    settings = settings or Settings()
    settings.database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.database.as_posix()}", connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")

    Base.metadata.create_all(engine)
    from app.database.migrations import migrate
    migrate(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
