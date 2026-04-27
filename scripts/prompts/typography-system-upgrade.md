# Typography & UI presentation upgrade

## Goal

Upgrade the SteamPulse frontend type system for better cross-browser/mobile readability, performance, and consistency, without changing the dark theme, brand colors, or page layouts. Keep the editorial dual-personality (serif display + sans body) but swap to faces that render reliably at small sizes and ship as variable fonts.

## Why

- **Syne** (current body face) is a display typeface from Bonjour Monde — disproportionate weights/widths, narrow lowercase. Acceptable in headlines, painful in long-form report copy and on mobile. This is the single biggest readability hit on the site.
- **Playfair Display** is dated and overused; its Didone-style hairlines render fragile at small sizes and lower DPI.
- No variable fonts → multiple TTF requests for weights; switching is a free perf + visual-consistency win.
- No fluid type scale, no semantic type tokens, duplicated sentiment-color logic, and inline `style={{ color: "var(--teal)" }}` scattered across components even though `--color-teal` is already mapped in `@theme inline`.

## Outcomes

- Fonts: **Fraunces** (display, variable) + **Inter** (body/UI, variable) + **JetBrains Mono** (kept).
- Variable-font payload only; eliminate non-variable weight requests.
- Semantic type-scale tokens with `clamp()`-based fluid sizing.
- Reading-width caps applied to long-form report copy.
- Inline `style={{ color: "var(--teal)" }}` migrated to Tailwind utilities.
- Duplicated `getScoreColor()` consolidated into one helper.
- WCAG AA contrast verified on muted text and badges.

## Files to modify

- `frontend/app/layout.tsx` — swap font imports.
- `frontend/app/globals.css` — replace font-family vars, add type-scale + leading tokens, optionally bump `--muted-foreground`.
- `frontend/lib/styles.ts` (new) — single home for `getScoreColor` and any sentiment-color helpers.
- `frontend/components/game/ScoreBar.tsx`, `frontend/components/game/GameCard.tsx` — import shared `getScoreColor`.
- All components using inline `style={{ color: "var(--teal)" }}` — migrate to `text-teal` (already mapped via `--color-teal`). Use Grep to find them; expect Navbar, GameHero, IntelligenceCards, etc.
- Long-form report sections (game detail, genre detail) — add `max-w-prose` (~65ch) wrapper to body copy.

## Implementation steps

### 1. Replace font loading in `frontend/app/layout.tsx`

```ts
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
  axes: ["opsz", "SOFT", "WONK"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  display: "swap",
});
```

Apply `${fraunces.variable} ${inter.variable} ${jetbrains.variable}` to `<html className=...>`.

### 2. Update `frontend/app/globals.css`

Replace font variables in `@theme inline`:

```css
--font-sans: var(--font-inter);
--font-serif: var(--font-fraunces);
--font-mono: var(--font-jetbrains);
```

Add a fluid type scale and leading tokens to `@theme inline`:

```css
--text-display: clamp(2.5rem, 1.6rem + 4vw, 4.25rem);
--text-h1: clamp(2rem, 1.4rem + 2.6vw, 3rem);
--text-h2: clamp(1.5rem, 1.2rem + 1.4vw, 2.125rem);
--text-h3: clamp(1.25rem, 1.1rem + 0.8vw, 1.5rem);
--text-body: 1rem;
--text-body-sm: 0.875rem;
--text-eyebrow: 0.75rem;
--leading-display: 1.05;
--leading-tight: 1.15;
--leading-snug: 1.3;
--leading-normal: 1.55;
--leading-relaxed: 1.7;
```

Update the `h1, h2, h3, h4` block:

```css
h1, h2, h3, h4 {
  font-family: var(--font-fraunces), Georgia, "Times New Roman", serif;
  letter-spacing: -0.02em;
  line-height: var(--leading-tight);
  font-feature-settings: "ss01" 1, "kern" 1, "liga" 1;
}
h1 { font-size: var(--text-h1); }
h2 { font-size: var(--text-h2); }
h3 { font-size: var(--text-h3); }
```

