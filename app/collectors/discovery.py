"""Public search + existing Explore; no exhaustive new-launch claim."""
import logging
import uuid
from datetime import datetime, timezone
from app.collectors.providers import Appearance, ExploreDiscovery
from app.collectors.http import SourceError
from app.config import discovery_config

log = logging.getLogger(__name__)


class SearchDiscovery:
    URL = "https://apis.roblox.com/search-api/omni-search"

    def __init__(self, client, config=None, now=None):
        self.client = client
        self.config = config or discovery_config()
        self.now = now or datetime.now(timezone.utc)
        self.coverage = []
        self.failed_sources = 0

    def queries(self):
        rotation = list(dict.fromkeys(self.config["core_queries"] + self.config["rotating_queries"]))
        count = min(max(0, self.config["queries_per_cycle"]), len(rotation))
        start = (int(self.now.timestamp() // 3600) * count) % max(1, len(rotation))
        return [rotation[(start+i) % len(rotation)] for i in range(count)]

    def discover(self):
        # Search has a tighter observed throttle than metadata. Keep its pacing
        # independent, and restore the normal metadata interval afterwards.
        previous = getattr(self.client, "interval", None)
        if previous is not None:
            self.client.interval = max(previous, self.config.get("search_interval_seconds", 10))
        try:
            return self._discover()
        finally:
            if previous is not None:
                self.client.interval = previous

    def _discover(self):
        found = {}
        for query in self.queries():
            source = "search:" + query
            params = {"searchQuery": query, "sessionId": str(uuid.uuid4()), "pageType": "all"}
            pages, rank, error, seen = 0, 0, None, set()
            for _ in range(self.config["search_pages"]):
                try:
                    data = self.client.get(self.URL, params)
                    if not isinstance(data.get("searchResults"), list):
                        raise SourceError("Search schema changed: no searchResults")
                    pages += 1
                    for group in data["searchResults"]:
                        for game in group.get("contents") or []:
                            if not game.get("universeId"):
                                continue
                            rank += 1
                            if game.get("isSponsored"):
                                continue
                            try:
                                uid = int(game["universeId"])
                                if uid > 0:
                                    found.setdefault((uid, source), Appearance(uid, source, rank, game.get("rootPlaceId"), game.get("name")))
                            except (ValueError, TypeError):
                                log.warning("Invalid search game: %r", game)
                    token = data.get("nextPageToken")
                    if not token or token in seen:
                        break
                    seen.add(token)
                    params["pageToken"] = token
                except SourceError as exc:
                    error = str(exc)
                    self.failed_sources += 1
                    log.warning("Search source failed query=%s: %s", query, exc)
                    break
            self.coverage.append({"source": source, "pages": pages, "page_limit": self.config["search_pages"], "unique_games": len({uid for uid,s in found if s == source}), "error": error, "scope": "relevance-ranked keyword results; no chronological launch feed"})
        return list(found.values())


class CombinedDiscovery:
    def __init__(self, client, settings):
        self.explore = ExploreDiscovery(client, settings)
        self.search = SearchDiscovery(client)
        self.context, self.coverage = {}, []
        self.failed_sources = 0

    def discover(self):
        found = self.explore.discover()
        self.context = self.explore.context
        for source in sorted({a.source for a in found}):
            self.coverage.append({"source": source, "unique_games": len({a.universe_id for a in found if a.source == source}), "error": None, "scope": "Explore list; visibility-selected sample", "page_limit": self.explore.settings.discovery_pages})
        if self.explore.failed_sources:
            self.coverage.append({"source": "explore", "error": "One or more pages failed", "scope": "partial results retained"})
        self.failed_sources += self.explore.failed_sources
        if discovery_config()["search_enabled"]:
            found += self.search.discover()
            self.coverage += self.search.coverage
            self.failed_sources += self.search.failed_sources
        return found


def select_candidates(appearances, metadata, settings, now, watched=()):
    config = discovery_config()
    rank = {}
    for a in appearances:
        rank[a.universe_id] = min(rank.get(a.universe_id, 10**9), a.rank)
    def age(uid):
        value = metadata.get(uid, {}).get("created")
        try:
            created = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
            return (now-created).total_seconds()/86400
        except (ValueError, AttributeError, TypeError):
            return float("inf")
    ids = list(rank)
    young = sorted([uid for uid in ids if 0 <= age(uid) <= config["young_days"]], key=lambda u: (0 if age(u)<=7 else 1 if age(u)<=30 else 2, age(u), rank[u]))
    small = sorted([uid for uid in ids if isinstance(metadata.get(uid,{}).get("playing"), int) and 0<=metadata[uid]["playing"]<config["small_ccu"]], key=lambda u: (metadata[u]["playing"]==0, age(u), rank[u]))
    selected, reasons = [], {}
    def add(candidates, limit, reason):
        admitted = 0
        for uid in candidates:
            if uid not in reasons and admitted < limit:
                selected.append(uid); reasons[uid]=reason; admitted+=1
    add(watched, len(watched), "manual_watchlist")
    add(young, int(settings.target_games*config["young_fraction"]), "young_creation_date")
    add(small, int(settings.target_games*config["small_fraction"]), "small_ccu")
    add(sorted(ids, key=lambda u: rank[u]), max(0, settings.target_games-len(selected)), "source_rank")
    return selected, reasons
