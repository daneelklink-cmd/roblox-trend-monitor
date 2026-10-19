# Roblox Trend Monitor

A local, read-only market intelligence terminal for detecting acceleration, new entrants and emerging winners. Python 3.12+, SQLite, SQLAlchemy, httpx, pandas, Streamlit, Plotly and APScheduler. No accounts, cookies, paid services, LLMs or fabricated history.

## Start on Windows

Open PowerShell in this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.collect
.\.venv\Scripts\python.exe -m streamlit run app/dashboard/main.py
```

Open http://127.0.0.1:8501. A fresh clone starts with an empty database; the first collection populates it with real observations. Local databases and virtual environments are excluded from Git. If `python` opens the Microsoft Store or fails, use an installed Python 3.12+ executable or the Windows Python launcher:

```powershell
py -3 -m venv .venv
```

Activation is optional. Explicit `.venv\Scripts\python.exe` commands avoid PowerShell activation-policy problems. For an activated shell, `python -m app.collect` and `streamlit run app/dashboard/main.py` work normally.

## Exact source structure

```text
roblox-trend-monitor/
  .env.example
  .gitignore
  .streamlit/config.toml
  README.md
  requirements.txt
  requirements-lock.txt           # exact environment used for verification
  config/scoring.json
  app/
    __init__.py
    config.py
    collect.py
    scheduler.py
    collectors/
      __init__.py
      http.py                    # request pacing, retry, Retry-After, backoff
      providers.py               # DiscoveryProvider / GameMetadataProvider / MetricsProvider
    services/
      __init__.py
      collection.py              # admission, refresh, persistence, summaries
      locking.py                 # Windows/POSIX crash-safe collector process lock
    database/
      __init__.py
      models.py
      session.py
    analytics/
      __init__.py
      metrics.py                 # baselines, growth, scoring, threshold events
      queries.py                 # dashboard/report data, matched cohorts
    dashboard/
      __init__.py
      main.py
    reports/
      __init__.py
      generate.py
  data/
    .gitkeep
    market.sqlite                # generated real observations, WAL mode
    collector.log                # generated rotating logs
    verification.json            # generated database evidence
    endpoint-verification.json   # generated endpoint evidence
  reports/
    daily/YYYY-MM-DD.md
    3day/YYYY-MM-DD.md
    weekly/YYYY-MM-DD.md
  scripts/
    check_dashboard.py
    inspect_data.py
    probe_endpoints.py
    start-dashboard.ps1
    start-scheduler.ps1
  tests/
    __init__.py
    conftest.py
    test_analytics.py
    test_collection.py
    test_reports_dashboard.py
    test_scheduler.py
```

Runtime directories such as `.venv`, Python caches, logs, SQLite WAL/SHM files and collector locks are not source. SQLite contains `games`, `snapshots`, `discovery_appearances` and `collection_runs`. Classification fields are nullable and intentionally empty. Raw official genre fields are preserved in `games.metadata_json`; no genres or mechanics are guessed.

## Verified public endpoints

1. `GET https://apis.roblox.com/explore-api/v1/get-sorts`
   - **Undocumented public website discovery API**, isolated in `ExploreDiscovery`.
   - Parameters: random `sessionId`; follow the returned `nextSortsPageToken` as `sortsPageToken`. Configurable country/device hints are passed; returned selected filters are recorded because the server may ignore hints or apply regional defaults.
   - Extracts `sorts[].games[].universeId`, `rootPlaceId`, name and original one-based position, keyed by `sortId`. Sponsored items are excluded without renumbering the remaining positions.
   - Verified Trending (`top-trending`), Up-and-Coming, Top Playing Now, Most Popular, genre Trending lists and other available lists. Pagination is capped by configuration. Lists can change or disappear.
2. `GET https://games.roblox.com/v1/games?universeIds=...`
   - Official public metadata endpoint, batches of up to 50.
   - Current `playing`, `visits`, `favoritedCount`, name, creator, root place, description, created/updated timestamps and raw genre metadata.
3. `GET https://games.roblox.com/v1/games/votes?universeIds=...`
   - Official public optional vote metrics, batches of up to 50. `like_ratio = upVotes / (upVotes + downVotes)`; missing or zero-total votes produce null.

Official metadata/voting reference: https://create.roblox.com/docs/cloud/reference/domains/games

Run `python scripts/probe_endpoints.py` to verify the live response schema and selected discovery filters. No authentication, CAPTCHA bypass, proxies or access-control workarounds are used. On 401/403 the request fails clearly. Requests are paced (default 0.6 seconds apart), with at most four attempts for network errors, HTTP 429 or 5xx, exponential backoff plus jitter and respect for Retry-After. A requested cooldown above 120 seconds defers the source instead of retrying early. Errors are logged. Earlier discovery pages and other metadata batches survive partial failure; optional vote failure does not prevent CCU snapshots.

