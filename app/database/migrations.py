"""Additive v2 migration: retain all existing games, snapshots and constraints."""
from sqlalchemy import inspect
from sqlalchemy.schema import CreateColumn
from app.database.models import Game


def migrate(engine):
    present = {c["name"] for c in inspect(engine).get_columns("games")}
    missing = [c for c in Game.__table__.columns if c.name not in present]
    if not missing:
        return
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        # Recheck under the write lock when dashboard/collector start together.
        present = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(games)")}
        for column in missing:
            if column.name not in present:
                if not column.nullable:
                    raise RuntimeError(f"Explicit migration needed for nonnullable column {column.name}")
                ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
                connection.exec_driver_sql(f"ALTER TABLE games ADD COLUMN {ddl}")
