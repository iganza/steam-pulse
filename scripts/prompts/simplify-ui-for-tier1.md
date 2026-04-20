# Simplify the UI for Tier 1 (catalog-only)

*Drop-in prompt for Claude Code in the SteamPulse project repo.*

*Companion to `fix-landing-page.md`. This prompt covers the rest of
the app; the landing page has its own brief.*

---

## Context

Under the Tier 1 catalog model (see `steam-pulse.org` → Active Launch
Plan and `project_business_model_2026.md`), the product is a self-serve
PDF report catalog. Everything on-site is free forever. Reports are
the only paid product. The sleep criterion governs every surface: *"if
work can't be built once and sold 1,000 times without my involvement,
it doesn't belong in this business."*

The app today still carries a substantial layer of Pro-tier plumbing
(the `usePro()` hook, `ProLockOverlay`, blur+overlay CSS, `/pro` page,
a Pro waitlist form, and the entire interactive Toolkit: Compare lens,
Builder lens, Trends lens, ExploreTable, MarketMap). It also surfaces
enthusiast feeds (`/new-releases`, `/trending`, `/compare`, `/explore`)
that don't serve the indie-dev report buyer.

None of this belongs in Tier 1. Every interactive user-facing toolkit
feature is Tier-2-gated or killed forever. Every Pro-gated on-site
section is now free. This prompt removes it all.

## Why this prompt exists

Pro-gating plumbing is dead code under the new model. Every dead
component is surface area that can break, confuse a reader, generate
a support ticket, or drift in a future refactor. Keeping dead code is
indistinguishable from keeping live code from the maintainer's
perspective — so it burns attention forever. Cut now.

The Toolkit UI was designed for a "$15–$25/mo Pro subscription" world
where a user paid for a workspace to ask their own questions. That
world was killed in the 2026-04-17 → 2026-04-19 pivot. Under the
catalog model, the conversion target is a paid PDF; interactive
toolkit workspaces actively compete with that funnel instead of
feeding it.

## Goals (measurable)

After this work:

1. **Zero Pro-gating plumbing** remains in the frontend. Grep for `usePro`, `NEXT_PUBLIC_PRO_ENABLED`, `ProLockOverlay`, `validate-key` → zero matches outside the `scripts/prompts/completed/` directory.
2. **All on-site content renders free for every visitor.** `dev_priorities`, `churn_triggers`, `player_wishlist` are visible unblurred. `AudienceOverlap` shows a single dataset size to everyone. `PromiseGap` shows all rows. `TopReviews` shows a single cap to everyone. `MarketReach` / `CompetitiveBenchmark` render without blur+overlay CTAs.
3. **Toolkit UI is deleted** — the `frontend/components/toolkit/` tree and the `/compare` + `/explore` routes it powered.
4. **Enthusiast-feed routes are deleted** — `/trending`, `/new-releases`.
5. **`/pro` route + Pro waitlist form are deleted.**
6. **Navigation is reduced to four items**: Logo · Reports · Browse · About.
7. **All obsolete tests are deleted** — Compare, Builder Lens, Market Reach gating tests, Pro waitlist tests, anything touching `usePro()`.
8. **`/api/validate-key` endpoint is deleted** in the backend Lambda.
9. **Per-game pages remain free, indexable, and SEO-healthy** — Lighthouse SEO ≥ 90 on a sample page after cleanup.
10. **Build + typecheck + test suite green** — `npm run build`, `npx tsc --noEmit`, `npm test` all pass.

## Hard deletes (delete entirely — not archive, not `_legacy`, not commented out)

### Routes (delete the whole directory under `frontend/app/`)

- `frontend/app/pro/` — Pro waitlist page + form. No Pro tier exists.
- `frontend/app/compare/` — Compare workspace. Toolkit feature; Tier 2 gated via NL chat gate or killed. Delete.
- `frontend/app/explore/` — ExploreTable / explore workspace. Toolkit feature. Delete.
- `frontend/app/trending/` — enthusiast feed. Not an indie-dev report-buyer funnel surface.
- `frontend/app/new-releases/` — enthusiast feed. Ditto.

