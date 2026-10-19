"""Replaceable API boundaries. Discovery is public but undocumented/unstable."""
import logging
import uuid
from dataclasses import dataclass
from typing import Protocol
from app.collectors.http import SourceError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Appearance:
    universe_id: int
    source: str
    rank: int
    place_id: int | None = None
    name: str | None = None


class DiscoveryProvider(Protocol):
    def discover(self) -> list[Appearance]: ...


class GameMetadataProvider(Protocol):
    def fetch(self, ids: list[int]) -> dict[int, dict]: ...


class MetricsProvider(Protocol):
    def fetch(self, ids: list[int]) -> dict[int, dict]: ...


class ExploreDiscovery:
    URL = "https://apis.roblox.com/explore-api/v1/get-sorts"

    def __init__(self, client, settings):
        self.client, self.settings = client, settings
        self.failed_sources = 0
        self.context = {}

    def discover(self):
        params = {"sessionId": str(uuid.uuid4()), "country": self.settings.country, "device": self.settings.device}
        found, seen_tokens = {}, set()
        for _ in range(self.settings.discovery_pages):
            try:
                data = self.client.get(self.URL, params=params)
                if not isinstance(data.get("sorts"), list):
                    raise SourceError("Discovery schema changed: no sorts array")
            except SourceError:
                self.failed_sources += 1
                log.exception("Discovery page unavailable; retaining earlier pages and tracked games")
                break
            for sort in data["sorts"]:
                for item in sort.get("filters") or []:
                    self.context[str(item.get("filterId", "unknown"))] = item.get("selectedOptionId")
                source = str(sort.get("sortId") or sort.get("id") or "unknown")
                for rank, game in enumerate(sort.get("games") or [], 1):
                    try:
                        if game.get("isSponsored"):
                            continue
                        uid = int(game["universeId"])
                        if uid <= 0:
                            continue
                        found.setdefault((uid, source), Appearance(uid, source, rank, game.get("rootPlaceId"), game.get("name")))
                    except (ValueError, TypeError, KeyError):
                        log.warning("Skipping malformed discovery item source=%s item=%r", source, game)
            token = data.get("nextSortsPageToken")
            if not token or token in seen_tokens:
                break
            seen_tokens.add(token)
            params["sortsPageToken"] = token
        return list(found.values())


class BatchedProvider:
    URL = ""

    def __init__(self, client):
        self.client = client
        self.failed_batches = 0

    def fetch(self, ids):
        result = {}
        for start in range(0, len(ids), 50):
            batch = ids[start:start + 50]
            try:
                payload = self.client.get(self.URL, {"universeIds": ",".join(map(str, batch))})
                if not isinstance(payload.get("data"), list):
                    raise SourceError("API schema changed: no data array")
                for row in payload["data"]:
                    try:
                        uid = int(row["id"])
                        if uid in batch:
                            result[uid] = row
                    except (ValueError, TypeError, KeyError):
                        log.warning("Malformed item from %s: %r", self.URL, row)
            except SourceError:
                self.failed_batches += 1
                log.exception("Batch failed for %s; continuing with remaining games", self.URL)
        return result


class RobloxMetadata(BatchedProvider):
    URL = "https://games.roblox.com/v1/games"


class RobloxMetrics(BatchedProvider):
    # CCU, visits and favorites arrive in metadata; votes use this optional endpoint.
    URL = "https://games.roblox.com/v1/games/votes"
