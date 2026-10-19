import logging
import time
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from app.config import Settings
from app.collectors.http import PublicClient
from app.collectors.providers import ExploreDiscovery, RobloxMetadata, RobloxMetrics, Appearance
from app.database.models import Game, Snapshot, DiscoveryAppearance, CollectionRun
from app.database.session import database, utcnow, parse_time
from app.services.locking import collector_lock

log = logging.getLogger(__name__)


def collect(settings=None, client=None, discovery=None, metadata=None, metrics=None, now=None):
    settings = settings or Settings()
    with collector_lock(settings.database.with_suffix(".collector.lock")):
        return _cycle(settings, client, discovery, metadata, metrics, now)


def _cycle(settings, client, discovery, metadata, metrics, now):
    started = time.monotonic()
    now = now or utcnow()
    cycle_key = now.strftime("%Y-%m-%dT%H:00:00Z")
    engine, Session = database(settings)
    owned_client = client is None
    client = client or PublicClient(settings.interval)
    discovery = discovery or ExploreDiscovery(client, settings)
    metadata = metadata or RobloxMetadata(client)
    metrics = metrics or RobloxMetrics(client)
    summary = {"cycle": cycle_key, "games_discovered": 0, "new_games": 0, "snapshots_written": 0, "failed_games": 0, "failed_requests": 0}
    try:
        with Session.begin() as session:
            run = session.get(CollectionRun, cycle_key)
            if run is None:
                session.add(CollectionRun(cycle_key=cycle_key, started_at=now))
            else:
                run.status = "running"
            existing = {g.universe_id: g.archived for g in session.scalars(select(Game))}
        try:
            appearances = discovery.discover()
        except Exception:
            log.exception("Discovery provider failed; refreshing all previously tracked games")
            appearances = []
            summary["discovery_failed"] = True
        appearances += [Appearance(uid, "manual-seed", i + 1) for i, uid in enumerate(settings.seed_ids)]
        summary["games_discovered"] = len({a.universe_id for a in appearances})
        # Admit a balanced set by list rank, not just the first list. Never evict tracked games.
        priority = {"top-trending": 0, "up-and-coming": 1, "top-playing-now": 2}
        candidates = list(dict.fromkeys(a.universe_id for a in sorted(appearances, key=lambda a: (a.rank, priority.get(a.source, 3), a.source))))
        candidates = list(dict.fromkeys(settings.seed_ids + candidates))[:settings.target_games]
        tracked = {uid for uid, archived in existing.items() if not archived}
        tracked.update(uid for uid in candidates if not existing.get(uid, False))
        ids = sorted(tracked)
        by_game = defaultdict(list)
        for a in appearances:
            if a.universe_id in tracked:
                by_game[a.universe_id].append(a)
        rows = metadata.fetch(ids)
        votes = metrics.fetch(ids)
        for uid in ids:
            try:
                with Session.begin() as session:
                    row = rows.get(uid)
                    observed = by_game[uid]
                    game = session.get(Game, uid)
                    if game is None:
                        fallback = next((a for a in observed if a.name), None)
                        if not row and not fallback:
                            summary["failed_games"] += 1
                            log.warning("No metadata for newly discovered universe %s", uid)
                            continue
                        game = Game(universe_id=uid, name=row["name"] if row else fallback.name,
                                    place_id=row.get("rootPlaceId") if row else fallback.place_id,
                                    first_seen_at=now, last_seen_at=now)
                        session.add(game)
                        session.flush()
                        summary["new_games"] += 1
                    sources = sorted({a.source for a in observed})
                    game.current_discovery_source = ",".join(sources) or None
                    for a in observed:
                        session.execute(insert(DiscoveryAppearance).values(
                            cycle_key=cycle_key, timestamp=now, universe_id=uid, source=a.source, rank=a.rank
                        ).on_conflict_do_nothing(index_elements=["cycle_key", "universe_id", "source"]))
                    if row is None:
                        summary["failed_games"] += 1
                        log.warning("Metadata missing universe=%s; no fabricated snapshot written", uid)
                        continue
                    game.name = row["name"]
                    game.place_id = row.get("rootPlaceId")
                    creator = row.get("creator") or {}
                    game.creator_name, game.creator_id = creator.get("name"), creator.get("id")
                    game.description = row.get("description")
                    game.created_at, game.updated_at = parse_time(row.get("created")), parse_time(row.get("updated"))
                    game.last_seen_at, game.metadata_json = now, row
                    if not isinstance(row.get("playing"), int) or row["playing"] < 0:
                        summary["failed_games"] += 1
                        log.warning("Invalid or missing CCU universe=%s", uid)
                        continue
                    vote = votes.get(uid, {})
                    up, down = vote.get("upVotes"), vote.get("downVotes")
                    ratio = up / (up + down) if up is not None and down is not None and up + down > 0 else None
                    def rank(source):
                        return min((a.rank for a in observed if a.source == source), default=None)
                    result = session.execute(insert(Snapshot).values(
                        cycle_key=cycle_key, timestamp=now, universe_id=uid, playing=row["playing"],
                        visits=row.get("visits"), favorites=row.get("favoritedCount"), up_votes=up, down_votes=down,
                        like_ratio=ratio, trending_rank=rank("top-trending"), top_playing_rank=rank("top-playing-now"),
                        discovery_source=game.current_discovery_source, game_name_at_time=game.name,
                        game_updated_at=game.updated_at,
                    ).on_conflict_do_nothing(index_elements=["cycle_key", "universe_id"]))
                    summary["snapshots_written"] += result.rowcount
            except Exception:
                summary["failed_games"] += 1
                log.exception("Could not persist universe=%s; continuing", uid)
        summary.update(failed_requests=client.failed_requests, tracked_games=len(ids),
                       discovery_context=getattr(discovery, "context", {}),
                       failed_discovery_sources=getattr(discovery, "failed_sources", 0),
                       failed_batches=getattr(metadata, "failed_batches", 0) + getattr(metrics, "failed_batches", 0),
                       duration_seconds=round(time.monotonic() - started, 2))
        partial = any(summary.get(k) for k in ("failed_games", "failed_requests", "failed_discovery_sources", "failed_batches", "discovery_failed"))
        summary["status"] = "partial" if partial else "complete"
        if not ids:
            summary["status"] = "empty"
            log.error("No games available. Discovery may be unavailable; configure RTM_SEED_IDS if needed.")
        with Session.begin() as session:
            run = session.get(CollectionRun, cycle_key)
            run.completed_at, run.status, run.summary = utcnow(), summary["status"], summary
        log.info("Collection complete: %s", summary)
        return summary
    finally:
        if owned_client:
            client.close()
        engine.dispose()
