# Niche Scout v1 (Standalone, Reads Prod DB)

## Context

Concept Doctor v1 validates *one specific concept*: the operator hands
it a target peer game and the script tells them whether to build
something like it. **Niche Scout v1 operates one rung up.** It scans
the Steam catalog and answers the operator's bigger question: "where
in the catalog is the ground actually fertile?"

This is the more strategically valuable primitive. Most indie failures
are upstream of execution: the wrong niche was picked. A successful
operator iterates `Niche Scout → pick a niche → Concept Doctor on a
representative game → if green, build`. v1 is the scout half of that
loop.

Roadmap entry that prefigures this:
`scripts/prompts/maybe/data-intelligence-roadmap.md:275-291`
("Market Niche Finder", proposes `mv_niche_opportunities` with formula
`avg_positive_pct × log(avg_review_count) / sqrt(game_count)`). v1
keeps that formula as one component of a richer score.

v1 is a standalone Python script the operator runs locally. Reads from
prod (no writes). One batch LLM call for the synthesis verdict. No web
fetches, no DB writes, no library_layer imports.

## Deliverable

One file: `scripts/niche_scout_v1.py`.

CLI:
```
poetry run python scripts/niche_scout_v1.py [--top 20] [--genre <slug>] [--data-only]
```

- `--top` caps the result list (default 20).
- `--genre` optionally constrains the scan to a single genre slug
  (e.g. `--genre rpg`); without it, scan all genres.
- `--data-only` skips the LLM verdict.

Output:
- `reports/niche_scout/<utc_timestamp>.md` (rendered report)
- `reports/niche_scout/<utc_timestamp>_data.json` (raw structured data)

Also prints the report to stdout.

## DB Connection

Reads prod via `STEAMPULSE_PROD_DATABASE_URL` env var (psycopg2
directly, no SQLAlchemy, no library_layer imports). Do NOT
`from sp import ...`. The script uses
`psycopg2.connect(os.environ["STEAMPULSE_PROD_DATABASE_URL"])` with
`set_session(readonly=True)`. Same pattern as `concept_doctor_v1.py`.

## How a successful operator picks a niche

The naive roadmap formula (`avg_positive_pct × log(avg_review_count) /
sqrt(game_count)`) says "high sentiment + small audience = opportunity"
which is also the formula for *dead market that one good developer
randomly seeded*. A real operator weighs eight criteria:

1. **Demand exists**: aggregate review volume in the niche is
   non-trivial over the last 12 months. A 4-game niche with 96%
   positive isn't a market, it's noise.
2. **Demand is growing or steady**: niche releases per year are not
   collapsing year-over-year.
3. **Not saturated**: release count is not exploding (>2x YoY). When
   everyone piles in, marketing CAC spikes.
4. **Quality bar is reachable**: median positive_pct among niche
   games that crossed 500 reviews is in the 75-90 band. Below 75 the
   audience is unforgiving; above 90 a hit becomes a lottery ticket.
5. **Long-tail health**: revenue is not concentrated in 1-2 mega-hits.
   Top 2 games eating >70% of revenue means winner-takes-all; a healthy
   long tail of $200K-$2M earners is what a new indie wants.
6. **Indie-shippable scope**: median winner's review_count and
   estimated_revenue_usd are within reach for a small team.
7. **Whitespace exists**: the niche's `mv_genre_synthesis` row carries
   recurring wishlist themes that no winner has fully delivered.
8. **Not AAA-dominated**: top games are themselves indie or mid-budget,
   not first-party AAA.

The composite score weights these. The naive formula becomes one
component (`demand_score × longtail_score`), not the whole score.

## What the script does

### 1. Enumerate candidate niches

