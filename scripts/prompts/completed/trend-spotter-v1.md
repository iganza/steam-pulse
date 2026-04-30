# Trend Spotter v1 (Standalone, Reads Prod DB)

## Context

Niche Scout v1 answers a snapshot question: "where is the ground fertile
right now?" It ranks (genre, modifier_tag) niches by current demand,
quality, longtail, and indie scope. It does not look at time.

**Trend Spotter v1 adds the time axis.** It scans the Steam catalog for
tags whose recent cohorts are catching fire faster than their older
cohorts, while supply is not yet stampeding in. The operator question
it answers: "what tags are accelerating *now* that no one else has
noticed yet?"

Two tools, two questions, complementary:

- Niche Scout finds *currently-fertile* niches by snapshot density.
- Trend Spotter finds *accelerating* niches by cohort momentum.

The classic operator loop: `Trend Spotter → notice momentum → Niche
Scout on the same genre to confirm fundamentals → Concept Doctor on a
representative target → if green, build`.

Brainstorm entry that prefigures this: `steam-pulse.org` "Phase 1
Discovery and momentum", under Dev/Marketing Toolkit Brainstorm.

v1 is a standalone Python script the operator runs locally. Reads from
prod (no writes). One batch LLM call for the synthesis verdict. No web
fetches, no DB writes, no `library_layer` imports.

## Deliverable

One file: `scripts/trend_spotter_v1.py`.

CLI:
```
poetry run python scripts/trend_spotter_v1.py [--top 20] [--genre <slug>] [--volume-floor 10] [--data-only]
```

- `--top` caps the result list (default 20).
- `--genre` optionally constrains the scan to tags that co-occur with
  one genre slug (e.g. `--genre rpg`); without it, scan all tags.
- `--volume-floor` minimum releases in the recent 4-quarter window for
  a tag to qualify (default 10). Rejects long-tail tags too sparse to
  trend reliably.
- `--data-only` skips the LLM verdict.

Output:
- `reports/trend_spotter/<utc_timestamp>.md` (rendered report)
- `reports/trend_spotter/<utc_timestamp>_data.json` (raw structured data)

Also prints the report to stdout.

## DB Connection

Reads prod via `STEAMPULSE_PROD_DATABASE_URL` env var (psycopg2
directly, no SQLAlchemy, no `library_layer` imports). Do NOT
`from sp import ...` (per `feedback_sp_py_import_side_effects.md`).
Same pattern as `concept_doctor_v1.py`, `niche_scout_v1.py`,
`tag_doctor_v1.py`. Reuse `open_readonly_conn` shape inline.

## Honest framing of what the matviews measure

The three trend matviews (`mv_trend_catalog`, `mv_trend_by_genre`,
`mv_trend_by_tag`, migrations 0024 + 0045) bucket games by their
`release_date`, not by review-arrival date. That means:

- `releases` per period is a **supply** signal (cohorts releasing).
- `velocity_50_plus` per period is the count of games in that release
  cohort whose lifetime review velocity is >= 50 reviews/day. Treat
  `velocity_50_plus / releases` as a **hit-rate** signal: of games
  shipped in this period with this tag, what fraction caught fire?
- `avg_reviews` per period is mean lifetime review_count among that
  cohort. Confounded by maturation (older cohorts had longer to
  accumulate). Use only as a tiebreaker, not a primary signal.

Trend Spotter v1 ranks tags by **rising hit-rate while supply is not
yet stampeding**. That is the cleanest "early-window" momentum signal
the existing matviews can produce, and the spec must not promise more.

A v2 will require either a new matview or rolling-reviews aggregation
to capture true demand-side momentum (reviews arriving per period
rather than cohorts releasing per period). Out of scope for v1.

## What the script does

### 1. Define the trend windows

All windows are computed at `granularity = 'quarter'` over the most
recent complete quarters (exclude the in-progress quarter):

- `recent`: last 4 complete quarters (the trailing year)
- `prior`: the 4 quarters before that (year-before-last)
- `baseline`: the 4 quarters before *that* (year before year-before-last)

Window edges are constants at the top of the script, computed from
`CURRENT_DATE` once.

### 2. Pull per-tag aggregates over each window

One SQL query against `mv_trend_by_tag` (with `game_type = 'game'`,
`granularity = 'quarter'`), grouped by `tag_slug` and window bucket.
Per tag per window aggregate:

