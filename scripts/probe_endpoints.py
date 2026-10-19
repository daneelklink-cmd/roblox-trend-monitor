"""Read-only live verification; writes exact response keys, not speculative docs."""
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, Settings
from app.collectors.http import PublicClient
from app.collectors.providers import ExploreDiscovery, RobloxMetadata, RobloxMetrics
from app.database.session import utcnow

settings = Settings()
client = PublicClient(settings.interval)
try:
    discovery = ExploreDiscovery(client, settings)
    appearances = discovery.discover()
    ids = list(dict.fromkeys(x.universe_id for x in appearances))[:2]
    metadata = RobloxMetadata(client).fetch(ids)
    votes = RobloxMetrics(client).fetch(ids)
    result = {"verified_at_utc": utcnow().isoformat(), "unique_discovered": len({a.universe_id for a in appearances}),
              "sources": sorted({a.source for a in appearances}), "selected_filters": discovery.context,
              "metadata_response_keys": sorted(next(iter(metadata.values()), {}).keys()),
              "votes_response_keys": sorted(next(iter(votes.values()), {}).keys()),
              "metadata_games": len(metadata), "votes_games": len(votes), "failed_requests": client.failed_requests}
    (ROOT / "data/endpoint-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
finally:
    client.close()
