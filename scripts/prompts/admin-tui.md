# SteamPulse Admin TUI — Implementation Prompt

Build a Textual-based terminal UI for SteamPulse operations. This is the single admin interface
for monitoring system state, browsing data, and triggering operational tasks. It replaces the
scattered `sp.py` / `seed.py` / `trigger_crawl.py` / `tail.py` scripts with one cohesive tool.

## Tech Stack

- **Textual** (latest) for the TUI framework
- **Rich** for table rendering and markup (bundled with Textual)
- **psycopg2** for direct DB access (reuse `library_layer.utils.db.get_conn()`)
- **boto3** for AWS (SQS, SNS, CloudWatch Logs, Secrets Manager, SSM, Step Functions, Cost Explorer)
- **httpx** (sync) for Steam API calls
- Python 3.12, type hints on everything, Pydantic models where structured data flows

### Dependencies to add

Add to `pyproject.toml` (main group, not infra):
```
textual = "^2.0"
```

Textual bundles Rich — no separate Rich dependency needed.

### Entry point

```
scripts/tui.py
```

Launch with: `poetry run python scripts/tui.py [--env staging|production]`

Default: connects to **local** DB (`DATABASE_URL` from `.env`). With `--env staging`, resolves
DB credentials from Secrets Manager and connects via the SSH tunnel on `localhost:5433`. With
`--env production`, same but tunnel on `localhost:5434`. The tunnel must already be open
(`scripts/dev/db-tunnel.sh`).

AWS operations (SQS, SNS, CloudWatch, Step Functions) always target the selected `--env`.
Local mode has no AWS operations — those panels show "Connect to staging/production for AWS ops".

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  SteamPulse Admin  │  env: staging  │  DB: ●  │  AWS: ●  │  12:34 │   ← Header bar
├────────┬────────────────────────────────────────────────────────────┤
│        │                                                            │
│  NAV   │                    MAIN CONTENT                            │
│        │                                                            │
│ [D]ash │  (switches based on nav selection)                         │
│ [G]ames│                                                            │
│ [R]evs │                                                            │
│ [T]ags │                                                            │
│ [A]nalysis                                                          │
│ [Q]ueues                                                            │
│ [L]ogs │                                                            │
│ [S]QL  │                                                            │
│        │                                                            │
├────────┴────────────────────────────────────────────────────────────┤
│  status bar / last action result                                    │   ← Footer
└─────────────────────────────────────────────────────────────────────┘
```

- Left sidebar: navigation with keyboard shortcuts (single key press)
- Main area: content for the active screen
- Header: environment badge, DB connection status (green/red dot), AWS connectivity, clock
- Footer: last action confirmation or error message

---

## Screens

### 1. Dashboard (`D`)

The landing screen. A live overview of the entire system at a glance.

#### Top row — KPI cards (4 across)

| Card | Query / Source |
|------|----------------|
| **Games** | `SELECT COUNT(*) FROM games` |
| **Reviews** | `SELECT COUNT(*) FROM reviews` |
| **Reports** | `SELECT COUNT(*) FROM reports` |
| **Catalog** | `SELECT COUNT(*) FROM app_catalog` |

Each card shows the count in large text with a label underneath.

#### Middle row — Pipeline Status (horizontal bar or table)

Show the crawl pipeline funnel:

```
Catalog Entries:  142,847
├─ Meta Pending:    1,203   ← app_catalog WHERE meta_status = 'pending'
├─ Meta Done:     138,921   ← meta_status = 'done'
├─ Meta Failed:       412   ← meta_status = 'failed'
├─ Meta Skipped:    2,311   ← meta_status = 'skipped'
├─ Reviews Done:   45,230   ← reviews_completed_at IS NOT NULL
├─ Tags Crawled:   44,100   ← tags_crawled_at IS NOT NULL
└─ Analyzed:       12,450   ← EXISTS report
```

Query:
```sql
SELECT
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE meta_status = 'pending') AS meta_pending,
  COUNT(*) FILTER (WHERE meta_status = 'done') AS meta_done,
  COUNT(*) FILTER (WHERE meta_status = 'failed') AS meta_failed,
  COUNT(*) FILTER (WHERE meta_status = 'skipped') AS meta_skipped,
  COUNT(*) FILTER (WHERE reviews_completed_at IS NOT NULL) AS reviews_done,
  COUNT(*) FILTER (WHERE tags_crawled_at IS NOT NULL) AS tags_crawled