- `releases` (sum)
- `velocity_50_plus` (sum)
- `velocity_10_50` (sum)
- `positive_count` (sum)
- `mixed_count` (sum)
- `negative_count` (sum)
- `avg_steam_pct` (releases-weighted average over the 4 quarters)
- `median_price` (from the latest quarter in the window; matview's
  median is per-quarter, so take the most recent or compute median of
  per-quarter medians; pick most recent for v1)
- `free_pct` (releases-weighted)

If `--genre <slug>` is passed, restrict to tags carried by at least
one game in that genre (join via `game_genres` + `game_tags`). The tag
itself stays the unit of analysis; the genre filter is a scope cut.

### 3. Derive trend deltas per tag

For each tag with `releases_recent >= volume_floor`:

```
hit_rate_recent     = velocity_50_plus_recent / releases_recent
hit_rate_prior      = velocity_50_plus_prior  / releases_prior     (0 if releases_prior == 0)
hit_rate_lift       = hit_rate_recent - hit_rate_prior            (in fraction, e.g. 0.08 = +8pp)

release_growth_yoy  = (releases_recent  - releases_prior)    / max(releases_prior, 1)
release_growth_2yr  = (releases_recent  - releases_baseline) / max(releases_baseline, 1)

quality_lift        = avg_steam_pct_recent - avg_steam_pct_prior

positive_share_recent = positive_count_recent / max(releases_recent, 1)
positive_share_lift   = positive_share_recent - positive_count_prior / max(releases_prior, 1)
```

### 4. Composite momentum score

Each component normalised to 0-1:

```
hit_lift_score      = clip(hit_rate_lift / 0.10, 0, 1)         # +10pp = full credit
quality_lift_score  = clip(quality_lift / 5.0, -0.5, 1)        # +5 avg_steam_pct = full credit
                                                               # negative penalised but capped
supply_health       = trapezoid(release_growth_yoy,
                                lo=-0.20, peak_lo=0.0,
                                peak_hi=0.50, hi=2.0)          # peaks at flat-to-+50% YoY
                                                               # penalises decay AND stampede
volume_floor_score  = 1.0 if releases_recent >= 30
                      else releases_recent / 30                # gentle ramp
non_f2p_score       = 1.0 if free_pct_recent < 30 else 0.5     # hard cut for F2P-dominated

momentum_score = (
    0.35 * hit_lift_score
  + 0.20 * quality_lift_score_clipped_to_0_1
  + 0.20 * supply_health
  + 0.10 * volume_floor_score
  + 0.15 * non_f2p_score
)
```

Weights are constants at the top of the script; operator can tune.
`trapezoid(x, lo, peak_lo, peak_hi, hi)` returns 0 below `lo` and
above `hi`, ramps linearly to 1 between `lo->peak_lo`, holds at 1
between `peak_lo->peak_hi`, ramps back to 0 between `peak_hi->hi`.

### 5. Hard disqualifiers

A tag is dropped (score forced to 0, captured in `disqualifier_reasons`)
if any of:

- `releases_recent < volume_floor` (default 10).
- `release_growth_yoy > 2.0` (release count more than tripled YoY:
  saturation stampede).
- `hit_rate_recent == 0 AND velocity_10_50_recent == 0` (nothing in
  this tag is breaking out at any tier).
- `free_pct_recent >= 70` (F2P-dominated; different game economics).
- `releases_prior == 0 AND releases_baseline == 0` (insufficient
  history to compute a trend).

### 6. Pick representative target appid for handoff

For each top-momentum tag, pick a representative recent winner for
Concept Doctor handoff: the most recent (within the recent 4-quarter
window) game with that tag where `review_count >= 500` and
`positive_pct >= 80`. Falls back to the highest `review_velocity_lifetime`
in the recent window if no qualifier crosses the 500/80 floor. Returns
appid + name + the suggested Concept Doctor command string.

### 7. Surface cooling tags too

Run the same scan a second pass and select the bottom-N tags by
`momentum_score` (where score > 0, i.e. not disqualified, but in the
bottom decile). These are the "cooling" set: previously fertile tags
where hit rate is decaying. Useful for the operator to know what to
*stop* targeting. Cap at top 5 cooling tags.

### 8. Pydantic data structure