Rank is the position in a specific returned discovery list, **not a universal platform rank**. Device/location, server experiments and partial lists affect it. Keep the same discovery profile for longitudinal work; use a new `RTM_DATABASE` if intentionally changing market/device profiles. `best_discovery_rank` is the lowest position observed in any available list, so its context differs from Trending-specific rank changes. `appearance_count` counts list appearances; the score counts unique hourly appearance cycles instead of awarding extra points for many lists in one hour.

## Configuration and tracking policy

Copy `.env.example` to `.env` or set environment variables in PowerShell. No secrets are required.

- `RTM_TARGET_GAMES=400`: maximum unique discovery candidates admitted each cycle, balanced across lists by rank. **Not a lifetime cap.** Previously tracked games are refreshed indefinitely, so the tracked set can grow beyond 400. Archive games explicitly to stop tracking them.
- `RTM_DATABASE=data/market.sqlite`: path relative to the project, or an absolute path.
- `RTM_DISCOVERY_PAGES=6`, `RTM_REQUEST_INTERVAL=0.6`: discovery budget and pacing.
- `RTM_DISCOVERY_COUNTRY=all`, `RTM_DISCOVERY_DEVICE=computer`: discovery hints; inspect returned context.
- `RTM_SEED_IDS=1686885941,994732206`: optional universe IDs if discovery is unavailable. These are NOT place IDs.

To explicitly archive a game in Python:

```python
from app.database.session import database
from app.database.models import Game
engine, Session = database()
with Session.begin() as session:
    session.get(Game, 1686885941).archived = True
engine.dispose()
```

If a game disappears from discovery, its current source and rank become null while metrics continue. `last_seen_at` means last successful metadata observation; discovery-list history lives in `discovery_appearances`. `first_seen_at` means first observed by this installation, never the game's release date.

## Collection, duplicates and hourly scheduling

```powershell
# One complete cycle
.\.venv\Scripts\python.exe -m app.collect

# Continuous collection (separate terminal; keep it running)
.\.venv\Scripts\python.exe -m app.scheduler

# Reports without collecting again
.\.venv\Scripts\python.exe -m app.reports.generate
```

The scheduler collects immediately, then at minute 00 of every UTC hour, and generates all three report windows after each cycle. Only one scheduled job runs at a time; delayed invocations coalesce. Ctrl+C stops it. It does **not** install a Windows service or survive closing the terminal, shutdown or sleep. Missed history is not backfilled. For unattended use, run `scripts/start-scheduler.ps1` via Windows Task Scheduler at sign-in; configure restart-on-failure and prevent overlapping instances. The application itself also holds an OS file lock to prevent concurrent collector processes.

Each snapshot has the actual observation timestamp in UTC and a separate UTC hour `cycle_key`. `(cycle_key, universe_id)` is unique; appearances are unique by cycle/game/source. Retrying in the same hour fills missing games without adding duplicate observations for games already collected. Metadata can be refreshed on retry, while that hour's original snapshot stays immutable. No synthetic data is inserted to make charts look populated. Indexes cover timestamp, universe ID and `(universe_id, timestamp)`. SQLite uses WAL and busy timeouts for concurrent dashboard reads.

Run health and failures are retained in `collection_runs` and `data/collector.log`. A `partial` run is not silently presented as complete. A completely empty first run exits with code 2. The collector never replaces missing CCU with zero. A temporarily missing game gets no snapshot that hour; it remains tracked.

## Analytics and interpretation

- CCU absolute and percent changes: 1h, 6h, 24h, 72h, 7d.
- For each game, comparison is anchored on its latest observed timestamp. Find the historical snapshot nearest `latest - horizon`, within ±90 minutes (±30 minutes for 1h). Exclude the current sample; ties choose the earlier timestamp. Actual baseline timestamps are retained in analytics.
- No matching history means null / **insufficient history**. Growth from zero has an absolute delta but undefined percentage; it is not reported as infinite growth.
- Average/peak windows (24h, 72h, 7d) require a baseline near the window boundary and at least 75% of the expected hourly samples. These are statistics of observed hourly samples, not exact continuous peaks or time-weighted averages.
- Visits/favorites growth uses matching historical baselines. These are cumulative public counters, not revenue, unique users, retention or spend.
- Trending rank changes require both endpoints to have a Trending rank. Missing rank is not interpreted as last place or rank zero. Rank history charts preserve separate lists.
- Entries older than two hours are marked stale and excluded from breakout rankings. Market totals sum fresh tracked observations; they are not synchronized whole-platform CCU or total Roblox market share.
- Declining requires at least a 10% CCU loss and lost player share in a matched cohort for the selected 24h/3d/7d horizon. Comparing only games with both observations avoids discovery-set growth masquerading as share loss.
- A threshold event is the first observed upward crossing of 1k/5k/10k/50k CCU after a lower observation. Initial games already above a threshold are labeled as baseline observations, not new entrants. The true crossing time lies between observations. Games may have crossed before tracking began; no lifetime-first claims are made.
- Title history is preserved in `snapshots.game_name_at_time`, including update/event/bonus prefixes.

