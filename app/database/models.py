from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"
    universe_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    place_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(Text)
    creator_name: Mapped[str | None] = mapped_column(Text)
    creator_id: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    current_discovery_source: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    primary_genre: Mapped[str | None] = mapped_column(String)
    secondary_genre: Mapped[str | None] = mapped_column(String)
    core_loop: Mapped[str | None] = mapped_column(String)
    theme: Mapped[str | None] = mapped_column(String)
    trend_family: Mapped[str | None] = mapped_column(String)
    social_mechanic: Mapped[str | None] = mapped_column(String)
    monetization_style: Mapped[str | None] = mapped_column(String)
    classification_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("cycle_key", "universe_id"), Index("ix_snapshot_game_time", "universe_id", "timestamp"))
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_key: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("games.universe_id"), index=True)
    playing: Mapped[int] = mapped_column(BigInteger)
    visits: Mapped[int | None] = mapped_column(BigInteger)
    favorites: Mapped[int | None] = mapped_column(BigInteger)
    up_votes: Mapped[int | None] = mapped_column(BigInteger)
    down_votes: Mapped[int | None] = mapped_column(BigInteger)
    like_ratio: Mapped[float | None] = mapped_column(Float)
    trending_rank: Mapped[int | None] = mapped_column(Integer)
    top_playing_rank: Mapped[int | None] = mapped_column(Integer)
    discovery_source: Mapped[str | None] = mapped_column(Text)
    game_name_at_time: Mapped[str] = mapped_column(Text)
    game_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class DiscoveryAppearance(Base):
    __tablename__ = "discovery_appearances"
    __table_args__ = (UniqueConstraint("cycle_key", "universe_id", "source"), Index("ix_appearance_game_time", "universe_id", "timestamp"))
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_key: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("games.universe_id"), index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    rank: Mapped[int] = mapped_column(Integer)


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    cycle_key: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, default="running")
    summary: Mapped[dict | None] = mapped_column(JSON)