### Components (delete the files)

- `frontend/lib/pro.tsx` — `usePro()` hook, Pro context.
- `frontend/components/toolkit/` — **delete the entire directory**. Every file:
  - `ProLockOverlay.tsx`
  - `ToolkitShell.tsx`
  - `LensTabSwitcher.tsx`
  - `LensIcon.tsx`
  - `LensRenderer.tsx`
  - `FilterBar.tsx`
  - `lenses/BuilderLens.tsx`
  - `lenses/CompareLens.tsx`
  - `lenses/TrendsLens.tsx`
  - `lenses/SentimentDrillLens.tsx`
  - `builder/ChartResolver.tsx`
  - `builder/ChartTypePicker.tsx`
  - `builder/MetricPicker.tsx`
  - `compare/CompareRadar.tsx`
  - `compare/MetricsGrid.tsx`
  - `compare/PromiseGapDiff.tsx`
  - `compare/WinsSummary.tsx`
  - `compare/GamePicker.tsx`
- `frontend/components/home/ForDevelopers.tsx` — the "For Developers →" home card. Redundant under the new positioning (the whole site is for devs).
- Any component that references `usePro()` or `ProLockOverlay` and isn't in the Simplify list below — delete.

### API endpoints (backend)

- `/api/validate-key` — stub endpoint for the killed Pro entitlement check. Delete handler + route registration.
- `/api/me/entitlement` (if it exists as a stub) — same story.
- `/api/subscribe` / `/api/subscription/*` (if stubs exist) — same.

### Env vars / config

- `NEXT_PUBLIC_PRO_ENABLED` — remove all references in code, `.env.example`, and any CDK environment block.

### Tests

- `frontend/tests/compare.spec.ts` — entire feature deleted.
- `frontend/tests/builder-lens.spec.ts` — entire feature deleted.
- `frontend/tests/market-reach.spec.ts` — Pro-gating-specific test; delete. Add a new minimal render test if MarketReach is kept on per-game pages.
- Any Playwright test that interacts with `/pro`, `/compare`, `/explore`, `/trending`, `/new-releases`, ProLockOverlay, or `usePro()`.

## Simplify (keep the file, strip the Pro gating)

### `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`

- Remove all `usePro()` calls and Pro-conditional rendering.
- `dev_priorities`, `churn_triggers`, `player_wishlist` sections render unconditionally, never blurred, never behind a CTA overlay.
- Remove any "Upgrade to Pro →" CTA buttons / `/pro` links.
- Keep everything else (sections, layout, SEO metadata).

### `frontend/components/analytics/GameAnalyticsSection.tsx`

- Remove `usePro()` / Pro-conditional fetch. API should return the same payload shape for every visitor.
- Top Reviews cap: pick **one** constant (recommend `10`) and apply to every visitor. Remove the `3 free / 10+ Pro` split.
- Remove Pro-only chart insight overlays. If an "insight" string accompanies a chart, render it to everyone.

### `frontend/components/game/MarketReach.tsx`

- Remove the blur + "Upgrade to Pro →" overlay pattern. Render full content to every visitor.
- Keep the component's data fetch + chart rendering.

### `frontend/components/game/CompetitiveBenchmark.tsx`

- Remove blur + overlay. Show percentiles to every visitor.

### `frontend/components/game/PromiseGap.tsx`

- Remove the 2-rows-free / all-rows-Pro split. Render all rows to every visitor.

### `frontend/components/analytics/AudienceOverlap.tsx`

- Remove the 5-games-free / 50-games-Pro split. Pick **one** constant — recommend `20` — and apply to every visitor. Update the API data fetch accordingly (single endpoint, single cap, no Pro branching).

### `frontend/components/layout/Navbar.tsx`

Reduce navigation to four items total:

```
Logo · Reports · Browse · About
```

- `Reports` → `/reports`
- `Browse` → the genre/tag browser surface. If a dedicated `/browse` route doesn't exist, point this at `/search` or the homepage's genre-browser anchor. Do not create a new route as part of this prompt — reuse what's there.
- `About` → `/about`. If the route doesn't exist, create a stub page with the methodology paragraph + founder bio. One page, static, no backend calls.