FROM app_catalog;

SELECT COUNT(*) AS reports FROM reports;
```

#### Bottom row — Freshness & Queues (two panels side by side)

**Left panel — Recent Activity:**
```
Last metadata crawl:    2h ago   (MAX(meta_crawled_at) FROM app_catalog)
Last review crawl:      45m ago  (MAX(review_crawled_at) FROM app_catalog)
Last analysis:          3h ago   (MAX(last_analyzed) FROM reports)
Last matview refresh:   1h ago   (MAX(refreshed_at) FROM matview_refresh_log)
```

**Right panel — Queue Depths** (AWS only, requires `--env`):
```
app-crawl-queue:          12
review-crawl-queue:      847
spoke-results-queue:       3
cache-invalidation-queue:  0
──────────────────────────────
metadata-dlq:              0
review-dlq:                2  ⚠
spoke-results-dlq:         0
cache-dlq:                 0
```

Use `sqs.get_queue_attributes(QueueUrl=..., AttributeNames=["ApproximateNumberOfMessages"])`.
Queue URLs resolved from SSM parameters. DLQ counts > 0 show a warning indicator.

#### Auto-refresh

Dashboard refreshes every 30 seconds. Show a countdown timer or spinner. Manual refresh with `r`.

---

### 2. Games Browser (`G`)

A searchable, sortable, filterable data table of all games.

#### Table columns

| Column | Source | Sortable |
|--------|--------|----------|
| AppID | `games.appid` | ✓ |
| Name | `games.name` | ✓ |
| Reviews | `games.review_count` | ✓ |
| Positive % | `games.positive_pct` | ✓ |
| Sentiment | `games.sentiment_score` | ✓ |
| Price | `games.price_usd` | ✓ |
| Released | `games.release_date` | ✓ |
| Crawled | `games.crawled_at` | ✓ |
| Analyzed | `games.last_analyzed` | ✓ |
| Has Report | `EXISTS report` | ✓ |

Default sort: `review_count DESC`. Page size: 50 rows. Paginate with `PgUp`/`PgDn`.

#### Search & filter bar (top of screen)

- **Text search**: fuzzy match on `name` (use `ILIKE '%term%'`)
- **Filter chips** (toggle with keyboard):
  - `f1` No report (games with reviews but no analysis)
  - `f2` Stale report (last_analyzed > 30 days ago)
  - `f3` Never crawled (crawled_at IS NULL)
  - `f4` Has reviews (review_count > 0)
  - `f5` Failed meta (meta_status = 'failed' in app_catalog)

#### Game detail panel

Press `Enter` on a game row to open a detail panel (right side or modal). Shows:

```
═══ Team Fortress 2 (440) ═══

Developer:    Valve
Publisher:    Valve
Released:     2007-10-10
Price:        Free
Platforms:    Win ✓  Mac ✓  Linux ✓
Deck:         Verified

── Crawl Status ──
Metadata:     done (crawled 2024-03-15 14:22 UTC)
Reviews:      45,231 in DB / 892,104 on Steam
Tags:         crawled 2024-03-15 14:25 UTC
Analysis:     2024-03-10 09:00 UTC (5 days ago)

── Scores ──
Sentiment:    0.91 (Very Positive)
Hidden Gem:   0.12
Review Vel.:  142/month

── Report Summary ──
One-liner:    "An eternal class-based shooter..."
Strengths:    3 items
Friction:     5 items
```

Queries:
```sql
-- Game + catalog join
SELECT g.*, ac.meta_status, ac.meta_crawled_at, ac.reviews_completed_at,
       ac.tags_crawled_at, ac.review_crawled_at
FROM games g
LEFT JOIN app_catalog ac ON ac.appid = g.appid
WHERE g.appid = %s;