## Initial Breakout Score (0–100)

Tune `config/scoring.json`. At least six hours of elapsed history and a valid 6h baseline are required. Stale observations have no score. Missing longer-horizon inputs contribute no points and the denominator is not renormalized: young histories cannot appear maximally confident.

Each component is clipped to [0,1], weighted, then divided by total weights and multiplied by 100:

| Component | Weight | Normalization |
|---|---:|---|
| Current CCU | 4 | log(1+CCU) / log(1+100,000), capped |
| 6h percent growth | 16 | positive growth / 200% |
| 24h percent growth | 22 | positive growth / 200% |
| 72h percent growth | 14 | positive growth / 200% |
| Acceleration | 18 | positive (6h % / 6 − 24h % / 24) / 10 |
| Trending rank improvement | 8 | positive 24h position gain / 25 |
| Discovery persistence | 4 | distinct observed appearance cycles in 24h / 24 |
| Game age | 4 | max(0, 1 − age in days / 90) |
| Sustained increases | 10 | positive hourly steps during 6h / 6; gaps must be 30–90 minutes |

A game whose 1h CCU drops more than 20% and current CCU is below 70% of its highest observed CCU in the last 24h loses 35 points. For this penalty only, a shorter observed history is usable; incomplete-window 24h averages/peaks shown in the dashboard remain unavailable. Final score is clipped to [0,100]. This penalizes observed spike collapses; hourly sampling cannot detect all within-hour spikes. Huge flat games receive very little score from scale alone. The score is an uncalibrated research heuristic, not a probability or forecast. No score history is stored yet.

## Dashboard and reports

The seven tabs are Breakouts, Top Playing, New Entrants, Sustained Winners, Declining, Game Explorer and Market Overview. Tables are sortable. For growth columns containing explicit "insufficient history" text, use the sidebar's **Numeric ranking sort** to sort the underlying numbers correctly (header sorting on those mixed text columns is lexical). Filter by CCU, minimum/maximum game age, name, creator, discovery source, minimum growth/horizon and minimum score. Select a breakout row and inspect it in Game Explorer, or use the explorer selector directly. Charts show CCU, separate-list rank histories, visits and favorites. The dashboard reports stale/partial collections and supports refreshing its 60-second cache.

Example question: set Minimum CCU = 5000, Created within = 30, Require minimum growth = enabled, horizon = 24h, minimum growth = 0 (use >0 for strictly growing). Early runs correctly have no qualified historical signals.

Daily/3day/weekly Markdown files are generated into `reports/`. Reports include breakouts, observed entrants, cooling games, threshold counts and first-seen Trending signals, with explicit insufficient-history messages. Initial Trending appearances may reflect sampling coverage, not a new platform entry. No genre trends are inferred without classification.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/check_dashboard.py
.\.venv\Scripts\python.exe scripts/inspect_data.py
.\.venv\Scripts\python.exe scripts/probe_endpoints.py
```

Tests use isolated temporary databases and clearly artificial fixtures; they never write fabricated history into `data/market.sqlite`. Coverage includes growth, clock-time matching/tolerance, sparse history, scoring/weight changes/spike collapses, observed crossings, duplicate prevention, title changes, continued tracking, archival, missing metrics, 403/malformed responses, Retry-After, partial batch/page failures and first-run reports. Streamlit AppTest exercises the real-data application, tabs, filters and explorer.

## Known limits / next iteration

Discovery is unstable, sampled and may use server-selected location/device context. Rankings can change between calls. There are no guarantees of exhaustive coverage or a permanently available discovery API. Public endpoints may be rate-limited or changed by Roblox. Collection is local and requires a running machine/process. No historical growth exists until time elapses. Hourly sampling misses short-lived peaks. Averages and player share are observational estimates. Full history is currently loaded into memory for analytics; this is appropriate for hundreds of games during an MVP, but should become bounded SQL queries/rollups as history grows. No migrations framework is needed for this fresh schema; back up the DB before future schema changes.

The schema supports later imported snapshots with explicit timestamps and a separate source/cycle key; a future importer must validate universe IDs, provenance, timestamps and conflicts, never silently blend source methodologies. Classification fields remain nullable for a later, explicitly enabled classifier. No saving of user credentials, paid APIs or LLM calls exists.

Recommended next iteration: collect for 7–14 days, inspect coverage/data gaps, then tune and validate scores against actual sustained breakouts. Add a source-aware import path and reliable unattended Windows deployment before expanding into genre/mechanic classification.
