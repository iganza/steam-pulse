# SteamPulse Metric Cleanup — Drop Redundancy, Use Steam's Sentiment, Add Confidence

## Key Decision

**Drop all redundant SteamPulse-computed sentiment fields entirely.** The current `sentiment_score` is just `positive_count / total` from Haiku batch_stats — mathematically equivalent to Steam's `positive_pct` since both use the same binary thumb votes. We do extra LLM work (Pass 1 batch_stats) to recompute a number Steam already provides, with worse accuracy (sampled vs. full population).

The LLM's real value is in **narrative sections** (one_liner, audience_profile, design_strengths, gameplay_friction, churn_triggers, dev_priorities, technical_issues, player_wishlist, notable_quotes). The AI doesn't need a competing sentiment number to prove its worth.

**New rule:** Steam's `positive_pct` is the only sentiment number shown to users. AI lives in narrative sections, badged as AI. No dual displays, no fallback confusion. There's just one number, and it's Steam's.

This document covers the comprehensive cleanup, not just sentiment. The audit found redundancy and ambiguity across many metrics; this prompt addresses all of them in one pass.

## Audit Results

| Metric | Source | Verdict | Action |
|--------|--------|---------|--------|
| `sentiment_score` | AI (Python, redundant) | REDUNDANT | **DROP** entirely |
| `overall_sentiment` text | AI label from sentiment_score | REDUNDANT | **DROP** — use Steam's `review_score_desc` |
| `sentiment_label()` function | Helper | REDUNDANT | **DROP** with sentiment_score |
| `positive_pct` | Steam | KEEP | Brand as Steam, sole sentiment number |
| `review_score_desc` | Steam | KEEP | Brand as Steam, replaces overall_sentiment |
| `hidden_gem_score` | Python (depends on sentiment_score) | REWORK | Use `positive_pct` directly, document thresholds |
| `compute_sentiment_trend()` | Python from Steam votes | KEEP | Add `reliable` flag and `sample_size` |
| `find_review_velocity()` | Python | KEEP | Add 3-month centered rolling average (the data is bucketed monthly — a 7-day window doesn't apply), ignore months <5 in `avg_monthly` |
| `find_playtime_sentiment()` churn_point | Python | KEEP | Only flag if both buckets ≥20 reviews |
| `find_early_access_impact()` | Python | KEEP | Add audience-shift disclaimer + sample sizes |
| `find_audience_overlap()` | Python | KEEP | Document the 10k reviewer cap |
| `find_benchmarks()` | Python | KEEP | Document cohort definition in response |
| `audience_profile` | LLM | KEEP | Add AI badge |
| `refund_risk` | LLM | RELABEL | Rename to `refund_signals`, add disclaimer |
| `community_health` | LLM | KEEP | Add "from reviews" tooltip; don't use for sorting |
| `monetization_sentiment` | LLM | KEEP + PAIR | Show alongside actual Steam DLC/price |
| `content_depth` | LLM | KEEP | Add `confidence` and `sample_size` to model |
| `design_strengths`, `gameplay_friction`, `player_wishlist`, `churn_triggers`, `dev_priorities`, `technical_issues`, `competitive_context`, `genre_context`, `notable_quotes`, `one_liner` | LLM | KEEP | High value, just needs AI badge |
| `avg_sentiment` (matview field) | Steam (`AVG(positive_pct)`) | RENAME | → `avg_steam_pct` |
| `metacritic_score`, `deck_compatibility` | Steam | KEEP | Already labeled clearly |

## Best Practices Applied

From Rotten Tomatoes, Steam, OpenCritic, HowLongToBeat, Bloomberg, Spotify, and post-2024 AI labeling norms:

1. **Provenance per metric** — every visible number has a source chip (👍 Steam vs ✨ SteamPulse)
2. **Two-zone layout** — Steam facts in one zone, SP analysis in another, never interleaved
3. **Side-by-side, never replace** — but for sentiment specifically, there's only one source: Steam
4. **Sample size + freshness always visible** — N reviews, last_analyzed timestamp on AI sections
5. **AI badge per AI section** — emerging post-2024 norm
6. **Distinguish Python-computed from LLM-synthesized** — trust signal, surface in methodology
7. **Color reserved for sentiment, not source** — chips/borders for source, color for value
8. **No anthropomorphic framing** — "Analysis indicates" not "We think"
9. **Confidence on fragile metrics** — trend, churn wall, EA impact need sample size flags

## Implementation Phases

### Phase 1: Backend deletions

#### 1a. Drop sentiment_score everywhere

**Files to modify:**

`src/library-layer/library_layer/utils/scores.py`:
- Delete `compute_sentiment_score()`
- Delete `sentiment_label()`
- Keep `compute_sentiment_trend()` (for the trend feature)
- Keep `compute_hidden_gem_score()` but rework signature (see Phase 1b)

`src/library-layer/library_layer/models/analyzer_models.py`:
- Remove `sentiment_score: float` from `GameReport`
- Remove `overall_sentiment: str` from `GameReport`
- Update model docstring

`src/library-layer/library_layer/analyzer.py`:
- Remove all references to `compute_sentiment_score` and `sentiment_label`
- Stop populating `sentiment_score` and `overall_sentiment` in the report dict

`src/lambda-functions/lambda_functions/batch_analysis/prepare_pass2.py`:
- Mirrors analyzer.py for the batch-inference path. Imports `compute_sentiment_score`, `compute_hidden_gem_score`, `compute_sentiment_trend`, `sentiment_label` (lines 27–30) and calls them at lines 124, 129, 133, 154.
- Drop the imports of `compute_sentiment_score` and `sentiment_label`.
- Stop populating `sentiment_score`/`overall_sentiment` in the prepared payload.
- Update the `compute_hidden_gem_score` call to the new `(positive_pct, review_count)` signature.
- Update the `compute_sentiment_trend` call to consume the new dict return shape.

`src/library-layer/library_layer/models/game.py`:
- Remove `sentiment_score: float | None` from `Game` model

`src/library-layer/library_layer/repositories/game_repo.py`:
- Find all SQL queries that reference `sentiment_score` — update sort options to use `positive_pct` instead
- Update `_list_from_matview()` if it sorts by sentiment_score

`src/lambda-functions/lambda_functions/api/handler.py`:
- Find any endpoint that returns `sentiment_score` or `overall_sentiment` and remove them
- The `/api/games` endpoint sorting param `sort=sentiment_score` should map to `positive_pct`

#### 1b. Rework hidden_gem_score

**File:** `src/library-layer/library_layer/utils/scores.py`

```python
def compute_hidden_gem_score(positive_pct: int | None, review_count: int | None) -> float:
    """Hidden gem score: high quality + low discoverability.

    Returns 0.0–1.0 where 1.0 = strong hidden gem candidate.

    Formula:
        scarcity = 1 - (review_count / 10000)   # 0 at 10k+, 1 at 0
        quality  = (positive_pct - 80) / 20     # 0 at 80%, 1 at 100%
        score    = scarcity * quality

    Thresholds:
        - Review cap: 10,000 (games above this are "well-known", not hidden)
        - Quality baseline: 80% positive (lower quality games aren't gems)

    Both inputs are Steam-sourced — no dependency on AI analysis.
    """
    if positive_pct is None or review_count is None:
        return 0.0
    if review_count >= 10_000:
        return 0.0
    if positive_pct < 80:
        return 0.0
    scarcity = 1.0 - (review_count / 10_000)
    quality = (positive_pct - 80) / 20
    return round(scarcity * quality, 2)
```

The signature changes from `(total_reviews, sentiment_score)` to `(positive_pct, review_count)`. Update all callers accordingly. Now hidden_gem_score is purely Steam-derived — no LLM dependency, can be computed for every game without analysis.

**Where it's called:**
- `library_layer/analyzer.py` — passes `sentiment_score`, change to `positive_pct`
- Anywhere else that calls it

#### 1c. Add confidence to fragile derived metrics

**File:** `src/library-layer/library_layer/utils/scores.py`

`compute_sentiment_trend()` — return a dict instead of a tuple so it's easier to extend:
```python
{
    "trend": "improving" | "stable" | "declining",
    "note": str,
    "sample_size": int,        # total reviews in both windows
    "reliable": bool,          # True when each window has >= 50 reviews
}
```

**File:** `src/library-layer/library_layer/repositories/review_repo.py`

`find_playtime_sentiment()` — only set `churn_point` if both the previous and current bucket each have ≥20 reviews. Otherwise `churn_point` is `None`.

`find_review_velocity()` — add a `smoothed` field with a 3-month centered rolling average alongside the raw monthly series (the underlying series is bucketed monthly, so the originally-suggested "7-day" window doesn't apply). In `summary`, exclude months with <5 reviews from `avg_monthly`.

`find_early_access_impact()` — add `ea_reviews` and `post_reviews` count fields. Add a `reliable: bool` flag (True when both are >= 50).

#### 1d. Rename `refund_risk` to `refund_signals`

**File:** `src/library-layer/library_layer/models/analyzer_models.py`

Rename `refund_risk` field to `refund_signals` in the GameReport model. Update analyzer.py and frontend types accordingly. The field's Pydantic structure stays the same.

#### 1e. Add `confidence` and `sample_size` to content_depth

**File:** `src/library-layer/library_layer/models/analyzer_models.py`

Add to `content_depth` model:
```python
confidence: Literal["low", "medium", "high"] = "medium"
sample_size: int = 0
```

Populate in analyzer.py based on number of reviews mentioning playtime.

### Phase 2: Database migrations

#### 2a. `0021_drop_sentiment_score.sql`

**Important:** `mv_genre_games` and `mv_tag_games` (created in `0020_price_summary_matview.sql`, lines 14 and 32) reference `g.sentiment_score` directly. Postgres will refuse `DROP COLUMN` while a matview depends on it, so this migration must drop those matviews first, then drop the column, then recreate them using `g.positive_pct`.

```sql
-- depends: 0020_price_summary_matview

-- 1. Drop matviews that reference games.sentiment_score
DROP MATERIALIZED VIEW IF EXISTS mv_genre_games;
DROP MATERIALIZED VIEW IF EXISTS mv_tag_games;

-- 2. Drop denormalized sentiment_score column + its index
DROP INDEX IF EXISTS idx_games_sentiment_score;
ALTER TABLE games DROP COLUMN IF EXISTS sentiment_score;

-- 3. Recreate mv_genre_games and mv_tag_games using g.positive_pct
--    (copy bodies from 0020, replace g.sentiment_score with g.positive_pct,
--     and recreate any associated UNIQUE indexes used for CONCURRENT refresh)
```

#### 2b. `0022_rename_avg_sentiment_in_matviews.sql`

Recreate the matviews that have `avg_sentiment` columns, renamed to `avg_steam_pct`. Affects:
- `mv_genre_games`, `mv_tag_games` (if they have it)
- `mv_price_positioning`
- `mv_release_timing`
- `mv_platform_distribution`
- `mv_tag_trend`

```sql
-- depends: 0021_drop_sentiment_score
-- transactional: false

DROP MATERIALIZED VIEW IF EXISTS mv_price_positioning;
CREATE MATERIALIZED VIEW mv_price_positioning AS
SELECT
    gn.slug AS genre_slug,
    gn.name AS genre_name,
    -- ... same as before but rename avg_sentiment → avg_steam_pct
    ROUND(AVG(g.positive_pct), 1) AS avg_steam_pct,
    -- ...
FROM games g
JOIN game_genres gg ON gg.appid = g.appid
JOIN genres gn ON gg.genre_id = gn.id
WHERE g.review_count >= 10
GROUP BY gn.slug, gn.name, ...;

CREATE UNIQUE INDEX idx_mv_price_positioning_pk ON mv_price_positioning(genre_slug, ...);

-- Repeat for other matviews
```

(Use the existing matview definitions from migrations 0016, 0019 as the base — just rename the column.)

#### 2c. Update `analytics_repo.py`

Change all queries that read `avg_sentiment` from matviews to `avg_steam_pct`. Update return dicts.

### Phase 3: Frontend deletions

#### 3a. Drop sentiment_score from types

**File:** `frontend/lib/types.ts`

- Remove `sentiment_score?: number` from `Game` interface
- Remove `sentiment_score: number` and `overall_sentiment: string` from `GameReport` interface
- Remove `avg_sentiment` from analytics types, replace with `avg_steam_pct`

#### 3b. Fix the fallback bugs

**Files with `game.sentiment_score ?? game.positive_pct` pattern:**
- `frontend/components/game/GameCard.tsx` (~line 13)
- `frontend/app/developer/[slug]/page.tsx` (lines 55, 104)
- `frontend/app/search/SearchClient.tsx` (line 480, plus `SORT_OPTIONS` at line 21)

In each, replace with just `game.positive_pct`. Use the new `<SteamSourceChip />` component for labeling.

For the `SORT_OPTIONS` entry in `SearchClient.tsx:21`, keep `value: "sentiment_score"` as the wire value (preserves any in-the-wild bookmarks/links). Map it server-side in the API handler to `positive_pct` (see Phase 6). Relabel the user-facing label to `"Best on Steam"`.

#### 3c. Fix `SearchAutocomplete.tsx`

Path: `frontend/components/layout/SearchAutocomplete.tsx` (NOT `components/game/`).

Lines 254-255 currently call `sentimentLabel(game.sentiment_score)` which crashes for unanalyzed games. Replace with:

```typescript
const score = game.positive_pct;  // always Steam
const label = score != null ? `${score}% positive on Steam` : "—";
const color = score != null && score >= 75
  ? "#22c55e"
  : score != null && score >= 50
    ? "#f59e0b"
    : "#ef4444";
```

Show 👍 Steam chip alongside.

#### 3d. Update `ScoreBar.tsx`

Currently labeled "Sentiment Score". Relabel to "Steam Sentiment" with 👍 icon, since there's no SP score anymore.

Alternatively: rename the component to `SteamSentimentBar.tsx`.

#### 3e. Update `GameReportClient.tsx`

Path: `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` (lives under `app/`, not `components/`).

The game detail page. Currently uses `report.sentiment_score` and `report.overall_sentiment`. Both are gone.

Replace with:
- Steam Facts zone showing `game.review_score_desc` (Steam's text label) + `game.positive_pct` + review count + 👍 chip + Steam crawl timestamp
- SteamPulse Analysis zone with all the narrative sections, AI badge, sample size badge (`total_reviews_analyzed`), `last_analyzed` timestamp
- `<HiddenGemBadge />` stays — gets a SP attribution chip and tooltip explaining the formula

#### 3f. Update `DeveloperPortfolio.tsx`

Path: `frontend/components/analytics/DeveloperPortfolio.tsx` (NOT `components/game/`).

Lines 126–127 display `{summary.avg_sentiment}%` — rename to `avg_steam_pct` (matches the matview column rename in Phase 2). Add 👍 Steam chip to the displays. Trajectory chart legend gets the chip too.

#### 3g. Update `AnalyticsClient.tsx`

Lines 231 and 269 reference `avg_sentiment`. Update to `avg_steam_pct` and relabel chart axes "Avg Steam %" with 👍 chip in legend.

#### 3h. Update other analytics components that reference `avg_sentiment`

These all consume the renamed matview columns and must be updated in the same pass:
- `frontend/components/analytics/PricePositioning.tsx:78` — `dataKey="avg_sentiment"` → `"avg_steam_pct"`
- `frontend/components/analytics/PlatformGaps.tsx:23,96` — `{stats.avg_sentiment}%` → `{stats.avg_steam_pct}%`
- `frontend/components/analytics/ReleaseTiming.tsx:74,93` — `dataKey="avg_sentiment"` → `"avg_steam_pct"`
- `frontend/components/analytics/TagTrendChart.tsx:76` — `dataKey="avg_sentiment"` → `"avg_steam_pct"`

Relabel any chart legends/axes from "Avg Sentiment" → "Avg Steam %" with the 👍 chip.

### Phase 4: New components and methodology page

**New files in `frontend/components/ui/`:**

- `SteamSourceChip.tsx` — small chip with 👍 icon + "Steam" label
- `SteamPulseMark.tsx` — small chip with ✨ icon + "SP" label, variants `computed` and `ai`
- `SourceTimestamp.tsx` — relative time ("Crawled 2h ago" / "Analyzed 3d ago")
- `SampleSize.tsx` — "Based on N reviews" badge
- `MethodologyLink.tsx` — "How is this computed?" link → opens drawer/modal

**New file:** `frontend/app/methodology/page.tsx`

Documents:
- Two-pass LLM pipeline (Haiku → Sonnet)
- Which fields are Python-computed vs LLM-generated vs Steam-sourced
- Hidden gem score formula and thresholds
- Sentiment trend computation
- Confidence flags meaning

### Phase 5: Freshness display

Show users when each piece of data was last updated. Same trust theme as source labeling: provenance + freshness + sample size.

**Timestamps to surface (user-facing):**

| Data | Source field | Where to show |
|------|--------------|---------------|
| Game metadata (name, price, developer, etc.) | `app_catalog.meta_crawled_at` | Steam Facts zone header |
| Review data (count, positive_pct) | `app_catalog.review_crawled_at` (most recent batch) or `app_catalog.reviews_completed_at` | Steam Facts zone header (review section) |
| Player tags | `app_catalog.tags_crawled_at` | Tag list header / tooltip |
| AI analysis | `reports.last_analyzed` | SteamPulse Analysis zone header |

**Internal-only (NOT shown to users):**
- `matview_refresh_log.refreshed_at` — purely backend optimization, no user-facing freshness needed

#### 5a. API response updates

**File:** `src/lambda-functions/lambda_functions/api/handler.py`

- `/api/games/{appid}/report` response must include in the `game` block:
  - `meta_crawled_at` (from `app_catalog`)
  - `review_crawled_at` or `reviews_completed_at` (whichever is most recent)
  - `tags_crawled_at`
  - `last_analyzed` (already present from `reports.last_analyzed`)
  - `positive_pct`, `review_score_desc` (already covered above)
- `/api/games` listing endpoint already returns `crawled_at` and `last_analyzed` — verify this is true and add `meta_crawled_at` if missing

**File:** `src/library-layer/library_layer/repositories/game_repo.py`

Update `find_by_appid()` and any join queries that feed `/api/games/{appid}/report` to LEFT JOIN `app_catalog` and select the timestamps.

#### 5b. Frontend freshness component

**New file:** `frontend/components/ui/Freshness.tsx`

```typescript
interface FreshnessProps {
  timestamp: string | Date | null;
  prefix?: string;  // e.g. "Crawled" / "Analyzed" / "Updated"
  staleAfter?: number;  // seconds; show in red if older
}
```

Renders relative time ("Crawled 2h ago") with optional staleness indicator. Color-coded:
- < 24h → muted gray
- 1-7 days → muted
- > 7 days → amber
- > 30 days → red

This is a simpler version than the TUI's `FreshnessLabel` widget — same idea, web-friendly.

#### 5c. Display locations

**Game card (`GameCard.tsx`)** — keep cards minimal, no timestamps. Freshness lives on the detail page.

**Game detail page (`GameReportClient.tsx`)** — two zones each get a freshness line in the header:

```
┌─ Steam Facts ────────────────────┐
│  👍 Steam · Crawled 2h ago       │
│  ...                             │
└──────────────────────────────────┘

┌─ SteamPulse Analysis ────────────┐
│  ✨ SP · Analyzed 3d ago · 1,247 │
│       reviews                     │
│  ...                             │
└──────────────────────────────────┘
```

If `last_analyzed` is older than 30 days AND `review_crawled_at` is recent, show a small banner: "Analysis is from 35 days ago — game has new reviews since then."

**Tag list** — small "tags updated 5d ago" line under the tag cloud, or tooltip on hover.

**Search autocomplete** — no freshness (too cluttered).

**Developer portfolio / analytics** — no freshness on aggregate views.

### Phase 6: API verification

**File:** `src/lambda-functions/lambda_functions/api/handler.py`

- `/api/games/{appid}/report` — verify all freshness timestamps are in the response (see Phase 5a)
- `_preview_fields()` (lines 155–156) — currently returns `overall_sentiment` and `sentiment_score` for `/api/preview`. **Remove both.** Replace with `review_score_desc` + `positive_pct` from the Steam-sourced fields. The preview UI needs the same Steam-only treatment as the rest of the app.
- Remove `sentiment_score` and `overall_sentiment` from any other response shapes
- `/api/games` sort param: **decision — keep `sort=sentiment_score` as the wire value and map it server-side to `ORDER BY positive_pct DESC`.** This preserves any in-the-wild bookmarks/links and avoids a frontend/back-end coordination dance. The user-facing label in `SearchClient.tsx` SORT_OPTIONS becomes "Best on Steam" (see Phase 3b).

### Phase 7: Tests

**Backend:**
- `tests/services/test_analyzer.py` — update assertions about sentiment_score
- `tests/repositories/test_game_repo.py` — update sort tests
- `tests/repositories/test_analytics_repo.py` — update for column rename
- Update `library_layer.utils.scores` test file to reflect deletions and the new hidden_gem_score signature
- Add tests for freshness timestamps in `/api/games/{appid}/report` response

**Frontend:**
- `frontend/tests/fixtures/mock-data.ts` — remove sentiment_score from mock data, add varied positive_pct values
- Playwright tests — update assertions for new visual structure (Steam chips, no sentiment_score display)

## What Stays the Same

- LLM analyzer pipeline (Haiku Pass 1 → Sonnet Pass 2) — unchanged
- All narrative AI report sections — unchanged
- Matview computations — unchanged (just column rename)
- Repository → Service → Handler pattern — unchanged
- No new infrastructure
- No prompt strategy changes (analyzer prompts stay)

## Verification

1. `bash scripts/dev/migrate.sh` — applies migrations 0021 and 0022
2. `poetry run pytest -v` — all backend tests pass
3. `cd frontend && npm install && npm run dev`
4. **Game listing pages** (`/genre/action`, `/tag/multiplayer`, `/search?q=...`):
   - Cards show only `👍 Steam X%`, no SP score
   - No fallback confusion (the bug is gone because `sentiment_score` doesn't exist)
5. **Game detail page** (`/games/440/team-fortress-2`):
   - Steam Facts zone with 👍 chip and Steam timestamp
   - SteamPulse Analysis zone with ✨ chip, sample size, last_analyzed
   - Narrative sections: design_strengths, gameplay_friction, dev_priorities, etc.
   - HiddenGemBadge with SP attribution + tooltip showing formula
6. **Search autocomplete**:
   - All games show "X% positive on Steam" (no crashes on unanalyzed games)
7. **Developer portfolio** (`/developer/{slug}`):
   - Steam % clearly chipped
8. **Analytics dashboard** (`/analytics`):
   - Charts show "Avg Steam %" (not "Avg Sentiment")
9. **Methodology page** (`/methodology`):
   - Documents formulas, Python vs LLM split
10. **Sort order** on `/genre/action` should be similar to before (was sentiment_score DESC, now positive_pct DESC — close enough they match for most games)
11. `cd frontend && npm run test:e2e` — Playwright tests pass

## Out of Scope

- **No analyzer prompt changes** — the LLM still produces the same output, we just stop populating sentiment_score
- **No analyzer pipeline changes** — Pass 1 and Pass 2 unchanged
- **No new metrics** — pure cleanup, no new signals
- **No matview computation changes** — only the column name rename
- **No threshold tweaks** — keep 75/50 colors consistent
