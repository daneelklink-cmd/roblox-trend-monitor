# Early discovery and launch-cohort research

Discovery combines the existing public Roblox Explore lists with public omni-search
keyword results. `config/discovery.json` controls queries, rotation, pagination and
admission budgets. Each hourly attempt records candidates, metadata coverage,
source errors and selection reasons. Existing tracked games are refreshed before
new candidate metadata. Admission favors creation ages <=7, <=30 and <=90 days,
plus games below 1,000 CCU; all previously tracked games remain tracked.

These sources do not provide an exhaustive chronological launch feed. Search is
relevance-ranked, keywords introduce selection bias, sponsored results are skipped,
and pagination is bounded. Counts and rates describe this observed sample, never
all Roblox launches. HTTP 429 retries honor Retry-After; exhausted endpoints are
deferred for the rest of that attempt. Partial runs remain visibly partial.

Dates are separate: Roblox creation date, first scouted discovery (new records
only), first tracked observation, and manually verified public launch with evidence.
No old discovery dates or historical CCUs are invented. Missing observations are
stored separately; real zero CCU is a valid snapshot. Unique game/cycle constraints
and game/time indexes remain in place. Migration adds nullable columns/tables.

Cohorts include overlapping creation-age windows and first-observed UTC weeks.
Milestones are 100/500/1,000/5,000/10,000 CCU. Baseline-already-above games are
separate from observed crossings. Crossing times are bounds between observations;
gaps over 1.5h are flagged. Equal-follow-up rates exclude baselines and require
completed follow-up plus >=75% occupied hourly bins. Insufficient follow-up is
unknown, not failure. Current cohort statistics exclude stale current readings.

Analytics cover 1h/6h/24h/72h/7d/30d where actual baselines exist. Weekly comparisons
provide comparable weekday/hour baselines. Visit velocity uses actual elapsed time;
counter decreases do not become negative traffic. Breakout scores penalize tiny
baselines and sparse coverage. Sustained 24h growth requires adequate hourly
coverage, no gap >1.5h, positive 24h growth and >=60% positive steps. Drawdown is
relative to the peak observed by this monitor, not an unobserved lifetime peak.

Official genre labels retain their source; they do not verify gameplay. Manual
fields include core loop, theme, trend family, social, progression and monetization.
Each field retains evidence/source/confidence; confidence is an annotator label,
not calibrated probability. CSV import/export preserves per-field provenance and
imports are transactional. Edit through authenticated server shell, not public UI:

```bash
python -m app.manage watch add UNIVERSE_ID --note 'Research candidate'
python -m app.manage watch list
python -m app.manage watch remove UNIVERSE_ID
python -m app.manage export-classifications classifications.csv
python -m app.manage import-classifications classifications.csv
python -m app.manage classify UNIVERSE_ID --core-loop 'Plant / harvest / sell' --source manual_hypothesis --confidence 0.5
python -m app.manage verify-launch UNIVERSE_ID 2026-10-19 --evidence-url https://example.com/announcement
```

Market Opportunities compares matched games, displays sample sizes and history
coverage, HHI/top-five concentration, smaller competitors, new observed members
and recently created game traction. Potential saturation is only a screening proxy:
>=3 matched games, >=60% coverage, nonpositive matched aggregate growth, >=3 new
observed members, >=3 young games and young median CCU <500. Increased discovery
alone cannot prove increased launch supply. Unverified classification remains labeled.

Scheduler-generated daily, 3-day and weekly Markdown reports include smaller/newer
emerging games, recent-creation growth, category/concentration comparisons, new
competitors and three explicitly labeled manual research hypotheses. Unsupported
rankings remain empty with missing-evidence explanations. No revenue is inferred.

Important files: collectors/discovery.py, services/collection.py,
database/migrations.py, analytics/cohorts.py, analytics/opportunities.py,
services/classification.py, manage.py, dashboard/research.py and reports/generate.py
(all under app/). No backup or additional infrastructure work is included.
