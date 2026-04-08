# Revenue Estimates — UI Integration

Follow-up to `revenue-estimates.md`. The backend now ships `estimated_owners`, `estimated_revenue_usd`, and `revenue_estimate_method` on the `games` row, and the API (`GET /api/games/{appid}/report`) already returns them in `game_meta` when non-null. Nothing in `frontend/` consumes these fields yet. This prompt delivers the first user-visible surface: a **Market Reach** card on the game report page.

Market Map lens, Compare lens row, and list-page revenue sort are **out of scope** — they have their own prompts / lenses. This prompt is the single-game page only.

## Why this matters

Indie devs are the target Pro audience. "How much did this game make?" is the first question they ask about any game. VG Insights and Gamalytic charge for this number behind a full dashboard; our wedge is showing it **inline** beside the qualitative report on a page they already came for. Every game-page view without this card is a missed conversion trigger for Pro.

## UX Research — what the category does well

Study these (login-walled numbers are fine to infer from public screenshots and marketing pages):

- **VG Insights** (vginsights.com) game pages — look at the revenue block layout, the confidence language ("Estimated"), and how they disclaim gross-vs-net.
- **Gamalytic** (gamalytic.com) — similar numbers, different visual treatment; they lean heavier on a range display.
- **SteamDB** — owner estimates (old Boxleiter-style) with a simple range; minimalist, trust-first presentation.
- **Steam Spy** — historical baseline; the user expectation for what "owner estimate" means was set here.
- **Stratechery / The Information paywall cards** — not gaming, but the gold standard for a "you can see the headline, pay to see the number" tease. Worth reading for blur/lock treatment ideas.

**Patterns worth stealing:**

1. **Lead with a range, not a point estimate.** Users distrust a single precise number for a modeled quantity. "180k – 540k owners" reads as honest; "362,400 owners" reads as fake precision. Compute the range in the frontend from the point estimate using the ±50% confidence band documented in `revenue-estimates.md`: `low = round(point * 0.5)`, `high = round(point * 1.5)`. Round to 2 significant figures for display.
2. **Explain the method in one sentence, not a footnote.** A tiny "How is this calculated?" disclosure that expands inline beats a footnote users never scroll to.
3. **Always label "gross".** "Estimated gross revenue (pre–Steam cut, pre-refunds)". Never just "Revenue".
4. **Method badge.** Small pill reading `boxleiter_v1` linking to a methodology page (stub for now — link to `/methodology/revenue` which can 404 until a follow-up writes it, or link to `#` with a tooltip).
5. **Empty state is a design surface, not an error.** When the estimate is null (free-to-play, <50 reviews, DLC/demo), show a compact grey card explaining *why* there's no estimate. Do not hide the card entirely — the absence of a number is itself information, and hiding would make the card feel broken on half of games.
6. **Confidence is part of the primary display, not small print.** A `±50%` badge next to the number, not a footnote. Users who see a range *and* a confidence marker trust the number more, not less.

**Anti-patterns to avoid:**

