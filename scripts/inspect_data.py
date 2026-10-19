"""Read-only evidence of what is currently stored; also writes data/verification.json."""
import json
import sys
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.database.session import database
from app.config import ROOT


engine, _ = database()
with engine.connect() as connection:
    def rows(sql):
        return [dict(row) for row in connection.execute(text(sql)).mappings()]
    evidence = {
        "counts": rows("SELECT (SELECT count(*) FROM games) games, (SELECT count(*) FROM snapshots) snapshots, (SELECT count(*) FROM discovery_appearances) appearances"),
        "latest_run": rows("SELECT * FROM collection_runs ORDER BY started_at DESC LIMIT 1"),
        "creation_cohorts": rows("SELECT sum(created_at >= datetime('now','-7 days') AND created_at <= datetime('now')) created_7d, sum(created_at >= datetime('now','-30 days') AND created_at <= datetime('now')) created_30d, sum(created_at >= datetime('now','-90 days') AND created_at <= datetime('now')) created_90d FROM games"),
        "latest_attempt": rows("SELECT * FROM collection_attempts ORDER BY started_at DESC LIMIT 1"),
        "history_range": rows("SELECT min(timestamp) first_utc,max(timestamp) last_utc,count(DISTINCT cycle_key) observed_hours FROM snapshots"),
        "latest_candidates": rows("SELECT count(*) candidates,sum(created_at >= datetime('now','-7 days')) young_7d,sum(created_at >= datetime('now','-30 days')) young_30d,sum(playing < 1000) below_1000 FROM discovery_candidates WHERE attempt_id=(SELECT id FROM collection_attempts ORDER BY started_at DESC LIMIT 1)"),
        "example_snapshots": rows("SELECT g.name, s.universe_id, s.timestamp, s.playing, s.visits, s.favorites, s.like_ratio, s.trending_rank FROM snapshots s JOIN games g USING(universe_id) ORDER BY s.playing DESC LIMIT 5"),
        "discovery_sources": rows("SELECT source, count(*) appearances FROM discovery_appearances GROUP BY source ORDER BY appearances DESC"),
        "duplicate_game_cycles": rows("SELECT universe_id, cycle_key, count(*) n FROM snapshots GROUP BY universe_id,cycle_key HAVING count(*) > 1"),
    }
engine.dispose()
content = json.dumps(evidence, indent=2, ensure_ascii=False, default=str)
(ROOT / "data/verification.json").write_text(content, encoding="utf-8")
print(content)
