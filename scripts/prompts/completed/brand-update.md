# Brand Update: "SteamPulse: Steam Game Intelligence"

## Goal

Update all copy across the frontend to reflect the new brand tagline and drop
the word "AI" from user-facing strings. The brand is:

> **SteamPulse: Steam Game Intelligence**

"AI" reads as a buzzword and undersells the product. Replace all instances with
copy that describes the *outcome* — what the user gets — rather than the
technology used.

**This is a copy-only change. Do not modify layout, styling, component
structure, or any backend code.**

---

## Substitution Rules

| Old phrase | Replace with |
|---|---|
| `AI Game Intelligence` | `Steam Game Intelligence` |
| `AI-synthesized review reports` | `Deep review intelligence` |
| `AI-analyzed player sentiment` | `player sentiment analysis` |
| `AI-powered review analysis` | `in-depth review analysis` |
| `AI-powered analysis` | `in-depth analysis` |
| `AI-powered review intelligence` | `review intelligence` |
| `AI analysis available` | `Analysis available` |
| `freshly analyzed titles with AI-powered review intelligence` | `freshly analyzed titles with review intelligence` |
| `SteamPulse —` (em-dash separator in titles) | `SteamPulse:` (keep as colon for consistency) |

Use judgment for any other "AI" mentions not listed — replace with the plain
functional description of what it actually does.

---

## Files to Update

### `frontend/app/layout.tsx`
- Title default: `"SteamPulse: Steam Game Intelligence"`
- Description: `"Deep review intelligence for Steam games. Discover what players love, hate, and want next."`
- All OG/Twitter title/description fields that reference "AI"

### `frontend/app/page.tsx`
- Title: `"SteamPulse: Steam Game Intelligence"`
- All description strings: replace "AI-synthesized review reports for 6,000+ Steam games" with `"Review intelligence for 6,000+ Steam games — discover what players love, hate, and want next."`

### `frontend/app/search/page.tsx`
- Dynamic description with query: `Steam games matching "${q}" — player sentiment analysis and game intelligence.`
- Default description: `"Browse and search 100,000+ Steam games with in-depth review analysis."`

### `frontend/app/genre/[slug]/page.tsx`
- Description: `Browse ${name} games on Steam — player sentiment analysis, hidden gems, and review intelligence.`

### `frontend/app/tag/[slug]/page.tsx`
- Description: `Steam games tagged "${name}" — player sentiment analysis, hidden gems, and review intelligence.`

### `frontend/app/developer/[slug]/page.tsx`
- Description: `All Steam games by ${name} — player sentiment analysis across their full catalog.`

### `frontend/app/trending/page.tsx`
- Description: `"Trending Steam games — most reviewed, top rated, and hidden gems with in-depth analysis."`

### `frontend/app/new-releases/page.tsx`
- Description: `"Newly released Steam games and freshly analyzed titles with review intelligence."`

### `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`
- Line with "AI analysis available once this game reaches sufficient reviews. Check back soon."
- Replace with: `"Analysis in progress — check back once this game reaches sufficient reviews."`

---

## Also Check

Search for any other "AI" mentions in:
- `frontend/app/pro/page.tsx` — the pro page pitch copy
- `frontend/components/` — any component with marketing copy
- `frontend/app/page.tsx` — the homepage hero section JSX (not just metadata)

For the homepage hero section in `page.tsx`, if there is visible body copy
referencing "AI", update it to describe the outcome:
- "AI-powered" → "synthesized from thousands of player reviews"
- "AI reports" → "review intelligence reports"
- "AI analysis" → "analysis"

---

## Also Update the SEO Prompt File

Update `scripts/prompts/seo-foundations.md` — any remaining "AI Game Intelligence"
strings should be `"Steam Game Intelligence"`.

---

## Do NOT Change

- The word "Analysis" anywhere — that's fine and descriptive
- The word "Intelligence" — that's the brand word, keep it
- Any Python/backend code
- Any test assertions that check for the current "AI analysis available" text
  in `frontend/tests/game-report.spec.ts` line 188 — **update that test too**
  to match the new copy: `"Analysis in progress"`
- Component structure, CSS, or functionality

---

## Verification

After making changes:
1. `cd frontend && npm run build` — must pass with no errors
2. `grep -r "AI" frontend/app --include="*.tsx" --include="*.ts"` — should return
   zero results (or only legitimate technical references like `aria-*` attributes)
3. Run `npx playwright test` — the test on line 188 of `game-report.spec.ts`
   must pass with updated copy
