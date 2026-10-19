from datetime import datetime
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(database=tmp_path / "test.sqlite", target_games=400, interval=0.1)


@pytest.fixture
def now():
    return datetime(2026, 10, 19, 12)
