# SteamPulse Frontend Refactor — Freemium UX + Auth-Ready Architecture

## Context

SteamPulse is an AI-powered Steam game intelligence platform. This is a Next.js 15 app (App Router, TypeScript, Tailwind + custom CSS vars, vanilla no-framework UI). The game report page is the core product page.

## What needs to change

### 1. Freemium tier split (primary task)

The report page has 13 sections. The split is:

**FREE (no account, no limit, unconditional):**
1. Hero — game name, cover image, sentiment badge, hidden gem score
2. The Verdict — one_liner + sentiment score bar
3. Quick Stats — review count, release year, price, genre
4. Design Strengths — top things players love
5. Gameplay Friction — top pain points
6. Audience Profile — who this game is for, archetypes, not-for
7. Sentiment Trend — improving/stable/declining + narrative note
8. Genre Context — how the game fits its genre
13. Related Games — internal cross-links (footer)

**PRO (requires paid unlock — currently license key, future: subscription):**
9. Player Wishlist — features players are requesting
10. Churn Triggers — when/why players quit or refund
11. Developer Priorities — AI-prioritised action items with effort/impact
12. Competitive Context — how this game compares to named similar titles

Currently, Competitive Context (section 12) is outside the `PremiumUnlock` gate and only renders when `report?.competitive_context` exists. Move it inside the Pro gate alongside sections 9–11.

### 2. Realistic placeholder content in blurred Pro sections

The blurred pro sections currently show generic placeholder data. Replace with more realistic, game-industry-specific placeholder content that makes the value obvious at a glance. The user should see the *shape* of what they're buying, not a grey box.

Good placeholder example for Developer Priorities:
```
#1 Fix first-session onboarding — Players report confusion in first 15 minutes before core loop clicks. Top churn trigger. (Freq: ~35% of negative reviews | Effort: Medium)
#2 Address save system complaints — Loss of progress mentioned in 28% of negative reviews. High frustration-to-fix ratio. (Freq: High | Effort: Low)
#3 Add Steam Workshop support — Most-requested feature across 3 review chunks. (Freq: Medium | Effort: High)
```

### 3. User state architecture (build the abstraction, no auth logic yet)

The app needs to be ready for three user states without implementing auth yet:

```typescript
type UserTier = "anonymous" | "free" | "pro";
```

- `anonymous` — no account, no purchase. Current state for all users. Gets free content + license key unlock flow.
- `free` — signed in (future: account creation), not paid. Same content as anonymous for now. Reserve this tier for future: saved games, browsing history, email reports.
- `pro` — paid user. Signed-in + active subscription OR valid license key. Gets all sections unlocked.

**What to build now:**
- Create a `useUserTier()` hook in `lib/auth.ts` that currently always returns `"anonymous"` but has the interface ready to swap in real auth later.
- `PremiumUnlock` component should consume `useUserTier()` — if tier is `"pro"`, render children directly (no blur, no CTA).
- Keep the license key flow as the current path to `"pro"` state (stored in localStorage as `sp_license_key`).
- Do NOT implement actual auth, sign-in UI, or account management. Just wire the abstraction.

### 4. Remove rate limiter handling from SSR

In `app/games/[appid]/[slug]/page.tsx`, a 402 error from `/api/preview` is caught and renders the page with `preview = null`. This was a workaround for a server-side rate limiter that no longer exists. The free preview is now unconditional.

Keep the null handling as a defensive fallback (network errors happen), but remove the comment about rate limiting. The `getPreview` call in `page.tsx` should still be wrapped in try/catch for 404 (→ notFound()) and generic errors (→ throw), but 402 should no longer be a special case.

Also: remove `rate_limiter.py` from the FastAPI backend if it exists (check `src/steampulse/` or `steampulse/`). If `/preview` endpoint in `api.py` calls the rate limiter, remove that call. The `/preview` endpoint should run unconditionally.

### 5. CTA copy update

The current CTA in `PremiumUnlock` says:
> "You're a developer doing pre-launch research. Get action items, refund signals, and feature gaps your competitors haven't fixed"

Update to make it even more specific and add the Competitive Context to the value prop:
> "Get the developer layer: action items ranked by ROI, churn signals, feature gaps, and how this game stacks up against its competitors."

The "Unlock for $7" button label is fine. Keep pricing links pointing to `https://steampulse.io/#pricing`.

### 6. Inline teaser after Gameplay Friction (new)

Add a subtle inline teaser CTA *after* the Gameplay Friction section (section 5) and *before* the Audience Profile section (section 6). This should feel editorial, not salesy:

```
── [small lock icon] 8 developer action items derived from these complaints →  [Unlock $7]
```

This is a one-line inline nudge, not a full CTA block. Style it like a secondary link, not a button. Only show when Pro sections are locked (not when `userTier === "pro"`).

## Files to modify

- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — main report component
- `frontend/app/games/[appid]/[slug]/page.tsx` — SSR page, fix 402 handling
- `frontend/components/game/PremiumUnlock.tsx` — add userTier awareness
- `frontend/lib/auth.ts` — CREATE THIS FILE — `useUserTier()` hook
- `frontend/lib/types.ts` — no schema changes needed
- `src/steampulse/api.py` (or equivalent path) — remove rate_limiter call from `/preview`
- `src/steampulse/rate_limiter.py` (or equivalent) — DELETE if it exists and is only used by `/preview`

## What NOT to change

- Do not add any auth UI (sign-in, sign-up, account page)
- Do not change the license key flow — it's the current path to pro
- Do not change the report schema or types
- Do not change the visual design language (CSS vars, dark theme, font choices)
- Do not add new npm dependencies
- Do not touch genre/tag/developer page components
- Do not change the pricing ($7 single / $15 for 5)

## Current code reference

### `PremiumUnlock` flow today
- Reads `sp_license_key` from localStorage on mount, auto-validates
- On success: calls `onUnlock(report: GameReport)` which sets `fullReport` state in `GameReportClient`
- Renders children blurred when locked, unblurred when unlocked
- Children contain sections 9–11 (wishlist, churn, priorities) + placeholder data

### `GameReportClient` state today
- `fullReport: GameReport | null` — null until license key validated
- Sections use `report?.field ?? placeholderData` pattern
- `preview: PreviewResponse | null` — SSR-hydrated, may be null
- `appid: number` — from URL params, always present

### CSS vars in use
- `--teal`: accent colour
- `--gem`: hidden gem gold
- `--positive` / `--negative`: sentiment colours
- `--card`, `--border`, `--muted-foreground`: layout

## Acceptance criteria

1. `npm run build` passes with no type errors
2. Free sections render unconditionally — no auth check, no rate limit
3. Pro sections (9–12, including Competitive Context) are behind a single `PremiumUnlock` gate
4. `useUserTier()` exists in `lib/auth.ts`, returns `"anonymous"` by default, is used by `PremiumUnlock`
5. Inline teaser appears after Gameplay Friction when tier is not `"pro"`
6. Placeholder content in blurred sections looks realistic and game-specific
7. `/preview` endpoint has no rate limiter