Remove: `Pro`, `Compare`, `Trending`, `New Releases`, `Explore`, `For Developers`, `Analytics`, any dropdown menus.

### `frontend/app/layout.tsx`

- Remove Pro context provider / `usePro` initialisation.
- Remove `NEXT_PUBLIC_PRO_ENABLED` gating of any conditional imports.
- Remove any preconnect/prefetch for `/pro` or `/api/validate-key`.

## Keep (no changes)

These are the free SEO substrate + report-funnel surfaces. Don't
touch them in this prompt:

- `frontend/app/page.tsx` — landing page. Owned by `fix-landing-page.md`.
- `frontend/app/games/[appid]/[slug]/page.tsx` — per-game page server component (routes + metadata).
- `frontend/app/genre/[slug]/page.tsx` — genre pages (free, SEO).
- `frontend/app/tag/[slug]/page.tsx` — tag pages (free, SEO).
- `frontend/app/developer/[slug]/page.tsx`, `frontend/app/publisher/[slug]/page.tsx` — SEO surfaces.
- `frontend/app/search/page.tsx` — utility.
- `frontend/app/reports/page.tsx`, `frontend/app/reports/ReportsClient.tsx` — catalog landing. Owned by `stripe-checkout-report-delivery.md`.
- All `frontend/components/game/*` components **except** those listed in "Simplify" above — they render embedded chart/data context on per-game pages and remain free.
- `frontend/components/analytics/*` components **except** those listed in "Simplify" — free-tier analytics on per-game / per-genre pages.
- `frontend/components/home/ProofBar.tsx`, `GameShowcase.tsx`, `IntelligenceCards.tsx`, `MarketTrendsPreview.tsx`, `MiniSentimentChart.tsx`, `MiniOverlapList.tsx`, `MiniTrendLine.tsx` — may be used by the landing page; the landing-page prompt will decide their fate. Don't delete here.
- `frontend/components/home/FooterCTA.tsx` — leave for the landing-page prompt to handle; it may be rewritten as a final "Read the report →" CTA.
- `frontend/components/layout/Breadcrumbs.tsx`, `HeroSearch.tsx`, `SearchAutocomplete.tsx` — utility layout components.

## Not-building (explicitly out of scope)

- **Do NOT build** `/reports/[slug]` — that's `stripe-checkout-report-delivery.md`.
- **Do NOT rewrite** `/` — that's `fix-landing-page.md`.
- **Do NOT add** a newsletter signup, Discord link, Pro waitlist, or any Tier-2-gated surface. Every one of those is in the "Killed forever" or "Gated" list per `project_business_model_2026.md`.
- **Do NOT refactor** unrelated code. Bug fixes stumbled across during cleanup should be ignored unless they would block the build.
- **Do NOT add `_legacy_` prefixes or deprecation comments.** Delete means delete.
- **Do NOT keep** routes that "might be useful for SEO later." Every KILLed route listed above has no SEO value to the report-buyer funnel; deleting simplifies the sitemap and the support surface.

## No redirects. No migration. Delete means 404.

There are no users, no external links, no search-indexed URLs, no
bookmarks, no referrals. Deleted routes return 404. Do not add Next.js
redirects. Do not add fallback pages. Do not preserve any path for
"future compatibility."

The sitemap generator is the only thing that needs touching: it must
stop emitting the deleted routes. If `frontend/public/sitemap.xml` is
static, edit it; if it's dynamic, remove the deleted routes from the
source array.

## Code guardrails

- **Delete files with `rm`**, not with empty content. An empty file is
  worse than no file — it shows up in greps.
- **Don't swap `usePro()` for `const isPro = true`.** Remove the call
  and any Pro-conditional code branches. Always-true branching leaves
  dead code and readers wondering "why is this here?"
- **Don't leave "unused" imports**: after deleting components, clean
  the import sites. `tsc --noEmit` and `eslint` will catch these.
