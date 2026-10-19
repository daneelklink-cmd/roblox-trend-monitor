import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()


@dataclass
class Settings:
    database: Path = field(default_factory=lambda: ROOT / os.getenv("RTM_DATABASE", "data/market.sqlite"))
    target_games: int = field(default_factory=lambda: max(1, int(os.getenv("RTM_TARGET_GAMES", "400"))))
    interval: float = field(default_factory=lambda: max(0.1, float(os.getenv("RTM_REQUEST_INTERVAL", "0.6"))))
    discovery_pages: int = field(default_factory=lambda: max(1, int(os.getenv("RTM_DISCOVERY_PAGES", "6"))))
    country: str = field(default_factory=lambda: os.getenv("RTM_DISCOVERY_COUNTRY", "all"))
    device: str = field(default_factory=lambda: os.getenv("RTM_DISCOVERY_DEVICE", "computer"))
    seed_ids: list[int] = field(default_factory=lambda: [int(x.strip()) for x in os.getenv("RTM_SEED_IDS", "").split(",") if x.strip()])


def scoring_config():
    return json.loads((ROOT / "config/scoring.json").read_text(encoding="utf-8"))
