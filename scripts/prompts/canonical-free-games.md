# Canonical-free game set

Define and support a stable, sticky set of "always fully visible, free" per-game pages on top of the showcase rule. Big-name games (Elden Ring, Baldur's Gate 3, Cyberpunk, Skyrim, etc.) are SEO magnets and trust-builders for any buyer who lands on one. They do not cannibalize the genre report SKU because a single per-game deep-dive does not substitute for cross-cohort synthesis.

Sits alongside the showcase rule from `scripts/prompts/rdb-launch-spec.md` Section 3. A per-game page renders in full when EITHER:

- The appid is in `benchmark_appids` of any published `reports` row (the showcase rule), OR
- `games.is_canonical_free = true` (this prompt's rule)

Otherwise the page renders the abbreviated preview.

## Why a rule, not a hand-curated list

A list invites case-by-case decisions and silent downgrades. A rule is auditable, idempotent, and stable across operators. Once a game enters the canonical-free set it stays there, even if its review count later drops below the threshold. That stickiness is the whole point of the commitment.

## Selection rule

Top 200 analyzed games by lifetime `review_count`, with no sentiment filter and a stickiness clause:

1. Eligibility: top 200 by `review_count` among rows where `has_analysis = true`. No `positive_pct` floor.
2. Already-canonical rows stay canonical. The populator script never sets `is_canonical_free = false` on a row that is already true. If a game falls out of the top 200, it remains in the canonical set forever.
3. New rows that match eligibility are added on each populator run.

The set grows monotonically. N starts at 200; revisit only when SEO data justifies a larger commitment (recommend leaving it at 200 for at least 6 months post-launch).

### Why no sentiment filter

A "Mixed" or "Mostly Negative" game with a strong analysis page is the best proof of what the engine does. Cyberpunk 2077, New World, Helldivers 2 in their review-bomb periods, ARK, etc. are exactly where buyers want to see whether SteamPulse can surface the actual issues. Filtering to only positive games would make the canonical set look cherry-picked. The diversity of sentiment is the point.

The set might include games whose reviews are dominated by a transient controversy. Those analyses re-run when the analysis pipeline re-runs against fresh review data; canonical-free status does not freeze the report content.

## Files to create / modify

### Database migration

`src/lambda-functions/migrations/<next>__games_is_canonical_free.sql`:

```sql
ALTER TABLE games
  ADD COLUMN is_canonical_free BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX games_is_canonical_free_idx
  ON games (is_canonical_free)
  WHERE is_canonical_free = true;
```

The partial index keeps lookups fast (the canonical set is small relative to the catalog).

### Populator script

`scripts/populate_canonical_free.py`:

Operator script. Idempotent. Re-entrant. No unit tests (per `feedback_no_script_tests`). Inline DB connection helper, no `from sp import ...` (per `feedback_sp_py_import_side_effects`).

Behavior:

- Connect to production DB (read connection string from env, same pattern as other operator scripts).
- Query the eligible candidate set:
  ```sql
  SELECT appid, name, review_count, positive_pct
  FROM games
  WHERE has_analysis = true
    AND review_count IS NOT NULL
  ORDER BY review_count DESC
  LIMIT 200;
  ```
- For each candidate, set `is_canonical_free = true` (no-op if already true).
- Print a summary: `N candidates evaluated, M newly added, K already canonical, total canonical = M + K`.
- Print the list of newly-added games (appid, name, review_count) for operator audit.
- Exit zero on success.

Optional flag `--dry-run` that prints the diff without writing.

Optional flag `--list` that prints the current canonical set sorted by review_count.

### Backend API integration

The per-game endpoint that powers `frontend/app/games/[appid]/[slug]/` must include `is_canonical_free` on the `game` block (alongside the existing fields). The `getGameReport` response in `frontend/lib/api.ts` already declares the `game` shape; add `is_canonical_free?: boolean` to that interface.

The endpoint logic (in `src/lambda-functions/lambda_functions/api/...`) returns the full `GameReport` shape when EITHER:

- The appid appears in `benchmark_appids` of any row in `reports`, OR
- `games.is_canonical_free = true`

Otherwise it returns the abbreviated preview shape (top 3 strengths + top 3 complaints + basic metadata + upsell). The preview-vs-full decision is server-side; do not push it to the client.

### Frontend integration

`frontend/app/games/[appid]/[slug]/GameReportClient.tsx` already renders the full `GameReport` when present. The change is upstream in the API response: when the API returns the abbreviated shape, render preview mode; when it returns the full shape, render today's full layout. No render-mode flag needed on the client.

For the operator: there is no UI surface for `is_canonical_free` itself. It is set entirely by the populator script.

## Operational cadence

Run the populator weekly. Add a cron-driven Lambda or run it as part of the existing `matview_refresh` schedule. Per `feedback_no_staging_schedules`, the EventBridge rule must be gated on `config.is_production`.

Alternatively the operator runs `scripts/populate_canonical_free.py` manually after any large analysis batch. Both are fine; the script is idempotent.

## Cost expectations

The script reads `games` and writes a small number of rows. Negligible.

The set itself implies one-time analysis cost. As of today, ~200 games have been analyzed. The eligible top-200-by-review-count likely overlaps partially. For appids in the top 200 by review count but not yet analyzed, the operator decides per game whether to spend the ~$0.50 to $1.00 LLM cost to analyze. The populator script does not trigger analysis automatically; it only marks already-analyzed games as canonical-free.

To find the gap: a small companion query (run manually) returns the top-200-by-review-count games that are NOT yet analyzed:

```sql
SELECT appid, name, review_count, positive_pct
FROM games
WHERE (has_analysis = false OR has_analysis IS NULL)
  AND review_count IS NOT NULL
ORDER BY review_count DESC
LIMIT 200;
```

That list is the operator's analysis backlog if they want to fill out the canonical set. Sentiment is intentionally not filtered: a "Mostly Negative" big-name game with a sharp analysis is a better demo than a "Very Positive" one.

## Verification

- Migration applies cleanly: `ALTER TABLE games` succeeds and the partial index is created.
- Populator dry-run on production data prints a list of ~200 appids without writing.
- Populator real run sets the flag and the count of `is_canonical_free = true` rows matches the dry-run.
- Re-running the populator the same day adds zero new rows.
- A test row marked `is_canonical_free = true` whose review count later drops below the top 200 stays canonical (verify by manually adjusting a non-production row's `review_count`).
- The per-game API returns the full report shape for a canonical-free appid even if it is not in any `benchmark_appids` set.
- The frontend `/games/[appid]/[slug]/` page renders the full report for a canonical-free appid.
- The defensive `frontend/tests/home.spec.ts` "no paywall" assertion still passes.

## Spec update

After this prompt ships, update `scripts/prompts/rdb-launch-spec.md` Section 3 to add the canonical-free rule alongside the showcase rule. The free-mode triggers become:

- Showcase: appid in `benchmark_appids` of any published report.
- Canonical: `games.is_canonical_free = true`.
- Otherwise: preview mode (top 3 + top 3 + metadata + upsell).
