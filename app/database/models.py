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
    progression_system: Mapped[str | None] = mapped_column(Text)
    classification_source: Mapped[str | None] = mapped_column(Text)
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    classification_meta: Mapped[dict | None] = mapped_column(JSON)
    public_launch_at: Mapped[datetime | None] = mapped_column(DateTime)
    launch_evidence_url: Mapped[str | None] = mapped_column(Text)
    launch_verification: Mapped[str | None] = mapped_column(String)
    first_discovered_at: Mapped[datetime | None] = mapped_column(DateTime)


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


class CollectionAttempt(Base):
    __tablename__ = "collection_attempts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    cycle_key: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String)
    summary: Mapped[dict | None] = mapped_column(JSON)


class SourceRun(Base):
    __tablename__ = "discovery_source_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("collection_attempts.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    details: Mapped[dict] = mapped_column(JSON)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (UniqueConstraint("attempt_id", "universe_id"), Index("ix_candidate_game_time", "universe_id", "timestamp"))
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("collection_attempts.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    universe_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    playing: Mapped[int | None] = mapped_column(BigInteger)
    sources: Mapped[list] = mapped_column(JSON)
    admitted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String)


class MissingObservation(Base):
    __tablename__ = "missing_observations"
    __table_args__ = (Index("ix_missing_game_time", "universe_id", "timestamp"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("collection_attempts.id"), index=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("games.universe_id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    reason: Mapped[str] = mapped_column(String)


class WatchEntry(Base):
    __tablename__ = "watchlist"
    universe_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ClassificationHistory(Base):
    __tablename__ = "classification_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("games.universe_id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    values_json: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)