```python
class TagWindowStats(BaseModel):
    releases: int
    velocity_50_plus: int
    velocity_10_50: int
    positive_count: int
    mixed_count: int
    negative_count: int
    avg_steam_pct: float
    median_price: float
    free_pct: float

class TagMomentum(BaseModel):
    tag_slug: str
    tag_name: str
    recent: TagWindowStats
    prior: TagWindowStats
    baseline: TagWindowStats
    hit_rate_recent: float
    hit_rate_prior: float
    hit_rate_lift: float
    release_growth_yoy: float
    release_growth_2yr: float
    quality_lift: float
    positive_share_recent: float
    positive_share_lift: float
    suggested_target_appid: int
    suggested_target_name: str

class TagMomentumScore(BaseModel):
    momentum: TagMomentum
    hit_lift_score: float
    quality_lift_score: float
    supply_health: float
    volume_floor_score: float
    non_f2p_score: float
    momentum_score: float
    disqualified: bool
    disqualifier_reasons: list[str]

class TrendSpotterData(BaseModel):
    generated_at: str
    horizon_quarters_per_window: int
    recent_window_start: str
    recent_window_end: str
    genre_filter: str
    volume_floor: int
    candidates_scanned: int
    candidates_disqualified: int
    top_momentum: list[TagMomentumScore]
    cooling: list[TagMomentumScore]
```

Per `feedback_avoid_none_types.md`: `genre_filter` defaults to empty
string (not None) when the operator omits the flag. No `| None` types.

### 9. Render markdown report

Sections in order:
- `# Trend Spotter (Generated <utc_timestamp> against prod)`
- `## Verdict & Momentum Picks` (LLM verdict block, if not `--data-only`)
- `## Scan Summary` (windows, genre filter, volume floor, scanned,
  disqualified)
- `## Top Trending Tags` (ranked table: rank, tag, momentum_score,
  releases_recent, hit_rate_recent, hit_rate_lift, release_growth_yoy,
  quality_lift, suggested_target_appid)
- `## Cooling Tags` (5 rows: tag, momentum_score, hit_rate_lift,
  release_growth_yoy, brief reason)
- `## Per-Tag Detail` (collapsible per tag in top_momentum: full window
  stat blocks + score breakdown + suggested Concept Doctor command +
  suggested Niche Scout command)

### 10. LLM verdict (skipped if `--data-only`)

One Anthropic batch request via the batch API per
`feedback_always_batch_api.md`. Model: `claude-opus-4-7`. Lifecycle
copied from `concept_doctor_v1.submit_batch_and_wait`. custom_id:
`trend_spotter_v1`.

System prompt structured with XML tags (matching the post-Tag-Doctor-v1
convention: `<inputs>`, `<goal>`, `<grounding_rules>`,
`<output_rubric>` with `<section role="..." length="...">` children,
`<style>`):

- `<inputs>`: TrendSpotterData JSON shape description (windows, per-tag
  stats, scoring components, cooling list).
- `<goal>`: Pick the 3 tags an indie operator should investigate this
  month (the early-window momentum picks) and the top 2 tags to stop
  targeting (the cooling ones). Be willing to recommend zero
  investigations when the data is noisy.
