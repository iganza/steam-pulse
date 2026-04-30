# Concept Doctor v1 (Standalone, Reads Prod DB)

## Context

Tag Doctor v1 audits *one existing game's* tag strategy. Concept Doctor v1
operates one rung up: the operator hands it a target peer game (e.g.
"I want to build something similar to *There Are No Orcs*"), and the
script tells them whether the niche is commercially viable and what
features the game must include to have a real shot at crossing the
500-review / 75% positive threshold that separates Winners from
sub-floor releases.

This is the smallest atomic primitive for *concept validation* — the
question every indie operator asks before committing 6–12 months of
dev work. Page Doctor v2 will eventually call this logic when auditing
a live Steam page; building Concept Doctor first means Page Doctor
v2 reuses the cohort-analysis surface instead of duplicating it.

The strategic frame the tool embodies: a successful indie doesn't
clone the genre leader, they ship a 7/10 in a niche where they can
beat the median. That requires knowing the niche's *floor* (Losers'
tag DNA, common pitfalls), the *table stakes* (tags + friction points
Winners all solve), the *differentiation gap* (what players begged
for in reviews that the field hasn't delivered), and a *realistic
revenue band*. The tool must be willing to say *don't build this*
when the data says so.

v1 is a standalone Python script the operator runs locally. Reads
from prod DB (no writes). One batch LLM call for the synthesis.
No web fetches, no DB writes, no library_layer imports.

## Deliverable

One file: `scripts/concept_doctor_v1.py`.

CLI:
```
poetry run python scripts/concept_doctor_v1.py --target-appid <id> [--peers 30] [--data-only]
```

- `--target-appid` is the game the operator wants to build "something like".
- `--peers` caps the peer set size (default 30 — wider than Tag Doctor's
  15 because we need both Winners and Losers in the cohort).
- `--data-only` skips the LLM verdict and emits the data report only.

Output:
- `reports/concept_doctor/<target_appid>_<utc_timestamp>.md` (rendered report)
- `reports/concept_doctor/<target_appid>_<utc_timestamp>_data.json` (raw structured data)

Also prints the report to stdout.

## DB Connection

Reads prod via `STEAMPULSE_PROD_DATABASE_URL` env var (psycopg2
directly, no SQLAlchemy, no library_layer imports). Do NOT
`from sp import ...` — sp.py injects dummy AWS creds at import time.
The script uses `psycopg2.connect(os.environ["STEAMPULSE_PROD_DATABASE_URL"])`
with `set_session(readonly=True)`.

## What the Script Does

### 1. Pull the target game

Standard `games` row + top-20 tags. Same pattern as Tag Doctor's
`fetch_dev_game` / `fetch_dev_tags`. If the target has no tags or
isn't in the DB, abort with a helpful message.

### 2. Pick the peer cohort (winners AND losers)

Reuse Tag Doctor's `pick_peers` SQL verbatim — the IDF-weighted
cosine similarity over normalized top-20 tag profiles is exactly
what's needed to find a tag-coherent neighborhood. **Two changes
vs Tag Doctor:**

- Lower the `review_count` floor to 50 (was 500) so we capture the
  full distribution, including releases that flopped.
- Drop the `positive_pct >= 75` floor entirely so Losers qualify.
- Keep the IDF² weighting and tag-richness floor (≥10 tags with
  votes > 0).

After selecting the top 30 peers by similarity, partition them in
Python:
- **Winners**: `review_count >= 500 AND positive_pct >= 80`
- **Mid**: anything else that passes the floor
- **Losers**: `review_count >= 50 AND positive_pct < 60`

### 3. Compute market vitals

One query per signal, all read-only:

- **Release velocity over time**: count of peer-tag-set releases
  per year for the last 5 years. Use the target's top-5 tag fingerprint
  to define the niche; count games with `release_date IS NOT NULL`
  and `coming_soon = FALSE` carrying ≥3 of those tags in their top 10.
  (`mv_genre_monthly_release_count` is genre-scoped; for a custom
  tag fingerprint we compute inline.)
- **Revenue distribution**: p25, median, p75, p90 of
  `estimated_revenue_usd` across the peer set, partitioned by
  Winner / Mid / Loser.
- **Success rate**: % of all games carrying ≥3 of the target's top-5
  tags that crossed `review_count >= 500`.
- **Demand signal**: median `review_velocity_lifetime` of the
  Winners' top decile vs the niche-wide median. Higher in the top
  decile = unsatisfied demand; converged = market satisfied.
- **Pricing**: distribution of `price_usd` and `is_free` rate within
  the peer set, separated by Winner / Loser.

### 4. Hard pre-flight check: every peer must have a Phase-3 report

The expensive Phase-1–3 LLM analysis ($1/game) is persisted in the
`game_reports` table. Concept Doctor reads these reports but must
**never trigger Phase-3 analysis itself**. Before spending any
budget on the verdict synthesis, the script verifies coverage:

```sql
SELECT g.appid, g.name, g.review_count
FROM games g
LEFT JOIN game_reports gr ON gr.appid = g.appid
WHERE g.appid = ANY(:peer_appids)
  AND gr.appid IS NULL
ORDER BY g.review_count DESC;
```

**If any peer in the selected cohort is missing a Phase-3 report,
the script bails immediately:**

- Print a single block listing the missing appids with their names
  and review counts, in a copy-paste friendly format (one appid
  per line) so the operator can hand them to the Phase-1–3 runner.
- Write nothing to `reports/concept_doctor/`.
- Make no LLM call.
- Exit non-zero (e.g. exit code 9) with a one-line summary like
  `Concept Doctor needs Phase-3 reports for N of M peers. Run
  Phase 1–3 on the appids above, then re-run.`

This is a hard contract: Concept Doctor either has the full peer
cohort analyzed and produces a grounded verdict, or it bails
entirely with a clean action list. There is no partial / degraded
output mode. The operator, not the tool, controls when Phase-3
spend happens.

If coverage passes, fetch the reports:

```sql
SELECT appid, report_json, reviews_analyzed, analysis_version
FROM game_reports
WHERE appid = ANY(:peer_appids);
```

`report_json` contains a `GameReport` with:
- `friction_clusters`: top friction points players hit
- `wishlist_items`: features players asked for
- `dropout_moments`: where players churn
- `competitor_refs`: games this one is compared to
- per-cluster `mention_count` and quoted reviewer language

### 5. Aggregate friction / wishlist signals across cohort

Following the Phase-4 synthesis pattern in
`library_layer/prompts/genre_synthesis_v1.py`: a friction or wishlist
item is significant if it appears in ≥3 peers' GameReports
(`SHARED_SIGNAL_MIN_MENTIONS = 3`).

Compute three rollups in Python from the JSONB:
- **Winner friction**: friction clusters mentioned by ≥3 Winners.
  These are the features Winners *had to solve well* — table stakes.
- **Wishlist items**: wishlist items mentioned by ≥3 peers (any tier).
  These are the unmet demands — differentiation territory.
- **Loser-specific friction**: friction clusters mentioned by ≥3
  Losers but absent from Winners. These are the warning signs.

### 6. Compute tag DNA contrast

In Python:
- **Table-stakes tags**: tags present in the top-10 of ≥80% of Winners.
- **Winning differentiators**: tags present in ≥40% of Winners but
  ≤20% of Losers. These are the success indicators.
- **Loser warning tags**: tags present in ≥40% of Losers but ≤10%
  of Winners.

### 7. Pydantic data structure

```python
class TagWithVotes(BaseModel):
    name: str
    votes: int

class CohortPeer(BaseModel):
    appid: int
    name: str
    review_count: int
    positive_pct: int
    estimated_revenue_usd: float | None
    price_usd: float | None
    release_year: int | None
    cohort: str  # "winner" | "mid" | "loser"
    overlap_score: float
    has_game_report: bool

class FrictionSignal(BaseModel):
    topic: str
    mention_count: int
    cohort_seen_in: list[str]  # ["winner", "mid", "loser"]
    representative_quotes: list[str]  # cap at 3, 200 chars each

class WishlistSignal(BaseModel):
    topic: str
    mention_count: int
    representative_quotes: list[str]

class TagDNA(BaseModel):
    table_stakes: list[str]           # tags in >=80% of Winners
    winning_differentiators: list[str] # in >=40% Winners, <=20% Losers
    loser_warnings: list[str]          # in >=40% Losers, <=10% Winners

class MarketVitals(BaseModel):
    releases_per_year_last_5: dict[int, int]  # year -> count
    saturation_trend: str  # "growing" | "stable" | "declining"
    revenue_p25_winners: float
    revenue_median_winners: float
    revenue_p75_winners: float
    revenue_p90_winners: float
    success_rate_pct: float  # % of niche games crossing 500 reviews
    median_price_winners: float
    free_to_play_pct_winners: float
    top_decile_review_velocity: float
    niche_median_review_velocity: float

class ConceptDoctorData(BaseModel):
    target_appid: int
    target_name: str
    target_top_tags: list[TagWithVotes]
    wedge_fingerprint: list[str]  # the top-5 tags defining the niche
    peers: list[CohortPeer]
    winners_count: int
    losers_count: int
    peers_with_reports: int
    market_vitals: MarketVitals
    tag_dna: TagDNA
    winner_friction: list[FrictionSignal]
    wishlist: list[WishlistSignal]
    loser_friction: list[FrictionSignal]
```

Persist `ConceptDoctorData` as the `_data.json` sidecar.

### 8. Render data report (markdown)

Always emit. Sections in order:

- `# Concept Doctor for "{target_name}" (appid {appid})`
- `Generated <utc_timestamp> against prod`
- `## The Niche` (wedge fingerprint, peer-cohort split, winners/mid/losers counts)
- `## Market Vitals` (releases-per-year table + saturation trend, revenue
  distribution table, success rate, demand signal, pricing)
- `## Table-Stakes Tags` (with % of Winners carrying each)
- `## Winning Differentiators` (tags + % gap between Winners and Losers)
- `## Loser Warning Signs` (tags + reasons)
- `## What Winners Had to Solve` (winner_friction with quote samples)
- `## What Players Are Begging For` (wishlist with quote samples)
- `## What Tanks Losers` (loser_friction with quote samples)
- `## Peer Cohort` (table of all 30 peers with their classification)

Pure data, deterministic for the same input.

### 9. LLM verdict (skipped if --data-only)

One batch request via the Anthropic batch API per
`feedback_always_batch_api.md`. Model: `claude-opus-4-7`.

Inline batch lifecycle (no library_layer imports): create →
poll every 30s → retrieve → extract text content. Same pattern
as `submit_batch_and_wait` in `tag_doctor_v1.py`.

System prompt:

```
You are a senior indie game producer who has shipped 4 commercial
hits and 2 commercial failures in the past decade. You have one
target concept's tag profile, the cohort of 30 tag-coherent peers
split into Winners / Mid / Losers, market vitals, tag-DNA contrast,
and aggregated friction / wishlist signals from real player reviews.

Produce a verdict in markdown. Rules:

1. Lead with a one-sentence verdict: GO, CONDITIONAL GO, or NO.
2. Follow with a realistic revenue band sentence: "If you execute
   at the p50 of this niche, you make $X. p75: $Y. p90: $Z." Cite
   the data row.
3. List 5 to 8 must-have features (table stakes), each with a
   one-line rationale citing tag DNA, friction, or wishlist data
   ("8/10 Winners carry Tower Defense + Auto Battler in top 10",
   "5 Winners' reports flag pacing-breaks-after-hour-10 — solve
   this or churn at hour 8").
4. List 2 to 4 differentiation opportunities — wishlist items
   that recur across the cohort but no Winner has fully delivered.
5. List 2 to 4 hard pitfalls — loser-specific friction or warning
   tags. Each with a citation.
6. Close with one paragraph of brutal honesty: state explicitly
   that this analysis says nothing about *the operator's* execution
   capacity, and that of N similar peers, M shipped a 4/10. Name
   the gap between data sufficiency and execution sufficiency.
7. No invented features. No filler. No throat-clearing. Be blunt.
8. End with one sentence on cadence: re-run Concept Doctor as the
   project takes shape, and again at the 3-month mark.
```

User message: `ConceptDoctorData` JSON serialized + one-line ask
("Produce the verdict.").

Append the LLM's markdown to the data report under a leading
`## Verdict & Reality Check` section, placed at the top so the
operator sees the verdict first.

## Implementation Notes

- One file. No package structure for v1. Helpers inline.
- `psycopg2` (matches codebase). No SQLAlchemy.
- One-line comments only (per `feedback_terse_comments.md`).
- pydantic.BaseModel for all data structures (per `feedback_always_pydantic.md`).
- No field defaults that hide required-ness; every field explicit
  (per `feedback_no_field_defaults.md`).
- No script tests (per `feedback_no_script_tests.md`).
- No em-dashes in output strings (per `feedback_no_em_dashes.md`).
- No commit/push from the assistant (per `feedback_no_commit_push.md`).
- Output paths: create `reports/concept_doctor/` if missing.
- On any DB error, print a helpful message and exit non-zero.
- Reuse `pick_peers` from Tag Doctor v1 with the `review_count`/`positive_pct`
  floors loosened — copy the function inline (don't import).

## Reusable Surface for Page Doctor v2

Structure the data-extraction functions as pure functions taking a
connection and returning pydantic models:

- `fetch_target_game(conn, appid) -> TargetGame`
- `pick_cohort(conn, appid, n) -> list[CohortPeer]` (the loosened-floor
  variant of Tag Doctor's pick_peers)
- `fetch_market_vitals(conn, wedge_fingerprint, peer_appids) -> MarketVitals`
- `fetch_game_reports(conn, peer_appids) -> dict[int, dict]` (raw JSONB)
- `aggregate_friction_and_wishlist(reports, cohort_split) -> tuple[list[FrictionSignal], list[WishlistSignal], list[FrictionSignal]]`
- `compute_tag_dna(peer_top_tags, cohort_split) -> TagDNA`
- `compute_concept_data(...) -> ConceptDoctorData`

Page Doctor v2 will lift these into the library layer wholesale.

## What the System Can Answer vs Can't (be explicit in the report)

Strong:
- Niche size, growth, saturation
- Tag DNA of winners vs losers
- Friction / wishlist / dropout themes from real reviews
- Revenue bands from Boxleiter v2 estimates
- Pricing anchors

Partial:
- Wishlist API is gated; demand is proxied via review velocity, not
  pre-launch wishlist counts.
- Post-launch update cadence isn't tracked.

Out of scope (called out in the verdict's honesty paragraph):
- Operator's execution capacity
- Marketing/PR fit
- Platform expansion analysis

## Out of Scope (v2 / Page Doctor)

- Vision (no images involved)
- Persistence to a `concept_reports` table
- Free vs Pro gating
- Per-peer LLM re-analysis (relies on pre-computed `game_reports`)
- Multi-target concept comparison ("compare There Are No Orcs vs
  Idle Monster TD as targets")

## Verification

1. Run on `--target-appid 3480990` (There Are No Orcs). Verdict
   should be CONDITIONAL GO; table stakes should include Tower
   Defense + Auto Battler + Roguelite; differentiation suggestions
   should focus on the medieval/cute axis (per the wishlist
   signals from peers).
2. Run on a known graveyard niche (pick a target whose peer
   cohort has median revenue under $5k and declining release
   velocity). Verdict should be NO with cited data.
3. Run on Corner Quest (`--target-appid 4254260`). Confirm the
   report frames it from the prospective-builder angle: peer
   cohort spans bullet-hell, idler, auto-battler, tower-defense,
   roguelite. Verdict should be CONDITIONAL GO with table stakes
   matching what NIMRODS / Idle Monster TD / Desktop Defender all
   solve.
4. Run with `--data-only` and confirm deterministic output (modulo
   timestamp). Confirm the data sections are interpretable on
   their own.
5. Run on a target whose peer cohort contains at least one peer
   missing a Phase-3 report. Confirm the script:
   - Exits non-zero with the missing-peers block.
   - Writes nothing to `reports/concept_doctor/`.
   - Makes no LLM call (no Anthropic spend).
   - Prints the missing appids in a copy-paste friendly format.
6. After running Phase 1–3 on the missing peers manually, re-run
   Concept Doctor and confirm it now proceeds end-to-end.
