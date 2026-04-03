# Manual Trigger Script: Review Crawl & Analysis

## Goal

Create a CLI script (`scripts/trigger_crawl.py`) that lets an operator
manually select games and publish events to the SteamPulse SNS topics. This
is the primary way to trigger work during pre-revenue — no automated nightly
recrawl. The EventBridge schedules remain disabled.

The script queries the local/staging PostgreSQL database to find games
matching criteria, then publishes events through the same SNS topics and
event models used by the automated pipeline. This ensures the manual path
and the automated path are identical — the script is just a human-driven
producer.

---

## Prerequisites

- `scripts/prompts/event-pipeline-refactor.md` must be implemented first
  (SNS topics, event models, `publish_event()` helper, `SteamPulseConfig`)
- PostgreSQL database with games and reviews tables populated
- AWS credentials configured (for SNS publish)
- `.env` file with `DATABASE_URL` and `GAME_EVENTS_TOPIC_ARN`,
  `CONTENT_EVENTS_TOPIC_ARN`, `SYSTEM_EVENTS_TOPIC_ARN`

---

## CLI Interface

```bash
# Trigger review crawl for a specific game
poetry run python scripts/trigger_crawl.py crawl --appid 440

# Trigger analysis for a specific game (assumes reviews already crawled)
poetry run python scripts/trigger_crawl.py analyze --appid 440

# Find games with reviews but no analysis report, trigger analysis for first N
poetry run python scripts/trigger_crawl.py analyze --needs-report --limit 50

# Find games with stale reports (>N days old), trigger re-analysis
poetry run python scripts/trigger_crawl.py analyze --stale-days 30 --limit 20

# Find eligible games (>= threshold reviews) with no reviews crawled yet
poetry run python scripts/trigger_crawl.py crawl --needs-reviews --limit 100

# Dry run — show what WOULD be published without actually publishing
poetry run python scripts/trigger_crawl.py analyze --needs-report --limit 50 --dry-run

# Override the eligibility threshold for this run
poetry run python scripts/trigger_crawl.py crawl --needs-reviews --threshold 200 --limit 50
```

### Commands

| Command | Publishes | To Topic |
|---|---|---|
| `crawl --appid N` | `GameMetadataReadyEvent` (is_eligible=true) | `game-events` |
| `crawl --needs-reviews` | `GameMetadataReadyEvent` per game | `game-events` |
| `analyze --appid N` | `ReviewsReadyEvent` | `content-events` |
| `analyze --needs-report` | `ReviewsReadyEvent` per game | `content-events` |
| `analyze --stale-days N` | `ReviewsReadyEvent` per game | `content-events` |

---

## Implementation

### File: `scripts/trigger_crawl.py`

Use `argparse` (not click/typer — no new deps). Import directly from the
library layer:

```python
import argparse
import sys
import os
import boto3

# Add library layer to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "library-layer"))

from library_layer.config import SteamPulseConfig
from library_layer.events import GameMetadataReadyEvent, ReviewsReadyEvent
from library_layer.utils.events import publish_event
```

### Database Queries

Connect to the database via `DATABASE_URL` from `.env` (use `psycopg2`
directly, not the repository classes — this is an operator script, not
production code).

**Games needing review crawl** (`--needs-reviews`):
```sql
SELECT g.appid, g.name, g.review_count
FROM games g
LEFT JOIN (
    SELECT appid, COUNT(*) as crawled
    FROM reviews
    GROUP BY appid
) r ON g.appid = r.appid
WHERE g.review_count >= %(threshold)s
  AND (r.crawled IS NULL OR r.crawled = 0)
ORDER BY g.review_count DESC
LIMIT %(limit)s
```