-- Report summary
SELECT reviews_analyzed, last_analyzed,
       report_json->>'one_liner' AS one_liner,
       jsonb_array_length(report_json->'design_strengths') AS strengths_count,
       jsonb_array_length(report_json->'gameplay_friction') AS friction_count
FROM reports WHERE appid = %s;

-- Review count in DB
SELECT COUNT(*) FROM reviews WHERE appid = %s;
```

#### Game actions (from detail panel)

Keybindings shown at bottom of detail panel:

| Key | Action | Implementation |
|-----|--------|----------------|
| `c` | Crawl metadata | Publish `GameDiscoveredEvent` to game-events SNS topic |
| `r` | Crawl reviews | Send `ReviewCrawlMessage` to review-crawl-queue |
| `t` | Crawl tags | Send tag crawl message to app-crawl-queue |
| `a` | Run analysis | Start Step Functions execution (`sfn.start_execution`) |
| `o` | Open on Steam | Open `https://store.steampowered.com/app/{appid}` in browser |

All mutating actions require a confirmation dialog: "Crawl reviews for TF2 (440)? [y/n]"

For SNS/SQS publishing, reuse the typed event models from `library_layer/events.py`:
```python
from library_layer.events import ReviewCrawlMessage
msg = ReviewCrawlMessage(appid=440, max_reviews=5000)
sqs.send_message(QueueUrl=review_queue_url, MessageBody=msg.model_dump_json())
```

---

### 3. Reviews Browser (`R`)

Browse reviews per game.

#### Top: Game selector

Input field for appid. On submit, loads reviews for that game.

#### Table columns

| Column | Source |
|--------|--------|
| Steam ID | `steam_review_id` |
| Voted Up | `voted_up` (✓/✗) |
| Playtime | `playtime_hours` |
| Posted | `posted_at` |
| Language | `language` |
| Helpful | `votes_helpful` |
| Funny | `votes_funny` |
| EA | `written_during_early_access` (✓/✗) |
| Body (truncated) | first 80 chars of `body` |

Default sort: `votes_helpful DESC`. Page size: 50.

Press `Enter` on a review row to show full body text in a scrollable panel.

#### Summary stats (above table)

```
Total: 45,231 │ Positive: 89% │ Avg Playtime: 847h │ EA Reviews: 12% │ Last Review: 2h ago
```

Query:
```sql
SELECT
  COUNT(*) AS total,
  ROUND(100.0 * COUNT(*) FILTER (WHERE voted_up) / NULLIF(COUNT(*), 0), 1) AS positive_pct,
  ROUND(AVG(playtime_hours), 1) AS avg_playtime,
  ROUND(100.0 * COUNT(*) FILTER (WHERE written_during_early_access) / NULLIF(COUNT(*), 0), 1) AS ea_pct,
  MAX(posted_at) AS last_review
FROM reviews WHERE appid = %s;
```

---

### 4. Tags & Genres (`T`)

Two tabs: **Tags** and **Genres**.

#### Tags tab

Table from `mv_tag_counts` materialized view:

| Column | Source |
|--------|--------|
| Tag | `name` |
| Category | `category` |
| Games | `game_count` |

Grouped by category (collapsible tree or sections). Sort by `game_count DESC` within each category.

Press `Enter` on a tag → show top 20 games for that tag (from `mv_tag_games`).

#### Genres tab

Table from `mv_genre_counts`:

| Column | Source |
|--------|--------|
| Genre | `name` |
| Games | `game_count` |

Press `Enter` on a genre → show top 20 games for that genre (from `mv_genre_games`).

#### Freshness indicator

Show matview last refresh time at the top:
```
Materialized views last refreshed: 2024-03-15 14:00 UTC (1h ago)    [R] Refresh now
```

`R` key triggers matview refresh (sends message to cache-invalidation-queue or invokes
the matview refresh Lambda directly via `lambda.invoke()`).

---

### 5. Analysis (`A`)

Monitor and trigger LLM analysis jobs.

#### Analysis backlog table

Games that have reviews but no report, or stale reports:

```sql
SELECT g.appid, g.name, g.review_count,
       (SELECT COUNT(*) FROM reviews r WHERE r.appid = g.appid) AS reviews_in_db,
       r.last_analyzed,
       CASE
         WHEN r.appid IS NULL THEN 'no report'
         WHEN r.last_analyzed < NOW() - INTERVAL '30 days' THEN 'stale'
         ELSE 'current'
       END AS status
FROM games g
LEFT JOIN reports r ON r.appid = g.appid
WHERE g.review_count >= 50
ORDER BY
  CASE WHEN r.appid IS NULL THEN 0 ELSE 1 END,
  g.review_count DESC
LIMIT 100;
```

| Column | Notes |
|--------|-------|
| AppID | |
| Name | |
| Steam Reviews | `games.review_count` |
| DB Reviews | count from reviews table |
| Last Analyzed | `reports.last_analyzed` or "never" |
| Status | no report / stale / current |

#### Actions

| Key | Action |
|-----|--------|
| `a` | Analyze selected game (start Step Functions execution) |
| `b` | Batch analyze: queue top N unanalyzed games (prompt for N) |
| `Enter` | View report JSON for selected game (scrollable panel) |

#### Report viewer

When pressing `Enter` on an analyzed game, show the report JSON formatted with Rich syntax
highlighting. Sections collapsible:
- One-liner
- Audience Profile
- Design Strengths
- Gameplay Friction
- Churn Triggers
- Dev Priorities
- Technical Issues
- Competitive Context

---

### 6. Queues (`Q`)

Monitor and manage SQS queues. **AWS-only screen** (requires `--env`).

#### Queue overview table

| Queue | Messages | In Flight | DLQ | DLQ Messages |
|-------|----------|-----------|-----|-------------|
| app-crawl-queue | 12 | 3 | metadata-dlq | 0 |
| review-crawl-queue | 847 | 10 | review-dlq | 2 ⚠ |
| spoke-results-queue | 3 | 1 | spoke-results-dlq | 0 |
| cache-invalidation-queue | 0 | 0 | cache-dlq | 0 |
| email-queue | 0 | 0 | email-dlq | 0 |

Attributes: `ApproximateNumberOfMessages`, `ApproximateNumberOfMessagesNotVisible`.

Auto-refresh every 10 seconds.

#### DLQ Inspector

Press `Enter` on a DLQ row to inspect dead letters:

- `sqs.receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=10, VisibilityTimeout=0)`
  (visibility 0 = peek without consuming)
- Show message body (parsed JSON), approximate receive count, sent timestamp
- For each message:
  - `r` — Retry: move message back to source queue (send to source, delete from DLQ)
  - `d` — Delete: permanently remove from DLQ (with confirmation)
  - `Enter` — View full message body

#### Bulk operations (bottom bar)

| Key | Action |
|-----|--------|
| `p` | Purge selected queue (with double confirmation: type queue name) |
| `s` | Send test message to selected queue (opens input for JSON body) |

---

### 7. Logs (`L`)

Live CloudWatch log streaming. **AWS-only screen**.

#### Service selector (top bar)

Toggle buttons for services — multiple can be active:
```
[crawler] [spoke] [ingest] [api] [analysis] [admin]
```

Default: `crawler`, `spoke`, `ingest` active.

#### Time range

Dropdown or input: `5m` | `15m` | `1h` | `6h` | `1d`. Default: `15m`.

#### Log stream (main area)

Scrollable log view with:
- Color-coded service prefix: `[crawler]` blue, `[spoke]` green, `[ingest]` yellow, `[api]` cyan, `[analysis]` magenta
- Timestamp
- Log level highlighted: ERROR red, WARN yellow, INFO default
- Structured fields shown inline

Implementation: Use `logs.filter_log_events()` with the selected log groups.
Log group names follow the pattern: `/steampulse/{env}/{service}`.
For spokes: `/steampulse/{env}/spoke/{region}` — include all spoke regions.

#### Error filter

`e` key toggles error-only mode (filter pattern: `"ERROR"`).

#### Auto-tail

New logs append at bottom. Auto-scroll when at bottom of view.
Manual scroll pauses auto-scroll (like a real terminal). `End` key resumes.

---

### 8. SQL Console (`S`)