Add a body baseline:

```css
body {
  font-family: var(--font-inter), -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  line-height: var(--leading-normal);
}
```

Add reusable utility classes:

```css
.text-eyebrow {
  font-family: var(--font-jetbrains), monospace;
  font-size: var(--text-eyebrow);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted-foreground);
}
.prose-readable { max-width: 65ch; }
```

Bump `--muted-foreground` from `#7c7c85` to `#9b9ba6` (improves contrast from ~4.6:1 to ~6.2:1 on `#0c0c0f`; verify with a contrast checker).

### 3. Consolidate sentiment color logic

Create `frontend/lib/styles.ts`:

```ts
export function getScoreColor(score: number): string {
  if (score >= 75) return "var(--positive)";
  if (score >= 50) return "var(--teal)";
  if (score >= 25) return "var(--gem)";
  return "var(--negative)";
}
```

Replace duplicates in `frontend/components/game/ScoreBar.tsx` and `frontend/components/game/GameCard.tsx` with imports from `@/lib/styles`. Match the existing thresholds in those files exactly — adjust the helper if they differ.

### 4. Migrate inline teal styles to Tailwind utilities

Run a grep pass:

```
Grep pattern: style=\{\{\s*color:\s*["']var\(--teal\)["']
```

For each hit, replace `style={{ color: "var(--teal)" }}` with `className="text-teal"` (or merge into existing className via `cn(...)`). Tailwind v4 already exposes `text-teal` because `--color-teal` is mapped in `@theme inline`. Same approach for any inline `background: "rgba(45,185,212,...)"` → use `bg-teal/10` etc.

Don't migrate dynamic colors (e.g., `getScoreColor(score)` returning a CSS var at runtime) — those legitimately need inline styles.

### 5. Apply reading width to long-form copy

In game-detail and genre-detail report sections (e.g., `frontend/app/games/[appid]/[slug]/page.tsx`, `frontend/app/genre/[slug]/page.tsx`), wrap report-body sections in a container with `className="prose-readable mx-auto"` (or Tailwind's `max-w-prose`). Don't apply to data tables, charts, or grid sections — only flowing prose (synthesis paragraphs, methodology, friction lists).

### 6. Apply eyebrow utility

Search for existing uppercase-mono labels and replace ad-hoc `className="font-mono uppercase text-xs tracking-widest text-muted-foreground"` patterns with `className="text-eyebrow"`. Keep behavior identical.

### 7. Cleanup

- Remove now-unused imports of `Playfair_Display` and `Syne`.
- Delete `--font-playfair` and `--font-syne` references if any remain.
- Remove the `getScoreColor` duplicates.

## Verification

1. `cd frontend && npm run build` — no type errors, build succeeds.
2. `cd frontend && npm run dev` — open `http://localhost:3000`:
   - Landing page hero — Fraunces display renders cleanly; no FOUT flash beyond `display: swap` first paint.
   - Scroll to discovery rows — body text in Inter, eyebrow labels in JetBrains Mono.
   - Visit `/games/<any-appid>/<slug>` — long-form report copy is line-length capped (~65ch); headings hierarchy is clear.
   - Visit `/genre/<slug>` — same checks; pre-order/buy block still legible.
   - Resize to 375px width — h1 scales fluidly, no horizontal scroll, body text remains readable.
   - DevTools network tab: confirm only variable font files load (one per family); no multiple weight requests.
3. Lighthouse on landing and a game-detail page — Accessibility ≥95, Performance unchanged or better.
4. Spot-check Safari, Chrome, Firefox on macOS; iOS Safari and Android Chrome on a phone.
5. Run a contrast checker on `--muted-foreground` against `--background` and `--card` — confirm ≥4.5:1 for body, ≥3:1 for large text.

## Out of scope (explicitly)

- No light-mode addition.
- No layout/grid changes.
- No new component primitives.
- No copy rewrites.
- No new dependencies (all fonts come via `next/font/google`).