- **Don't preserve "just in case" components** in a `_deprecated`
  folder. They are deleted from git but remain in history — retrieve
  from the git log if ever needed.
- **Voice guardrails from `fix-landing-page.md` apply here too** for
  any user-facing copy touched (About page, nav labels, empty-state
  messages). Forbidden vocabulary and preferred register are specified
  there; do not duplicate that list here.

## Verification

### Grep checks (must return zero hits outside `completed/`)

```bash
rg 'usePro\(|NEXT_PUBLIC_PRO_ENABLED|ProLockOverlay|validate-key' frontend/ --glob '!**/completed/**'
rg 'Upgrade to Pro|Pro waitlist|/pro\b' frontend/ --glob '!**/completed/**'
rg 'ToolkitShell|CompareLens|BuilderLens|TrendsLens|MarketMap|ExploreTable' frontend/ --glob '!**/completed/**'
```

All three must return no matches.

### Directory checks (must not exist)

```bash
test ! -d frontend/app/pro
test ! -d frontend/app/compare
test ! -d frontend/app/explore
test ! -d frontend/app/trending
test ! -d frontend/app/new-releases
test ! -d frontend/components/toolkit
test ! -f frontend/lib/pro.tsx
```

### Build + typecheck + test

```bash
cd frontend && npx tsc --noEmit        # no errors
cd frontend && npm run build            # clean build
cd frontend && npm test                 # remaining tests pass
```

### Manual smoke

1. Load `/` in a browser. Nav shows four items: Reports · Browse · About (plus logo). No Pro, no Compare, no Trending.
2. Load a per-game page (e.g. `/games/440/team-fortress-2`). Every section renders without blur, without "Upgrade to Pro" CTAs. `dev_priorities`, `churn_triggers`, `player_wishlist` are visible.
3. Load `/pro`, `/compare`, `/explore`, `/trending`, `/new-releases` — each returns 404. No redirect, no fallback page.
4. Run Lighthouse on a per-game page: SEO ≥ 90.

### Backend verification

```bash
rg 'validate-key|validate_key' src/lambda-functions/ --glob '!**/__pycache__/**'
```

Must return zero hits in active handler code (matches in tests ok if
they're now testing an absence / 404 — otherwise delete those tests).

## Rollout

- No users. No external traffic. No migration. Single PR, bulk deletions, direct deploy.
- No feature flag. No A/B. No gradual rollout.
- Expected PR diff: **large deletions, small additions.** If the net line count goes up, something went wrong — re-read the "delete, don't archive" guardrail.

## PR description template

```
## Summary
Remove all Pro-tier plumbing, Toolkit UI, and enthusiast-feed routes
that predate the Tier 1 catalog model. Every on-site surface is now
free. Navigation reduces to Reports · Browse · About.

## Changes
- Delete routes: /pro, /compare, /explore, /trending, /new-releases
- Delete components: frontend/lib/pro.tsx, frontend/components/toolkit/** (all),
  frontend/components/home/ForDevelopers.tsx
- Delete API endpoint: /api/validate-key
- Delete tests: compare.spec, builder-lens.spec, market-reach.spec,
  any test touching usePro/ProLockOverlay/Pro waitlist
- Simplify: GameReportClient (remove Pro gating), GameAnalyticsSection
  (single TopReviews cap), MarketReach / CompetitiveBenchmark /
  PromiseGap (remove blur+overlay), AudienceOverlap (single dataset
  size), Navbar (reduce to 4 items), layout.tsx (remove Pro provider)
- Remove env var NEXT_PUBLIC_PRO_ENABLED everywhere
- Deleted routes 404 (no redirects, no users to migrate)
- Remove deleted routes from sitemap

## Why
The Tier 1 catalog model (see steam-pulse.org + project_business_model_2026.md)
makes the funnel SEO → landing → /reports → Stripe → S3. Any UI that
doesn't serve that arrow is deleted.

## Out of scope
- Landing page rebuild (see fix-landing-page.md)
- /reports/[slug] build (see stripe-checkout-report-delivery.md)
```