Interactive read-only SQL query tool against the connected database.

#### Layout

```
┌──────────────────────────────────────┐
│  SQL Input (multi-line text area)     │
│                                       │
│  SELECT * FROM games LIMIT 10;        │
│                                       │
├──────────────────────────────────────┤
│  Results Table                        │
│  (auto-sized columns, scrollable)     │
│                                       │
│  appid │ name          │ review_count │
│  440   │ Team Fortre.. │ 892,104      │
│  730   │ Counter-Str.. │ 7,421,233    │
│                                       │
├──────────────────────────────────────┤
│  12 rows │ 45ms │ History: ↑↓         │
└──────────────────────────────────────┘
```

#### Features

- **Multi-line input** with `Ctrl+Enter` to execute (or a "Run" button)
- **Read-only enforcement**: reject any query containing INSERT, UPDATE, DELETE, CREATE, ALTER,
  DROP, TRUNCATE (case-insensitive check). Also set `SET statement_timeout = '10s'` on the
  connection and use a read-only transaction (`SET TRANSACTION READ ONLY`).
- **Query history**: up/down arrows cycle through previous queries. Persist to
  `~/.steampulse/query_history.json` (last 50 queries).
- **Result stats**: row count, execution time
- **Export**: `Ctrl+S` saves results as CSV to `~/Downloads/steampulse-query-{timestamp}.csv`
- **Saved queries** (bookmarks): `Ctrl+B` saves current query with a name.
  `Ctrl+L` loads from saved list. Persist to `~/.steampulse/saved_queries.json`.

#### Pre-loaded query templates

Accessible via `Tab` key or dropdown. These are the operational queries an admin runs regularly:

```python
SAVED_QUERIES = {
    "Pipeline funnel": """
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE meta_status = 'pending') AS meta_pending,
          COUNT(*) FILTER (WHERE meta_status = 'done') AS meta_done,
          COUNT(*) FILTER (WHERE meta_status = 'failed') AS meta_failed,
          COUNT(*) FILTER (WHERE meta_status = 'skipped') AS meta_skipped,
          COUNT(*) FILTER (WHERE reviews_completed_at IS NOT NULL) AS reviews_done,
          COUNT(*) FILTER (WHERE tags_crawled_at IS NOT NULL) AS tags_done
        FROM app_catalog
    """,
    "Unanalyzed games (top 50)": """
        SELECT g.appid, g.name, g.review_count,
               ac.reviews_completed_at, g.crawled_at
        FROM games g
        JOIN app_catalog ac ON ac.appid = g.appid
        WHERE ac.reviews_completed_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.appid = g.appid)
        ORDER BY g.review_count DESC
        LIMIT 50
    """,
    "Stale reports (>30d)": """
        SELECT r.appid, g.name, r.last_analyzed, g.review_count,
               NOW() - r.last_analyzed AS age
        FROM reports r
        JOIN games g ON g.appid = r.appid
        WHERE r.last_analyzed < NOW() - INTERVAL '30 days'
        ORDER BY r.last_analyzed ASC
        LIMIT 50
    """,
    "Review crawl stuck": """
        SELECT ac.appid, g.name, ac.review_crawled_at, ac.reviews_completed_at,
               g.review_count
        FROM app_catalog ac
        JOIN games g ON g.appid = ac.appid
        WHERE ac.review_crawled_at IS NOT NULL
          AND ac.reviews_completed_at IS NULL
          AND ac.review_crawled_at < NOW() - INTERVAL '6 hours'
        ORDER BY ac.review_crawled_at ASC
    """,
    "Failed metadata": """
        SELECT ac.appid, ac.name, ac.meta_crawled_at
        FROM app_catalog ac
        WHERE ac.meta_status = 'failed'
        ORDER BY ac.meta_crawled_at DESC
        LIMIT 50
    """,
    "Top games without tags": """
        SELECT g.appid, g.name, g.review_count, ac.tags_crawled_at
        FROM games g
        JOIN app_catalog ac ON ac.appid = g.appid
        WHERE ac.tags_crawled_at IS NULL
          AND g.review_count >= 100
        ORDER BY g.review_count DESC
        LIMIT 50
    """,
    "Recent analyses": """
        SELECT r.appid, g.name, r.reviews_analyzed, r.last_analyzed,
               report_json->>'overall_sentiment' AS sentiment,
               (report_json->>'sentiment_score')::float AS score
        FROM reports r
        JOIN games g ON g.appid = r.appid
        ORDER BY r.last_analyzed DESC
        LIMIT 25
    """,
    "Matview refresh history": """
        SELECT refreshed_at, duration_ms, views_refreshed
        FROM matview_refresh_log
        ORDER BY refreshed_at DESC
        LIMIT 20
    """,
    "Review volume by month": """
        SELECT DATE_TRUNC('month', posted_at) AS month,
               COUNT(*) AS reviews,
               ROUND(100.0 * COUNT(*) FILTER (WHERE voted_up) / COUNT(*), 1) AS positive_pct
        FROM reviews
        WHERE posted_at > NOW() - INTERVAL '12 months'
        GROUP BY 1 ORDER BY 1 DESC
    """,
    "DLQ candidates (games with meta_status failed)": """
        SELECT ac.appid, ac.name, ac.meta_status, ac.meta_crawled_at
        FROM app_catalog ac
        WHERE ac.meta_status = 'failed'
        ORDER BY ac.meta_crawled_at DESC NULLS LAST
        LIMIT 50
    """,
}
```

