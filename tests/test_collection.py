from datetime import timedelta
import httpx
from sqlalchemy import select, func
from app.collectors.http import PublicClient, SourceError
from app.collectors.providers import Appearance, RobloxMetadata, ExploreDiscovery
from app.services.collection import collect
from app.database.session import database
from app.database.models import Game, Snapshot, DiscoveryAppearance
import pytest


class FakeClient:
    failed_requests = 0


class Discovery:
    def __init__(self, entries):
        self.entries = entries

    def discover(self):
        return self.entries


class Metadata:
    def __init__(self, name="Test experience", omit=False):
        self.name, self.omit = name, omit

    def fetch(self, ids):
        return {} if self.omit else {uid: {"id": uid, "name": self.name, "playing": 100, "visits": 1000, "favoritedCount": 50,
                "creator": {"id": 10, "name": "Creator"}, "created": "2026-01-01T00:00:00Z", "updated": "2026-10-19T00:00:00Z"} for uid in ids}


class Votes:
    def fetch(self, ids):
        return {}


def run(settings, now, discovery=None, metadata=None):
    return collect(settings, FakeClient(), discovery or Discovery([Appearance(1, "top-trending", 2, 100, "Test experience")]), metadata or Metadata(), Votes(), now)


def test_duplicate_prevention_and_missing_votes(settings, now):
    assert run(settings, now)["snapshots_written"] == 1
    assert run(settings, now + timedelta(minutes=10))["snapshots_written"] == 0
    engine, Session = database(settings)
    with Session() as s:
        assert s.scalar(select(func.count()).select_from(Snapshot)) == 1
        assert s.scalar(select(func.count()).select_from(DiscoveryAppearance)) == 1
        assert s.scalar(select(Snapshot)).up_votes is None
    engine.dispose()


def test_disappearing_games_continue_and_titles_retained(settings, now):
    run(settings, now)
    run(settings, now + timedelta(hours=1), Discovery([]), Metadata("[UPDATE] Renamed"))
    engine, Session = database(settings)
    with Session() as s:
        snapshots = s.scalars(select(Snapshot).order_by(Snapshot.timestamp)).all()
        assert [x.game_name_at_time for x in snapshots] == ["Test experience", "[UPDATE] Renamed"]
        assert snapshots[-1].trending_rank is None
        assert s.get(Game, 1).current_discovery_source is None
    engine.dispose()


def test_missing_api_metrics_never_fabricated(settings, now):
    summary = run(settings, now, metadata=Metadata(omit=True))
    assert summary["snapshots_written"] == 0
    assert summary["failed_games"] == 1
    assert summary["status"] == "partial"


def test_archived_games_not_refreshed(settings, now):
    run(settings, now)
    engine, Session = database(settings)
    with Session.begin() as s:
        s.get(Game, 1).archived = True
    engine.dispose()
    assert run(settings, now + timedelta(hours=1))["snapshots_written"] == 0


def test_retry_respects_rate_limit_and_recovers():
    calls, delays = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3"}) if len(calls) == 1 else httpx.Response(200, json={"data": []})
    client = PublicClient(interval=0, transport=httpx.MockTransport(handler), sleep=delays.append)
    assert client.get("https://games.roblox.com/test") == {"data": []}
    assert 3 in delays and client.failed_requests == 1
    client.close()


def test_long_retry_after_deferred_without_early_retry():
    client = PublicClient(interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "3600"})), sleep=lambda _: None)
    with pytest.raises(SourceError, match="cooldown"):
        client.get("https://games.roblox.com/test")
    assert client.failed_requests == 1
    client.close()


@pytest.mark.parametrize("response", [httpx.Response(403), httpx.Response(200, text="not json")])
def test_failed_api_response(response):
    client = PublicClient(interval=0, transport=httpx.MockTransport(lambda _: response), sleep=lambda _: None)
    with pytest.raises(SourceError):
        client.get("https://games.roblox.com/test")
    client.close()


def test_failed_batch_does_not_drop_other_batches():
    def handler(request):
        if request.url.params["universeIds"].startswith("1,"):
            return httpx.Response(403)
        return httpx.Response(200, json={"data": [{"id": 51, "name": "Still available"}]})
    client = PublicClient(interval=0, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    provider = RobloxMetadata(client)
    assert 51 in provider.fetch(list(range(1, 52)))
    assert provider.failed_batches == 1
    client.close()


def test_discovery_survives_later_page_failure(settings):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"sorts": [{"sortId": "top-trending", "games": [{"universeId": 1}, {"universeId": 1}, {"universeId": 2, "isSponsored": True}]}], "nextSortsPageToken": "next"})
        return httpx.Response(403)
    client = PublicClient(interval=0, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    provider = ExploreDiscovery(client, settings)
    found = provider.discover()
    assert len(found) == 1 and found[0].universe_id == 1
    assert provider.failed_sources == 1
    client.close()
