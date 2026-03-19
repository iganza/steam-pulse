# Font Size & UI Scaling — Bump to Best Practice

## Goal

The site's font sizes skew too small for a data-rich, interaction-heavy site.
Currently 75 instances of `text-xs` (12px), 62 of `text-sm` (14px), and only 4
of `text-base` (16px). Best practice for desktop interaction-heavy pages is a
**16px default** with 13–14px for secondary/caption text. We need to bump
everything up roughly one Tailwind tier.

**This is a styling-only change. Do not modify functionality, data flow,
component APIs, or any backend code.**

---

## The Type Scale

After this change, the site should follow this scale:

| Role | Tailwind class | Size | Where |
|---|---|---|---|
| Page headings | `text-2xl` / `text-3xl` | 24–30px | Page titles, hero text |
| Section headings | `text-lg` / `text-xl` | 18–20px | Section labels, card titles |
| **Body / default** | **`text-base`** | **16px** | Descriptions, stat values, links, form inputs, nav items |
| Secondary / captions | `text-sm` | 14px | Labels on stat cards, muted hints, breadcrumbs, tag chips |
| Fine print | `text-xs` | 12px | Only for: badges, decorative mono labels, copyright |

## Rules

1. **Body text and primary content: `text-sm` → `text-base`**
   - Game descriptions (`shortDesc` in GameReportClient)
   - Stat values in Quick Stats cards (review count, release year, price, developer, velocity)
   - Navbar links (desktop and mobile menu)
   - Search input text
   - One-liner / verdict text
   - Analysis status messages
   - Any text that is the *primary content* of its section

2. **Labels and secondary text: `text-xs` → `text-sm`**
   - Stat card labels ("Reviews", "Released", "Price", "Developer", "Velocity")
   - Tag chips and genre chips
   - Breadcrumbs
   - Autocomplete dropdown items
   - Chart axis labels and tooltips
   - Score context sentence
   - "See all results" footer in autocomplete
   - Competitive benchmark labels

3. **Keep as `text-xs` (12px) — only these:**
   - Badge components (`components/ui/badge.tsx`) — leave as-is
   - Navbar brand logo text (the uppercase tracking-widest "STEAMPULSE" — this is stylistic, not for reading)
   - Copyright/footer fine print if any
   - Button `xs` variant size — leave as-is

4. **Headings should be bigger too:**
   - `GameCard` title (`h3`): `text-sm` → `text-base font-semibold`
   - Section labels (the `<SectionLabel>` component or equivalent): ensure at least `text-lg`
   - Page titles on search/genre/tag/developer pages: ensure at least `text-2xl`

5. **Input fields must be at least 16px (`text-base`)** — iOS auto-zooms inputs below 16px:
   - Desktop search input in Navbar
   - Hero search input on homepage
   - Mobile search input
   - Any other form inputs

---

## Files to Update

### High Priority (game report page — most viewed page)
- `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`
  - 30× `text-sm` → most become `text-base`
  - 13× `text-xs` → most become `text-sm`
  - Stat card values: `text-sm` → `text-base`
  - Stat card labels (the "Reviews", "Released" etc.): keep `text-xs` → `text-sm`

### Game components
- `frontend/components/game/GameCard.tsx` — title: `text-sm` → `text-base`, score: `text-xs` → `text-sm`
- `frontend/components/game/PlaytimeChart.tsx` — bucket labels, percentages, review counts
- `frontend/components/game/CompetitiveBenchmark.tsx` — benchmark labels, percentile text
- `frontend/components/game/SentimentTimeline.tsx` — axis labels, tooltip text

### Layout components
- `frontend/components/layout/Navbar.tsx` — nav links, dropdown items, search input
- `frontend/components/layout/Breadcrumbs.tsx` — `text-xs` → `text-sm`
- `frontend/components/layout/SearchAutocomplete.tsx` — dropdown items, "See all results"

### Pages
- `frontend/app/page.tsx` — hero section text
- `frontend/app/search/page.tsx` — any body text
- `frontend/app/genre/[slug]/page.tsx` — any body text
- `frontend/app/tag/[slug]/page.tsx` — any body text
- `frontend/app/developer/[slug]/page.tsx` — any body text
- `frontend/app/trending/page.tsx` — any body text
- `frontend/app/new-releases/page.tsx` — any body text
- `frontend/app/pro/page.tsx` — pricing/feature text

### UI primitives — BE CAREFUL
- `frontend/components/ui/card.tsx` — `CardDescription` uses `text-sm`, consider `text-base`
- `frontend/components/ui/button.tsx` — default variant already `text-sm`, bump to `text-base`; leave `xs` variant as `text-xs`
- `frontend/components/ui/badge.tsx` — leave at `text-xs` (badges are intentionally small)
- `frontend/components/ui/dialog.tsx` — body text `text-sm` → `text-base`

---

## Touch Targets (while you're at it)

Ensure interactive elements meet 44×44px minimum touch target (WCAG 2.1 AA):
- Tag chips: add `py-1.5 px-3` minimum (currently `py-1 px-2.5`)
- Nav links: ensure at least `py-2` on mobile
- Stat cards: already card-sized, should be fine

---

## Spacing Adjustments

When text gets larger, spacing sometimes needs a nudge to keep things balanced:
- If Quick Stats cards feel cramped after bumping values to `text-base`, add `gap-1` or `py-1` as needed
- If the game description feels tight, ensure `leading-relaxed` is on body text
- Use your judgment — the goal is readability, not pixel-perfection

---

## Verification

After making changes:
1. `cd frontend && npm run build` — must pass clean
2. Visually inspect on desktop at 1440px and 768px widths:
   - `/games/440/team-fortress-2` — primary game report
   - `/search` — game grid
   - `/genre/action` — taxonomy page
   - Homepage hero + search
3. Verify no iOS zoom: all `<input>` elements should be `text-base` (16px) or larger
4. Run `npx playwright test` — all existing tests must pass
5. Spot-check: `grep -r "text-xs" frontend/app frontend/components --include="*.tsx" | grep -v node_modules | grep -v .next | wc -l` should be ≤ 20 (down from 75)

---

## Do NOT Change

- `components/ui/badge.tsx` — badges stay at `text-xs`
- `components/ui/button.tsx` xs variant — stays at `text-xs`
- Font families — keep existing `font-mono`, `font-serif`, `font-sans` assignments
- Any backend or API code
- Colors, borders, or layout structure