---

## Keyboard Shortcuts (Global)

| Key | Action |
|-----|--------|
| `d` | Switch to Dashboard |
| `g` | Switch to Games |
| `r` | Switch to Reviews |
| `t` | Switch to Tags |
| `a` | Switch to Analysis |
| `q` | Switch to Queues |
| `l` | Switch to Logs |
| `s` | Switch to SQL |
| `?` | Show help overlay (all shortcuts) |
| `Ctrl+Q` | Quit |
| `Escape` | Close modal/panel, return to list view |

When a text input is focused, single-key navigation is suppressed (only `Escape` and `Ctrl+*`
shortcuts work).

---

## AWS Connectivity

### Queue URL resolution

On startup with `--env`, resolve all queue URLs from SSM:

```python
ssm = boto3.client("ssm", region_name="us-west-2")

QUEUE_PARAMS = {
    "app-crawl-queue": "/steampulse/{env}/messaging/app-crawl-queue-url",
    "review-crawl-queue": "/steampulse/{env}/messaging/review-crawl-queue-url",
    "spoke-results-queue": "/steampulse/{env}/messaging/spoke-results-queue-url",
    "cache-invalidation-queue": "/steampulse/{env}/messaging/cache-invalidation-queue-url",
    "email-queue": "/steampulse/{env}/messaging/email-queue-url",
}

# DLQ URLs derived from the queue URLs by convention or separate SSM params
DLQ_PARAMS = {
    "metadata-dlq": "/steampulse/{env}/messaging/metadata-dlq-url",
    "review-dlq": "/steampulse/{env}/messaging/review-dlq-url",
    # ... etc
}
```

If SSM resolution fails, show the queue name as "unavailable" — don't crash. DLQ URLs that
aren't in SSM can be derived from the queue URL by appending `-dlq` to the queue name
and calling `sqs.get_queue_url()`.

### SNS topic ARN resolution

Same pattern — resolve from SSM:
```python
TOPIC_PARAMS = {
    "game-events": "/steampulse/{env}/messaging/game-events-topic-arn",
    "content-events": "/steampulse/{env}/messaging/content-events-topic-arn",
    "system-events": "/steampulse/{env}/messaging/system-events-topic-arn",
}
```

### Step Functions ARN

```python
sfn_arn = ssm.get_parameter(Name=f"/steampulse/{env}/compute/sfn-arn")["Parameter"]["Value"]
```

---

## DB Connectivity

### Local mode (default)

```python
from library_layer.utils.db import get_conn
conn = get_conn()
```

Uses `DATABASE_URL` from `.env` (loaded with python-dotenv).

### Deployed mode (`--env staging|production`)