- `<grounding_rules>`:
  - Cite tags by `tag_slug`. Quote stats by name (`hit_rate_lift = +0.07`
    not "rising sharply").
  - Every recommendation must cite at least one TagMomentum field.
    No invented tags. No vibes.
  - Distinguish "supply growing too" (likely already noticed) from
    "supply flat, hit rate rising" (the actual early window).
  - Surface cross-cutting patterns (e.g., "every tag with
    hit_rate_lift > 0.05 also carries `release_growth_yoy < 0.30` in
    this scan").
- `<output_rubric>`:
  - `<section role="verdict" length="1 sentence">`: the single sharpest
    takeaway from the scan.
  - `<section role="top_3_investigate" length="3 items">`: each cites
    a tag, the strongest stat (`hit_rate_lift`, `release_growth_yoy`,
    `quality_lift`), and a suggested next-action (Niche Scout
    command, Concept Doctor command on the suggested target appid).
  - `<section role="top_2_stop" length="2 items">`: each cites a
    cooling tag, the decaying stat, and a one-line reason to abandon.
  - `<section role="cross_cutting_observations" length="1-2 paragraphs">`:
    patterns the operator wouldn't see by reading the table row by row.
  - `<section role="cadence" length="1 sentence">`: re-run Trend
    Spotter quarterly, after the most recent quarter closes.
- `<style>`: senior-designer-to-senior-designer voice, blunt, no
  marketing adjectives, no em-dashes (per
  `feedback_no_em_dashes.md`).

User message: `TrendSpotterData.model_dump_json(indent=2)` followed by
`"Produce the verdict."` (matching Concept Doctor / Niche Scout shape).

## Implementation notes

- One file. No package structure for v1. Helpers inline.
- `psycopg2` only. No SQLAlchemy. No `library_layer` imports.
- One-line comments only (per `feedback_terse_comments.md`).
- pydantic.BaseModel for all data structures (per
  `feedback_always_pydantic.md`).
- No field defaults that hide required-ness (per
  `feedback_no_field_defaults.md`).
- No `| None` (per `feedback_avoid_none_types.md`); use empty
  string / 0 / empty list as appropriate, including for
  `genre_filter` and `disqualifier_reasons`.
- No script tests (per `feedback_no_script_tests.md`).
- No em-dashes in output strings or report copy.
- No commit/push from the assistant (per `feedback_no_commit_push.md`).
- Output paths: create `reports/trend_spotter/` if missing.
- On any DB error, print a helpful message and exit non-zero.
- Reuse `open_readonly_conn`, `submit_batch_and_wait` shape inline
  from `concept_doctor_v1.py`. Copy, do not import.
- The matviews should be fresh as of the operator's last refresh
  cycle. The script does NOT trigger a refresh; if `mv_trend_by_tag`
  is stale the operator handles that out-of-band.

## Reusable surface map

| Component | Source |
|---|---|
| Read-only DB connection | `scripts/concept_doctor_v1.py:open_readonly_conn` |
| Batch lifecycle | `scripts/concept_doctor_v1.py:submit_batch_and_wait` |
| Output dual-file pattern | `scripts/niche_scout_v1.py:main` |
| LLM-prompt XML tagging convention | `scripts/concept_doctor_v1.py:SYSTEM_PROMPT`, `scripts/tag_doctor_v1.py:SYSTEM_PROMPT` |
| Trend matview schema | migrations 0024 + 0045 (`mv_trend_by_tag`, `mv_trend_by_genre`) |
| Tag IDF / co-occurrence reference | `scripts/tag_doctor_v1.py:pick_peers` |

## Verification

1. `poetry run python scripts/trend_spotter_v1.py --data-only`. Confirm:
   - Output prints a top-momentum table with at least 5 entries.
   - At least one tag in the top 5 is a known recent breakout (e.g.,
     check that one of `bullet-heaven`, `extraction-shooter`,
     `roguelite`-adjacent variants, or whatever the operator has been
     watching, surfaces in the top 10 or has a sensible cooling-tag
     position).
   - `roguelike-deckbuilder` appears with `release_growth_yoy` likely
     elevated (saturation territory) and `momentum_score` middle-of-pack
     or disqualified, matching Niche Scout's saturation finding.
   - The cooling list is non-empty and the entries have negative
     `hit_rate_lift`.
2. `--genre rpg --data-only`: confirm the result set is restricted to
   tags carried by RPG genre games and is smaller than the unfiltered
   scan.
3. `--volume-floor 30 --data-only`: confirm fewer disqualified tags
   reach the ranked output, and the lowest `releases_recent` in the
   ranked table is >= 30.
4. Pick the #1 ranked tag's `suggested_target_appid` and run Concept
   Doctor on it. Verdicts should align directionally (Concept Doctor
   should not say NO on a tag Trend Spotter ranked #1 unless market
   vitals contradict the momentum signal, which itself is a useful
   signal).
5. `--top 5 --data-only` twice in a row: confirm deterministic output
   modulo the timestamp.

## Out of scope (v2 / future)

- True demand-side momentum (reviews arriving per period, not cohorts
  releasing per period). Requires new aggregation, likely a new
  matview that joins `reviews.posted_at` against `game_tags`.
- Genre-level momentum (Trend Spotter for genre slugs instead of tag
  slugs). Trivially derivable from `mv_trend_by_genre`; defer until
  the tag-level v1 has demonstrated value.
- Tag-pair momentum (e.g., `roguelike + deckbuilder` as a pair).
  Combinatorial; needs either a derived matview or careful inline
  CTE.
- Automatic chained handoff to Niche Scout / Concept Doctor.
- Rolling 8-quarter regression slope for monotonic-growth detection
  (instead of 4q-vs-4q delta).
- Web UI / `/api/analytics/trend-spotter` endpoint.
- Cron / scheduled execution. Per project pattern, the only scheduled
  tool in the brainstorm family is Competitor Watch; Trend Spotter is
  on-demand.