For each `(genre_slug, modifier_tag_slug)` pair where the niche has
≥30 games. A game belongs to the niche if its genre matches AND the
modifier tag is in its top-10 tags (same membership rule as Concept
Doctor's `niche_games` CTE).

Use existing matviews `mv_genre_games` and `mv_tag_games` (migration
0019) for fast pair enumeration. No new matview; computed inline.

If `--genre <slug>` is passed, filter to that genre only.

### 2. Per-niche stats query

One SQL query per niche (or a single batched query keyed on the pair
list). Reads:

- Niche game count.
- Aggregate review count over last 12 months across niche games.
- Releases per year for last 5 years.
- Median positive_pct over niche games with `review_count >= 500`.
- Revenue distribution (p25, p50, p75, p90) over niche winners.
- Top-2 winner revenue share (concentration test).
- Median price_usd, F2P rate.
- Top winner's developer name (for AAA check).

### 3. Whitespace signal from `mv_genre_synthesis`

For each niche's underlying genre, fetch the friction/wishlist
clusters already computed at the genre level
(`library_layer/models/genre_synthesis.py`, migration 0050). Count
clusters with `mention_count >= 3` and no winner-delivered marker
as `unmet_wishlist_themes_count`.

### 4. Composite opportunity score

Each criterion produces a 0-1 normalized signal:

```
demand_score        = clip(aggregate_reviews_last_12mo / 50000, 0, 1)
growth_score        = sigmoid(release_growth_yoy_3yr_avg)
saturation_penalty  = 1 - clip((releases_last_year - releases_3yr_ago_avg)
                              / releases_3yr_ago_avg, 0, 2)
quality_score       = trapezoid(median_positive_pct_500plus,
                                70, 78, 88, 95)         # peak in 78-88
longtail_score      = 1 - top2_revenue_share
indie_scope_score   = 1.0 if median_winner_revenue in [200_000, 5_000_000]
                      else attenuated
whitespace_score    = clip(unmet_wishlist_themes_count / 5, 0, 1)
not_aaa_score       = 1.0 if top_winner_developer not in AAA_LIST else 0.5

opportunity_score   = (
    0.20 * quality_score
  + 0.15 * longtail_score
  + 0.15 * demand_score
  + 0.15 * growth_score
  + 0.10 * saturation_penalty
  + 0.10 * indie_scope_score
  + 0.10 * whitespace_score
  + 0.05 * not_aaa_score
)
```

Weights are constants at the top of the script; operator can tune.

### 5. Hard disqualifiers

A niche is dropped (score forced to 0) if any of:
- Fewer than 30 games in niche.
- All winners are first-party AAA (Valve, Riot, Activision, EA,
  Ubisoft, Take-Two, Microsoft, Sony, Nintendo, Tencent).
- Median price < $2 (F2P-dominated, different game model).
- 0 niche releases in the last 18 months (dead market).

`disqualifier_reasons` list captured for transparency.

### 6. Rank and pick representative target appid

Sort surviving candidates by `opportunity_score` desc, take top N.

For each top niche, pick a **representative target appid** for
Concept Doctor handoff: the most recent (last 24 months) winner
with `positive_pct >= 80` and `review_count` between 500 and 5000.
Falls back to oldest available winner if no recent qualifier.

### 7. Pydantic data structure

```python
class NicheCandidate(BaseModel):
    genre_slug: str
    modifier_tag_slug: str
    label: str
    game_count: int
    aggregate_reviews_last_12mo: int
    median_positive_pct_500plus: float
    revenue_p25: float
    revenue_p50: float
    revenue_p75: float
    revenue_p90: float
    top2_revenue_share: float
    median_price_usd: float
    free_to_play_pct: float
    releases_last_year: int
    releases_3yr_ago_avg: float
    growth_yoy_3yr_avg: float
    unmet_wishlist_themes_count: int
    top_winner_developer: str
    is_aaa_dominated: bool
    suggested_target_appid: int
    suggested_target_name: str

class NicheCandidateScore(BaseModel):
    candidate: NicheCandidate
    demand_score: float
    growth_score: float
    saturation_penalty: float
    quality_score: float
    longtail_score: float
    indie_scope_score: float
    whitespace_score: float
    not_aaa_score: float
    opportunity_score: float
    disqualified: bool
    disqualifier_reasons: list[str]

class NicheScoutData(BaseModel):
    generated_at: str
    genre_filter: str | None
    candidates_scanned: int
    candidates_disqualified: int
    top_niches: list[NicheCandidateScore]
```

### 8. Render markdown report

Sections in order:
- `# Niche Scout (Generated <utc_timestamp> against prod)`
- `## Verdict & Top Recommendations` (LLM verdict block, if not `--data-only`)
- `## Scan Summary` (genre filter, candidates scanned, candidates disqualified)
- `## Top Niches` (ranked table: rank, niche label, opportunity_score,
  game_count, success rate, revenue p50, growth, saturation, suggested
  target appid)
- `## Per-Niche Detail` (collapsible details per niche: full stat
  block + score breakdown + suggested Concept Doctor command)

### 9. LLM verdict (skipped if `--data-only`)

One Anthropic batch request via the batch API per
`feedback_always_batch_api.md`. Model: `claude-opus-4-7`. Lifecycle
copied from `concept_doctor_v1.submit_batch_and_wait`. custom_id:
`niche_scout_v1`.

System prompt structured with XML tags (matching the
`genre_synthesis_v1.py` and updated Concept Doctor convention):

- `<inputs>`: NicheScoutData JSON.
- `<goal>`: Identify the top 3 build-here niches and the top 3
  high-score-but-don't-build niches. Recommend a specific operator
  next-action for each (e.g., "run Concept Doctor on appid X").
- `<rules>`:
  - Cite niches by `genre_slug + modifier_tag_slug`. Quote stats by
    name (`top2_revenue_share = 0.78` not "concentrated").
  - When recommending against a high-scoring niche, the reason MUST
    cite a specific NicheCandidate field, not vibes.
  - Surface cross-niche patterns the operator wouldn't see by reading
    the table (e.g., "every niche with growth_yoy >0.5 also has
    top2_revenue_share >0.6 in this scan").
  - No invented data. No filler.
  - No em-dashes (the long horizontal dash). Use commas, colons, or
    parentheses.
- `<output_rubric>`: `verdict` (1 sentence), `top_3_build` (3 items
  with citation + suggested Concept Doctor command), `top_3_skip`
  (3 items with cited reason), `cross_cutting_observations` (1-2
  paragraphs), `cadence` (1 sentence).
- `<style>`: senior-designer-to-senior-designer voice, blunt, no
  marketing adjectives.

User message: `NicheScoutData.model_dump_json(indent=2)` followed by
"Produce the verdict."

## Implementation notes

- One file. No package structure for v1. Helpers inline.
- `psycopg2` only. No SQLAlchemy. No library_layer imports.
- One-line comments only (per `feedback_terse_comments.md`).
- pydantic.BaseModel for all data structures (per
  `feedback_always_pydantic.md`).
- No field defaults that hide required-ness (per
  `feedback_no_field_defaults.md`).
- No `| None` unless truly necessary (per
  `feedback_avoid_none_types.md`).
- No script tests (per `feedback_no_script_tests.md`).
- No em-dashes in output strings (per `feedback_no_em_dashes.md`).
- No commit/push from the assistant (per
  `feedback_no_commit_push.md`).
- Output paths: create `reports/niche_scout/` if missing.
- On any DB error, print a helpful message and exit non-zero.
- Reuse `open_readonly_conn`, `submit_batch_and_wait` shape, and
  `niche_games` CTE pattern from `concept_doctor_v1.py`. Copy inline,
  do not import.

## Reusable surface map

| Component | Source |
|---|---|
| Read-only DB connection | `scripts/concept_doctor_v1.py:open_readonly_conn` |
| Batch lifecycle | `scripts/concept_doctor_v1.py:submit_batch_and_wait` |
| `niche_games` CTE shape | `scripts/concept_doctor_v1.py:_fetch_niche_stats` |
| Genre/tag matviews | migrations 0019, 0050 |
| Boxleiter revenue | `games.estimated_revenue_usd` (migration 0026) |
| Output dual-file pattern | `scripts/concept_doctor_v1.py:main` |
| LLM-prompt XML tagging convention | `library_layer/prompts/genre_synthesis_v1.py` |

## Verification

1. `poetry run python scripts/niche_scout_v1.py --data-only`. Confirm:
   - Roguelike-deckbuilder appears but is **disqualified or low-score**
     (saturation_penalty near 0, top2_revenue_share >0.7 driven by
     Slay the Spire + Balatro).
   - Auto Battler niches score middle-of-pack with high
     whitespace_score (matches Concept Doctor's findings).
   - At least one tag-stack the operator hadn't considered ranks in
     top 5. The tool must surprise the operator at least sometimes.
2. `--genre strategy`: confirm constrained scan returns only Strategy-
   anchored niches.
3. Pick the #1 ranked niche's `suggested_target_appid` and run
   Concept Doctor on it. Verdicts should align directionally.
4. `--genre simulation`: confirm most simulation niches are flagged
   disqualified or low-score.
5. `--top 5 --data-only`: confirm deterministic output (modulo timestamp).

## Out of scope (v2 / future)

- New matviews. v2 builds `mv_niche_opportunities` per the roadmap.
- Tag-triple niches (genre + 2 modifier tags). Combinatorial
  explosion needs the matview infra first.
- Audience-overlap-driven niche definition via `mv_audience_overlap`.
- A web UI / `/api/analytics/niche-finder` endpoint.
- Cross-niche graph visualizations.
- Auto-handoff to Concept Doctor (chained execution).