**Games needing analysis** (`--needs-report`):
```sql
SELECT g.appid, g.name, COUNT(r.id) as review_count
FROM games g
JOIN reviews r ON g.appid = r.appid
LEFT JOIN reports rp ON g.appid = rp.appid
WHERE rp.appid IS NULL
GROUP BY g.appid, g.name
HAVING COUNT(r.id) > 0
ORDER BY COUNT(r.id) DESC
LIMIT %(limit)s
```

**Games with stale reports** (`--stale-days N`):
```sql
SELECT g.appid, g.name, rp.created_at, COUNT(r.id) as review_count
FROM games g
JOIN reviews r ON g.appid = r.appid
JOIN reports rp ON g.appid = rp.appid
WHERE rp.created_at < NOW() - INTERVAL '%(days)s days'
GROUP BY g.appid, g.name, rp.created_at
ORDER BY rp.created_at ASC
LIMIT %(limit)s
```

Adjust table/column names to match the actual schema — inspect `storage.py`
and the repository classes for exact names.

### Output

Use Rich for formatted output:

```
🔍 Finding games needing analysis (limit: 50)...

Found 50 games:
  #  AppID    Name                        Reviews
  1  440      Team Fortress 2             2,068
  2  570      Dota 2                      1,847
  3  730      Counter-Strike 2            1,523
  ...

📤 Publishing 50 ReviewsReadyEvent(s) to content-events...
  ✅ 440 — Team Fortress 2 (MessageId: abc123)
  ✅ 570 — Dota 2 (MessageId: def456)
  ...

Done. Published 50 events.
```

In `--dry-run` mode, show the same table but skip the publish step:
```
🔍 [DRY RUN] Would publish 50 ReviewsReadyEvent(s):
  ...
```

### Error Handling

- If `DATABASE_URL` is not set, exit with clear message
- If SNS topic ARN is not set, exit with clear message
- If SNS publish fails for one game, log the error and continue (don't abort
  the whole batch). At the end, report: "Published 48/50, 2 failures"
- Use `try/except` around each `publish_event()` call, NOT around the whole loop

---

## Configuration Loading

Load `.env` file for local use:
```python
from dotenv import load_dotenv
load_dotenv()

config = SteamPulseConfig()
sns_client = boto3.client("sns", region_name="us-east-1")
```

The script uses the SAME `SteamPulseConfig` and `publish_event()` helper as
Lambda. This guarantees the manual path produces identical events to the
automated path.

---

## Tests

Create `tests/scripts/test_trigger_crawl.py`:

1. `test_needs_reviews_query_returns_eligible_games` — mock DB cursor, verify
   SQL selects games with review_count >= threshold and no crawled reviews
2. `test_needs_report_query_returns_games_without_reports` — mock DB, verify
   SQL finds games with reviews but no report
3. `test_stale_days_query_filters_by_age` — mock DB, verify SQL uses interval
4. `test_crawl_command_publishes_metadata_ready` — mock SNS + DB, run crawl
   command, verify `GameMetadataReadyEvent` published with correct appid
5. `test_analyze_command_publishes_reviews_ready` — mock SNS + DB, run analyze
   command, verify `ReviewsReadyEvent` published
6. `test_dry_run_does_not_publish` — run with --dry-run, verify zero SNS calls
7. `test_partial_failure_continues` — mock SNS to fail on 2nd call, verify 1st
   and 3rd still published, report shows "2/3 succeeded, 1 failed"
8. `test_threshold_override` — pass --threshold 200, verify query uses 200
   instead of default 500
9. `test_limit_respected` — pass --limit 5, verify max 5 events published

---

## Constraints

- No new dependencies — use `argparse`, `psycopg2`, `boto3`, `rich` (all
  already in pyproject.toml)
- Import event models and `publish_event()` from the library layer — do NOT
  duplicate event construction logic
- Do NOT add this script to Lambda deployment — it's an operator tool that
  runs locally
- The script MUST use the same event models as the pipeline — if the schema
  changes, the script changes with it
- Keep `--dry-run` as a safety net — it should be the first thing you test
