# Surface Freshness Timestamps in Quick Stats (Analyzed + Unanalyzed)

## Context

The data-source-clarity refactor added per-source freshness timestamps to the
API response and rendered them as small "Crawled X ago" / "Analyzed X ago"
suffixes inside the **Steam Facts** and **SteamPulse Analysis** zone headers in
the "The Verdict" section. Those zones live inside the *analyzed-game* JSX
branch only — for an unanalyzed game, the entire Verdict section is skipped, and
even on analyzed games the timestamps are easy to miss because they're tucked
into a narrow header strip.

We want freshness visible **on every game page**, including unanalyzed ones, in
a more obvious place: under the **Reviews** tile in Quick Stats (when reviews
were last fetched), plus a small page-level "metadata last updated" line
nearby. We already pass `metaCrawledAt`, `reviewCrawledAt`,
`reviewsCompletedAt`, `tagsCrawledAt`, and `lastAnalyzed` as props to
`GameReportClient` — but only in the Suspense **fallback** render path. The
primary render path goes through `ToolkitShell.lensContent.sentiment` in
`page.tsx`, and that `GameReportClient` instance is currently missing the
freshness/Steam-sentiment props. They need to be wired through there as well —
otherwise the new captions never appear at runtime. No API changes needed.

## Approach

Two-file change:
1. `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — add a tiny muted
   caption inside the **Reviews** tile and a single muted "Page metadata
   updated X ago" line below the Quick Stats grid. Apply both edits to BOTH JSX
   branches (unanalyzed ~L229, analyzed ~L524) so an un-LLM-analyzed game still
   shows the same trust signals.
2. `frontend/app/games/[appid]/[slug]/page.tsx` — pass the freshness +
   Steam-sentiment props (`positivePct`, `reviewScoreDesc`, `metaCrawledAt`,
   `reviewCrawledAt`, `reviewsCompletedAt`, `tagsCrawledAt`, `lastAnalyzed`) to
   the `GameReportClient` rendered inside `ToolkitShell.lensContent.sentiment`,
   not just to the Suspense fallback instance.

### Reviews tile caption

In each branch, inside the existing `<div>` for the "Reviews" tile, after the
count `<p>`, append:

```tsx
{(() => {
  const ts = relativeTime(reviewCrawledAt) ?? relativeTime(reviewsCompletedAt);
  return ts ? (
    <p className="text-xs font-mono text-muted-foreground mt-1">Crawled {ts}</p>
  ) : null;
})()}
```

Renders nothing when both timestamps are null (graceful degradation — same
pattern already used in the Steam Facts zone header). Sources:
`reviewCrawledAt` first (most direct), falling back to `reviewsCompletedAt`.
Same precedence the Verdict section already uses.

### Page-metadata caption below the grid

Immediately after the closing `</div>` of the Quick Stats grid in each branch,
add:

```tsx
{(() => {
  const metaTs = relativeTime(metaCrawledAt);
  return metaTs ? (
    <p className="mt-3 text-xs font-mono text-muted-foreground">
      Page metadata updated {metaTs} · Source: Steam
    </p>
  ) : null;
})()}
```

Compute `relativeTime(metaCrawledAt)` once and reuse it — calling it twice
(condition + interpolation) duplicates work and can produce edge-case
inconsistencies near rounding boundaries since it depends on `Date.now()`.

Single line, muted, sits flush under the grid. Skipped entirely when
`metaCrawledAt` is null.

### Why not modify the Steam Facts zone header

That header still serves its purpose for analyzed games (it groups the
Steam-sourced sentiment with its own freshness chip). Quick Stats freshness is
additive — visible without scrolling, visible on unanalyzed games, and per-tile
rather than zone-wide.

## Critical files

- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`
  - Unanalyzed branch: Reviews tile around lines 232–241; grid closes around line 311.
  - Analyzed branch: Reviews tile around lines 524–533; grid closes around line 599.
  - The `relativeTime()` helper at module level (~line 85) is already in scope; no new imports.

## Reuse notes

- `relativeTime(iso: string | null | undefined): string | null` —
  module-level helper already defined in `GameReportClient.tsx`. Returns "just
  now", "Xm ago", "Xh ago", "Xd ago", "Xmo ago", "Xy ago", or `null` for
  missing input.
- Freshness props (`metaCrawledAt`, `reviewCrawledAt`, `reviewsCompletedAt`,
  `tagsCrawledAt`, `lastAnalyzed`) are already destructured in the component
  signature (~line 119) and passed by
  `frontend/app/games/[appid]/[slug]/page.tsx`.
- API response (`/api/games/{appid}/report` `game` block) already includes the
  underlying ISO strings — see
  `src/lambda-functions/lambda_functions/api/handler.py` `get_game_report()`.

## Out of scope

- No backend changes. No API contract changes.
- No card-level freshness on listing pages — the original data-source-clarity
  prompt explicitly excluded that ("keep cards minimal").
- No `tags_crawled_at` surfacing yet — that lives in the tag-cloud component
  and is a separate task.
- No new shared `<Freshness />` UI component — the inline pattern is short,
  the component currently uses inline plain elements throughout, and a
  separate component buys nothing for two callsites in one file.

## Verification

1. `cd frontend && npm run dev`.
2. **Analyzed game** (`/games/440/team-fortress-2` or any local appid with a
   row in `reports`): Reviews tile shows "Crawled 2h ago" beneath the count;
   "Page metadata updated 2d ago · Source: Steam" line appears immediately
   below the grid.
3. **Unanalyzed game** (any local appid that's been crawled but never run
   through analysis): same behaviour — Reviews tile + footer line both appear.
   This is the explicit requirement.
4. **Game with NULL freshness columns** (e.g., a stub/never-crawled appid, or
   a test DB before any catalog backfill): Reviews tile shows the count alone,
   footer line is omitted entirely. No layout shift, no broken render.
5. Quick API sanity:
   ```bash
   curl -s http://localhost:8000/api/games/<appid>/report \
     | jq '.game | {meta_crawled_at, review_crawled_at, reviews_completed_at}'
   ```
   Confirms the timestamps that drive the rendering.
6. `cd frontend && npm run lint` passes (no new files, no new imports → unlikely
   to fail, but cheap to verify).
7. Playwright tests in `frontend/tests/` continue to pass — the new lines are
   additive and don't change any existing data-testid or semantic structure.
