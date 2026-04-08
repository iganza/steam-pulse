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
  - `excluded_type` → "No estimate: DLC, demos, and tools aren't eligible."
  - `null` reason but null numbers → generic "No estimate available."
- **Pro gating:** when `isPro === false`, blur the two number ranges with a CSS blur filter (keep labels, method pill, and explainer visible) and overlay a compact "Unlock with Pro" CTA button. Do not call the `usePro()` hook yet if it doesn't exist — accept `isPro` as a prop and let the parent page pass `false` until `pro-gating.md` lands. The empty state is NOT gated — showing "not enough reviews" to free users is fine and actually reinforces trust.
- **Accessibility:** the blurred numbers must be `aria-hidden` and the CTA must be the focusable element. Screen readers should hear "Market reach estimate — unlock with Pro" not the blurred digits.

Styling: match the visual weight of existing card components in `frontend/components/game/` — look at `CompetitiveBenchmark.tsx`, `PromiseGap.tsx`, and `HiddenGemBadge.tsx` for card chrome, spacing, and typography so Market Reach feels like it belongs on the page, not bolted on.

### 3. Wire into the game page — `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`

Place the `<MarketReach />` card in the report layout. Exact position: **immediately after the sentiment / headline block and before the qualitative sections** (design strengths, friction, etc.). Rationale: it's a quantitative signal, it belongs with the other numeric signals (sentiment, hidden gem score), and putting it above the wall of narrative text means it's visible without scrolling on desktop.

If the page uses a grid, Market Reach occupies one cell the same size as `HiddenGemBadge` / sentiment — do not make it full-width.

Pass `isPro={false}` for now (hardcoded) with a `TODO(pro-gating)` comment. Free-tier behavior is the shipping default until auth lands.

### 4. Backend — reason passthrough (small addition)

- **Migration** `0030_add_revenue_estimate_reason.sql`: `ALTER TABLE games ADD COLUMN IF NOT EXISTS revenue_estimate_reason TEXT;`
- **`schema.py`:** mirror the new column.
- **`models/game.py`:** `revenue_estimate_reason: str | None = None`.
- **`game_repo.py` `bulk_update_revenue_estimates` (and the matching single-row path):** take and persist `reason`.
- **`process_results.py` + `backfill_revenue_estimates.py`:** pass `estimate.reason` through into the bulk update payload.
- **`api/handler.py` report endpoint:** include `revenue_estimate_reason` in the response when non-null (mirror the existing `has_revenue_estimate` block around line 396).
- **`scripts/backfill_revenue_estimates.py`:** extend the tuple shape — this is an additive change, so old tuples without the reason slot must keep working via a default or an explicit migration of the backfill script's payload shape in the same commit.

Do NOT surface the reason on `GET /api/games` list items — that endpoint already returns too much per row, and the empty-state copy is page-level only.

### 5. Tests

**Backend:**

- `tests/repositories/test_game_repo.py` — extend the existing revenue-estimate tests to assert `reason` round-trips through `bulk_update_revenue_estimates`.
- `tests/test_api.py` — extend the report handler test: when `reason` is set, it appears in the response; when null, it's absent.

**Frontend (Playwright):**

- `frontend/tests/` — add a game-page test that mocks the report API to return all three populated states (populated+pro, populated+free, empty+insufficient reviews) and asserts the card renders the correct copy and that the free-tier variant is blurred-and-gated. Mock data lives in `frontend/tests/fixtures/mock-data.ts` per CLAUDE.md — extend the report fixture there.

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

- Visiting `/games/{appid}/{slug}` for a game with an estimate shows the Market Reach card with owner and revenue **ranges**, ±50% confidence pills, method pill, and the one-sentence explainer.
- Visiting the same page as a free user (hardcoded for now) shows the card with blurred numbers and a visible "Unlock with Pro" CTA. Labels and explainer remain readable.
- Visiting a free-to-play game, a DLC, or a game with <50 reviews shows the card in its empty state with reason-specific copy. No blur, no CTA.
- Playwright test covers all three states.
- No change to the existing backend estimate math. No change to matviews. No change to list-page payload shape.