- No bogus "chart" of a single data point. One number does not need a sparkline.
- No giant hero number that dominates the page — Market Reach is one signal among many (sentiment, promise gap, etc.), not the headline.
- No emoji or money-bag iconography. This is a signal for professionals; keep it sober.
- No "last updated X days ago" unless we actually refresh on a schedule (we don't — it updates on re-analysis).

## Data shape (already shipped)

`GET /api/games/{appid}/report` returns, inside `game_meta` (or the top-level game object — verify in `frontend/lib/api.ts` and `frontend/lib/types.ts`):

```ts
estimated_owners?: number;            // bigint from PG, JSON number in practice
estimated_revenue_usd?: number;       // numeric(14,2), serialized as float
revenue_estimate_method?: string;     // "boxleiter_v1" or null
```

All three are absent when the backend has no estimate. The frontend must treat **any missing field** as "no estimate available" and render the empty state.

Note: the backend now returns `revenue_estimate_reason` on the report
`game` block when non-null (shipped alongside this prompt). The field
is persisted in a nullable `games.revenue_estimate_reason TEXT` column
added by migration `0030_add_revenue_estimate_reason.sql`, written from
`process_results.py` and `analysis_service.py`, and surfaced by the
report handler. Possible values come straight from the estimator:
`insufficient_reviews`, `free_to_play`, `missing_price`, `excluded_type`
(or NULL when a numeric estimate is present — the repo layer coerces
`reason` to NULL whenever `estimated_owners` / `estimated_revenue_usd`
are set, so stale codes cannot leak through).

## Implementation

### 1. Types — `frontend/lib/types.ts`

Extend the report / game type with the three new optional fields plus `revenue_estimate_reason`. Keep them optional — never required — because old cached responses won't have them.

### 2. Component — `frontend/components/game/MarketReach.tsx`

New client component. Props:

```ts
type MarketReachProps = {
  estimatedOwners: number | null;
  estimatedRevenueUsd: number | null;
  method: string | null;
  reason: string | null;         // "insufficient_reviews" | "free_to_play" | "excluded_type" | null
  reviewCount: number;           // to show "not enough reviews yet (N/50)"
  isPro: boolean;                // gating is frontend-only per CLAUDE.md
};
```

Responsibilities:

- **Populated state:** render two stacked stats — "Estimated owners" and "Estimated gross revenue" — each as a **range** (low / high from ±50%), formatted with `Intl.NumberFormat` (`compact` notation for owners above 100k, `currency: "USD"` + compact for revenue). Confidence pill `±50%` next to each. Method pill. One-sentence method explainer under the stats: *"Based on review count × genre/age/price-adjusted Boxleiter ratio. Gross revenue before Steam's 30% cut, refunds, and regional pricing."*
- **Empty state:** grey card, same footprint, no blur. Copy depends on `reason`:
  - `insufficient_reviews` → "Not enough reviews yet to estimate ({reviewCount}/50)."
  - `free_to_play` → "Free-to-play — revenue estimates don't apply."
  - `missing_price` → "No estimate: missing store price."
  - `excluded_type` → "No estimate: DLC, demos, and tools aren't eligible."
  - `null` reason but null numbers → generic "No estimate available."
- **Pro gating:** when `isPro === false`, blur **only the numeric range** (`<p>`) inside each stat with `blur-sm` + `aria-hidden`. Labels, `±50%` confidence pills, method pill, and the one-sentence explainer all remain fully readable. The "Unlock with Pro" CTA renders **inline below the stats grid** (not as an absolute overlay) so nothing obscures the labels. `isPro` is read from the `usePro()` context — which currently returns `false` everywhere until `pro-gating.md` lands. Empty states are NOT gated — showing "not enough reviews" to free users reinforces trust.
- **Accessibility:** each blurred range is `aria-hidden` and paired with an `sr-only` "<label> available with Pro." sibling. The CTA itself carries `aria-label="Market reach estimate — unlock with Pro"` so screen readers hear the intent, not the blurred digits.

Styling: match the visual weight of existing card components in `frontend/components/game/` — look at `CompetitiveBenchmark.tsx`, `PromiseGap.tsx`, and `HiddenGemBadge.tsx` for card chrome, spacing, and typography so Market Reach feels like it belongs on the page, not bolted on.

### 3. Wire into the game page — `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`

**Important constraint uncovered during implementation:** the revenue estimate is derived from `review_count` × price × genre/tags — **none of which require an LLM pass**. The card must therefore render on both the analyzed and unanalyzed code paths. `GameReportClient` originally had an `if (!report) return` early return that would have hidden Market Reach for any crawled-but-not-yet-analyzed game; that early return was collapsed into a single unified render path as part of this prompt. See "Unifying the render paths" below.

Place the `<MarketReach />` card **immediately after the Quick Stats section and before the narrative sections** (Design Strengths / Gameplay Friction / etc.). Rationale: it's a quantitative signal that belongs with the other numeric tiles, and on unanalyzed pages it becomes the last quantitative block before the "Analysis in progress" notice.

`isPro` is read from the existing `usePro()` context — no new prop plumbing. Until `pro-gating.md` wires a real subscription source, the context returns `false` everywhere, which is the correct free-tier default.

#### Unifying the render paths

The two-branch layout (`if (!report)` early return vs. full-report JSX) was duplicating ~200 lines of chrome and, more importantly, was hiding Market Reach from unanalyzed games. The right fix is a single render path with conditional sections, which also unblocks surfacing Steam sentiment to unanalyzed pages. Extract the duplicated chrome into three focused presentational components under `frontend/components/game/`:

- **`GameHero.tsx`** — hero image, title, genre chips, badge row. Accepts `hiddenGemScore: number | null` and only renders `<HiddenGemBadge />` when non-null, so unanalyzed games get the hero without the score badge. The Steam sentiment chip keys off `reviewScoreDesc` (Steam-owned, not LLM) and works on both paths.
- **`SteamFactsCard.tsx`** — `ScoreBar` + crawl freshness + the `scoreContextSentence()` copy. Used twice inside `GameReportClient`: inline within the Verdict section on analyzed pages, and standalone (under its own `Steam Facts` section label) on unanalyzed pages. Surfacing Steam sentiment context to unanalyzed pages is a **new user-visible gain** that falls out of this refactor.
- **`QuickStats.tsx`** — the stats grid. Takes both `reviewCount` (Steam total) and `totalReviewsAnalyzed` (LLM-ingested English count) and prefers the latter with an `en` suffix when present. Auto-switches between 5-column (no Analyzed tile) and 6-column (with Analyzed tile) based on whether `lastAnalyzed` is set. No visual regression on analyzed pages.

Extract `relativeTime()` and `slugify()` into a new `frontend/lib/format.ts` — both helpers are now used from 3+ files, so this is legitimate deduplication, not speculative abstraction. `scoreContextSentence()` and `momentumLabel()` stay local to the one component that uses them.

Then collapse `GameReportClient` to a single return composed of these components:

1. `<GameHero />` (always) — hidden-gem badge conditional on `report?.hidden_gem_score`.
2. `<Breadcrumbs />` (always).
3. **Verdict section** (`report && …`) — LLM one-liner, `Compare with…` CTA, inline `<SteamFactsCard />`, and the `SteamPulse Analysis` marker.
4. **Standalone Steam Facts** (`!report && …`) — unanalyzed pages get `<SteamFactsCard />` under its own `Steam Facts` section label.
5. `<QuickStats />` (always).
6. `<MarketReach />` (always) — the whole point of the refactor.
7. `About` section (`!report && shortDesc && …`) — unanalyzed only. Analyzed pages carry this weight through the LLM narrative.
8. Report-gated narrative sections: Design Strengths, Gameplay Friction, Audience Profile, Sentiment Trend, Genre Context, Promise Gap, Player Wishlist, Churn Triggers, Developer Priorities, Competitive Context. Each guarded with `{report?.field && …}`.
9. `Sentiment History` + `Playtime Sentiment` (always) — both are Steam-sourced, render on both paths.
10. `Competitive Benchmark` (`report && benchmarks && …`) — depends on the report existing (benchmarks are only fetched when `report` is non-null).
11. `Tags` (always).
12. `<GameAnalyticsSection />` (`report && …`) — intentionally gated for now; could be relaxed later since most of its sub-queries are Steam-sourced, but out of scope for this prompt.
13. "Analysis in progress" notice (`!report && …`).
14. Footer (always) — `Analysis based on N reviews` line is `report &&`-gated; the `View on Steam Store →` link always renders.

All existing `data-testid`s — `game-compare-deeplink`, `steam-facts-crawled`, `reviews-tile-crawled`, `quick-stats-meta-updated`, `score-context`, plus the Market Reach IDs — must flow through the new components unchanged so the existing Playwright specs keep passing without modification.

**Rules of thumb that kept this refactor debt-free:**
- Single-file rewrite, no `v2` alongside the old. Old code is gone, not deprecated.
- Each extracted component has exactly one responsibility and is used in at least one concrete site (no speculative abstraction).
- Helpers are extracted only after hitting ≥3 call sites.
- The unified path replaces the branched path completely — no feature flag, no compatibility shim.

### 4. Backend — reason passthrough (small addition)

- **Migration** `0030_add_revenue_estimate_reason.sql`: `ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_reason TEXT;` + matching entry in `schema.py`'s legacy-ALTER stub list so the test suite's `create_all()` path stays idempotent.
- **`models/game.py`:** `revenue_estimate_reason: str | None = None`.
- **`game_repo.py` `update_revenue_estimate` and `bulk_update_revenue_estimates`:** both take a `reason` value and both **enforce a symmetric data contract at the repo layer** — `method` is coerced to NULL when neither numeric field is set (existing contract), and `reason` is coerced to NULL when a numeric estimate IS present (new contract). The two coercions together guarantee a row can never carry both a real estimate *and* a stale reason code. Row tuple shape for the bulk path becomes `(appid, owners, revenue_usd, method, reason)` — a 5-tuple, not a 4-tuple.
- **`analysis_service.py` + `process_results.py` + `backfill_revenue_estimates.py`:** all three callers updated in the same commit to pass `estimate.reason` through. The tuple shape change is load-bearing for `execute_values`, so no default slot / compatibility shim — every caller moves at once.
- **`api/handler.py` report endpoint:** include `revenue_estimate_reason` in the response when non-null. Surface it **independently** of `has_revenue_estimate` — the reason is meaningful precisely when the numeric fields are NULL, so gating it on `has_revenue_estimate` would defeat its purpose.

Do NOT surface the reason on `GET /api/games` list items — that endpoint already returns too much per row, and the empty-state copy is page-level only.

### 5. Tests

**Backend:**

- `tests/repositories/test_game_repo.py` — extend the revenue-estimate tests so they pass a **stale reason alongside real numbers** and assert the repo coerces it to NULL. Add a second assertion where both numeric fields are NULL and the reason round-trips as (e.g.) `"insufficient_reviews"`. Mirror both cases in `test_bulk_update_revenue_estimates_mixed_batch`.
- `tests/test_api.py` — extend the report handler tests: when a numeric estimate is present, the response includes `estimated_owners`/`revenue`/`method` and **omits** `revenue_estimate_reason`. When the numeric fields are NULL and reason is set, the response omits the numeric keys and **includes** `revenue_estimate_reason`.
- `tests/handlers/test_batch_analysis.py` — the existing assertions unpack the row tuple shape from `bulk_update_revenue_estimates.call_args`; update both call sites to unpack 5 elements and assert `reason` is `None` when numeric values exist and `"free_to_play"` when the game is free.

**Frontend (Playwright):**

- `frontend/tests/market-reach.spec.ts` — new spec covering the three states the card can render: populated + free-tier (ranges present in the DOM but blurred and `aria-hidden`; labels + confidence pills + explainer still readable; "Unlock with Pro" CTA visible), empty + insufficient reviews ("Not enough reviews yet to estimate (N/50)." with no blur and no CTA), and empty + free-to-play (routes a specific appid with `revenue_estimate_reason: "free_to_play"` — register `mockAllApiRoutes()` **first** then the specific `**/api/games/<id>/report` override, because Playwright's route matching is LIFO).
- Add a `test.skip` placeholder for the populated + Pro variant with a `TODO(pro-gating)` — that path is unreachable via E2E until `usePro()` has a real data source.
- `frontend/tests/fixtures/api-mock.ts` — the populated-state fixture for appid 440 must be a **paid game** (`price_usd: 19.99`, `is_free: false`). Combining a numeric revenue estimate with `is_free: true` is an impossible state post-estimator and misleading as a test fixture. Omit `revenue_estimate_reason` from the populated mock entirely — the report endpoint omits it when NULL and the mock should mirror that.
- `frontend/tests/game-report.spec.ts` — the "no unlock CTAs" guardrail must be scoped: assert that any unlock-text matches are **confined to the Market Reach subtree**, not globally absent. The card is the one deliberately Pro-gated surface on this page.

Per CLAUDE.md: any frontend change that alters user-visible behaviour must include test updates in the same PR.

### 6. Analytics / instrumentation

Out of scope for this prompt, but note as a follow-up: we want a client-side event when a free user clicks the "Unlock with Pro" CTA on the Market Reach card specifically, so we can measure whether this surface is actually driving Pro conversions vs. other gated surfaces. Wire this when `pro-gating.md` ships the central CTA component.

## Non-goals

- No list-page revenue sort (separate prompt / already in backend).
- No Compare lens row (Compare is its own prompt).
- No Market Map visualization.
- No methodology page content — link target can be a stub.
- No currency localization — USD only.
- No historical revenue series.
- No refresh-on-demand button — estimates refresh on re-analysis.

## Acceptance

- Visiting `/games/{appid}/{slug}` for an **analyzed paid game with ≥50 reviews** shows the Market Reach card with owner and revenue **ranges**, ±50% confidence pills, method pill, and the one-sentence explainer.
- Visiting `/games/{appid}/{slug}` for a **crawled-but-not-yet-analyzed** game also shows the Market Reach card (populated if paid + ≥50 reviews; empty state otherwise). The card is independent of the LLM pass.
- Visiting the same page as a free user shows the card with blurred numeric ranges, visible labels and confidence pills, and an inline "Unlock with Pro" CTA below the stats grid. Labels, pills, method pill, and explainer remain fully readable.
- Visiting a free-to-play game, a DLC, or a game with <50 reviews shows the card in its empty state with reason-specific copy. No blur, no CTA.
- Playwright test covers all three states.
- No change to the existing backend estimate math. No change to matviews. No change to list-page payload shape.