Resolve credentials from Secrets Manager (same pattern as Lambda):
```python
import json, boto3

sm = boto3.client("secretsmanager", region_name="us-west-2")
secret = json.loads(
    sm.get_secret_value(SecretId=f"steampulse/{env}/db-credentials")["SecretString"]
)

# Tunnel must be running: scripts/dev/db-tunnel.sh
port = 5433 if env == "staging" else 5434
conn = psycopg2.connect(
    host="127.0.0.1", port=port,
    dbname=secret["dbname"], user=secret["username"], password=secret["password"],
)
```

---

## Code Organization

```
scripts/
  tui.py                    # Entry point (arg parsing, app launch)
  tui/
    __init__.py
    app.py                  # SteamPulseAdmin(App) — main Textual app class
    config.py               # TUI config: env, DB conn, AWS clients
    screens/
      __init__.py
      dashboard.py          # DashboardScreen
      games.py              # GamesBrowserScreen + GameDetailPanel
      reviews.py            # ReviewsBrowserScreen
      tags.py               # TagsGenresScreen
      analysis.py           # AnalysisScreen + ReportViewer
      queues.py             # QueuesScreen + DLQInspector
      logs.py               # LogsScreen
      sql.py                # SQLConsoleScreen
    widgets/
      __init__.py
      kpi_card.py           # Reusable KPI card widget
      pipeline_funnel.py    # Pipeline status widget
      queue_table.py        # Queue depths widget
      confirm_dialog.py     # Confirmation modal
      freshness.py          # "X ago" freshness display
    queries.py              # All SQL constants (saved queries, screen queries)
    aws.py                  # AWS client wrappers (SQS, SNS, CloudWatch, SSM, SFN)
    styles.css              # Textual CSS (layout, colors, sizing)
```

### CSS theming (`styles.css`)

Use a dark theme consistent with terminal aesthetics. Textual supports CSS:

```css
Screen {
    background: $surface;
}

#sidebar {
    width: 16;
    dock: left;
    background: $panel;
    border-right: solid $primary;
}

.kpi-card {
    height: 5;
    border: round $primary;
    content-align: center middle;
}

.warning {
    color: $warning;
}

.error {
    color: $error;
}

DataTable > .datatable--cursor {
    background: $accent;
}
```

---

## Implementation Notes

### Threading / async model

Textual runs on asyncio. DB calls (psycopg2) are synchronous and MUST run in a thread via
`asyncio.to_thread()` or Textual's `run_worker()` to avoid blocking the UI:

```python
async def refresh_dashboard(self) -> None:
    stats = await asyncio.to_thread(self._query_pipeline_stats)
    self.query_one("#pipeline-funnel").update(stats)
```

AWS boto3 calls are also synchronous — same treatment.

### Error handling

- DB connection lost: show red indicator in header, retry on next action
- AWS call fails: show error in footer bar, don't crash
- Query timeout: show "Query timed out (10s limit)" in results area
- Invalid SQL: show psycopg2 error message in results area (no stack trace)

### Data refresh pattern

Each screen implements a `refresh_data()` method. The dashboard auto-refreshes on a timer.
Other screens refresh on entry and on manual `r` key press. Never auto-refresh a screen
the user isn't looking at.

### Reuse library_layer

Import directly from the library layer for models and events:

```python
import sys
sys.path.insert(0, "src/library-layer")

from library_layer.events import ReviewCrawlMessage, GameDiscoveredEvent
from library_layer.models.game import Game
from library_layer.models.catalog import CatalogEntry
```

Do NOT duplicate model definitions. Do NOT duplicate SQL that already exists in repositories.
For read-only queries that are TUI-specific (like the dashboard aggregations), put them in
`scripts/tui/queries.py`.

For write operations that already exist in services (like publishing events), call the
service or use the event models directly with boto3 — don't reimplement the logic.

---

## What NOT to build

- No authentication (runs locally with your AWS creds + DB tunnel)
- No write operations on the database (all mutations go through SQS/SNS → Lambda pipeline)
- No log storage (CloudWatch is the source of truth)
- No real-time websockets (polling is fine for an admin tool)
- No deployment of the TUI itself (it's a local script)
- No tests for the TUI (operational tool, not production code)
