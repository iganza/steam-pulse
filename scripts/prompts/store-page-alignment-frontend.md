# Store Page Alignment Frontend — "Promise Gap" Section

## Background

SteamPulse's LLM analysis already produces a `store_page_alignment` field on every
`GameReport`. This structured data compares what a game's Steam store page promises
against what reviewers actually experience. The backend is fully functional — this
prompt is frontend-only.

The `StorePageAlignment` Pydantic model (in `analyzer_models.py`):

```python
class StorePageAlignment(BaseModel):
    promises_delivered: list[str]   # max 4 — marketing claims validated by reviews
    promises_broken: list[str]      # max 3 — claims contradicted by reviews
    hidden_strengths: list[str]     # max 3 — positives not mentioned on store page
    audience_match: Literal["aligned", "partial_mismatch", "significant_mismatch"]
    audience_match_note: str        # narrative explanation of audience alignment
```

The field is served as part of `GET /api/games/{appid}/report` inside `report_json`.
It is `null` for games analyzed before this feature existed.

### What "Promise Gap" means to users

- **Validated**: store page claimed it, reviews confirm — lean into this in marketing
- **Underdelivered**: store page claimed it, reviews disagree — fix the feature or fix the messaging
- **Hidden Strength**: reviews praise it, store page doesn't mention it — free marketing win
- **Audience Match**: does the store description target the audience that actually plays?

This is one of SteamPulse's most novel features — no competitor offers it.

---

## Goal

Add a "Promise Gap" section to the game report page (`GameReportClient.tsx`) that
renders `store_page_alignment` as a verdict table with color-coded badges, plus an
audience match callout. Free users see a teaser (first 2 rows); Pro users see everything.

No backend changes. No new API endpoints. No new pages or lenses. This is a new section
within the existing `GameReportClient.tsx` analyzed-game view.

---

## Codebase Orientation

### File Layout

- **Types**: `frontend/lib/types.ts` — `GameReport` interface (line 24), needs `StorePageAlignment` added
- **Game report client**: `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` — renders all report sections
- **Existing game components**: `frontend/components/game/` — `SectionLabel.tsx`, `ScoreBar.tsx`, `CompetitiveBenchmark.tsx`, `HiddenGemBadge.tsx`, etc.
- **Pro context**: `frontend/lib/pro.tsx` — `usePro()` hook, already called in `GameReportClient`
- **Test fixtures**: `frontend/tests/fixtures/mock-data.ts` — `MOCK_REPORT` object
- **Test spec**: `frontend/tests/game-report.spec.ts` — existing game page tests

### Existing Section Rendering Pattern

Report sections in `GameReportClient.tsx` follow this pattern:

```tsx
{report.genre_context && (
  <section>
    <SectionLabel>Genre Context</SectionLabel>
    <p className="text-base text-foreground/80 leading-relaxed">{report.genre_context}</p>
  </section>
)}
```

### Existing Pro Blur/Lock Pattern

From `CompetitiveBenchmark.tsx` and the analytics dashboard:

```tsx
<div className="relative">
  <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
    {/* gated content */}
  </div>
  {!isPro && (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
      <p className="text-sm font-mono text-foreground font-medium">Full Promise Gap Analysis</p>
      <Link href="/pro" className="text-sm font-mono px-4 py-1.5 rounded-full transition-colors"
        style={{ background: "rgba(45,185,212,0.15)", color: "var(--teal)", border: "1px solid rgba(45,185,212,0.3)" }}>
        Upgrade to Pro &rarr;
      </Link>
    </div>
  )}
</div>
```

### Existing List Rendering Pattern

From Design Strengths in `GameReportClient.tsx`:

```tsx
<li className="flex items-start gap-3">
  <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: "var(--positive)" }} />
  <span className="text-base text-foreground/80 leading-relaxed">{item}</span>
</li>
```

### Design Tokens

```css
--teal: #2db9d4;
--positive: #22c55e;    /* green — validated */
--negative: #ef4444;    /* red — underdelivered */
--gem: #c9973c;         /* amber — hidden strength */
--card: #141418;
--border: rgba(255,255,255,0.08);
```

---

## Step 1: TypeScript Types

In `frontend/lib/types.ts`, add the interface:

```typescript
export interface StorePageAlignment {
  promises_delivered: string[];
  promises_broken: string[];
  hidden_strengths: string[];
  audience_match: "aligned" | "partial_mismatch" | "significant_mismatch";
  audience_match_note: string;
}
```

Add the field to the `GameReport` interface (after `hidden_gem_score`):

```typescript
store_page_alignment?: StorePageAlignment | null;
```

---

## Step 2: Create `PromiseGap` Component

Create `frontend/components/game/PromiseGap.tsx`.

### Props

```typescript
interface PromiseGapProps {
  alignment: StorePageAlignment;
  isPro: boolean;
}
```

### Data Transformation

Combine the three lists into a single ordered array of verdict rows:

```typescript
type Verdict = "validated" | "underdelivered" | "hidden_strength";

interface PromiseRow {
  claim: string;
  verdict: Verdict;
}
```

Build in this order:
1. Each `promises_delivered` item → `{ claim, verdict: "validated" }`
2. Each `promises_broken` item → `{ claim, verdict: "underdelivered" }`
3. Each `hidden_strengths` item → `{ claim, verdict: "hidden_strength" }`

Max 10 rows total (4 + 3 + 3).

### Verdict Badge Design

| Verdict | Icon | Badge Text | Color | Background | Border |
|---|---|---|---|---|---|
| `validated` | `CheckCircle2` | VALIDATED | `var(--positive)` | `rgba(34,197,94,0.08)` | `rgba(34,197,94,0.2)` |
| `underdelivered` | `AlertTriangle` | UNDERDELIVERED | `var(--negative)` | `rgba(239,68,68,0.08)` | `rgba(239,68,68,0.15)` |
| `hidden_strength` | `Sparkles` | HIDDEN STRENGTH | `var(--gem)` | `rgba(201,151,60,0.08)` | `rgba(201,151,60,0.2)` |

Import `CheckCircle2`, `AlertTriangle`, `Sparkles` from `lucide-react`.

### Row Layout

Each row is a card-style div with icon, claim text, and verdict badge:

```tsx
<div className="p-4 rounded-xl flex items-start gap-4"
  style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
  <VerdictIcon className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: verdictColor }} />
  <div className="flex-1 min-w-0">
    <span className="text-base text-foreground/80 leading-relaxed">{row.claim}</span>
  </div>
  <span className="text-xs font-mono uppercase tracking-widest px-2 py-0.5 rounded-full flex-shrink-0"
    style={{ background: badgeBg, border: `1px solid ${badgeBorder}`, color: badgeColor }}>
    {badgeText}
  </span>
</div>
```

Rows stacked vertically with `space-y-3`.

For hidden strengths, prefix the claim display with a subtle label so users understand
these were NOT on the store page. For example, render the claim text as-is (the LLM
already frames it as a discovery, e.g., "Vibrant community-created content and modding scene").

### Responsive

On mobile (below `md`), the badge should wrap below the claim text. Use `flex-wrap` on
the row or switch to a stacked layout:

```tsx
<div className="p-4 rounded-xl flex flex-col sm:flex-row sm:items-start gap-3"
  style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)" }}>
  <div className="flex items-start gap-3 flex-1 min-w-0">
    <VerdictIcon className="w-4 h-4 mt-0.5 flex-shrink-0" style={{ color: verdictColor }} />
    <span className="text-base text-foreground/80 leading-relaxed">{row.claim}</span>
  </div>
  <VerdictBadge ... />
</div>
```

### Free vs Pro Gating

Free users see the first 2 rows at full visibility. Remaining rows are blurred:

```tsx
const FREE_VISIBLE_COUNT = 2;

{/* First 2 rows — always visible */}
<div className="space-y-3">
  {rows.slice(0, FREE_VISIBLE_COUNT).map((row, i) => (
    <PromiseRow key={i} row={row} />
  ))}
</div>

{/* Remaining rows — Pro only */}
{rows.length > FREE_VISIBLE_COUNT && (
  <div className="relative mt-3">
    <div className={isPro ? "space-y-3" : "blur-sm pointer-events-none select-none space-y-3"}>
      {rows.slice(FREE_VISIBLE_COUNT).map((row, i) => (
        <PromiseRow key={i + FREE_VISIBLE_COUNT} row={row} />
      ))}
    </div>
    {!isPro && (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <p className="text-sm font-mono text-foreground font-medium">Full Promise Gap Analysis</p>
        <Link href="/pro"
          className="text-sm font-mono px-4 py-1.5 rounded-full transition-colors"
          style={{ background: "rgba(45,185,212,0.15)", color: "var(--teal)", border: "1px solid rgba(45,185,212,0.3)" }}>
          Upgrade to Pro &rarr;
        </Link>
      </div>
    )}
  </div>
)}
```

### Audience Match Callout

Below the verdict rows, render the audience match as a separate callout card:

```tsx
<div className="mt-6 p-5 rounded-xl" style={{ background: "var(--card)", border: "1px solid var(--border)" }}>
  <div className="flex items-center gap-3 mb-2">
    <AudienceMatchBadge match={alignment.audience_match} />
    <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground">
      Audience Match
    </p>
  </div>
  {isPro ? (
    <p className="text-base text-foreground/80 leading-relaxed">
      {alignment.audience_match_note}
    </p>
  ) : (
    <p className="text-sm text-muted-foreground italic">
      Detailed audience alignment analysis available with Pro.
    </p>
  )}
</div>
```

Audience match badge values:

| Value | Display | Color |
|---|---|---|
| `aligned` | ALIGNED | `var(--positive)` green |
| `partial_mismatch` | PARTIAL MISMATCH | `var(--gem)` amber |
| `significant_mismatch` | MISMATCH | `var(--negative)` red |

Same pill styling as verdict badges.

### Null/Empty Handling

If all three lists are empty, return `null` — the section won't render. The parent
already guards with `report.store_page_alignment &&`.

Add `data-testid="promise-gap"` on the outermost wrapper div.

---

## Step 3: Integrate into GameReportClient

In `GameReportClient.tsx`:

1. Import `PromiseGap` from `@/components/game/PromiseGap`
2. Import `StorePageAlignment` type if needed (it flows through `GameReport`)
3. Add the section **after Genre Context and before Player Wishlist**. This positions
   Promise Gap right after the context/analysis sections and before the pro-oriented
   improvement sections:

```tsx
{/* Promise Gap */}
{report.store_page_alignment && (
  <section>
    <SectionLabel>Promise Gap</SectionLabel>
    <PromiseGap alignment={report.store_page_alignment} isPro={isPro} />
  </section>
)}
```

The null check ensures older reports gracefully skip the section.

---

## Step 4: Update Test Fixtures

In `frontend/tests/fixtures/mock-data.ts`, add `store_page_alignment` to `MOCK_REPORT`:

```typescript
store_page_alignment: {
  promises_delivered: [
    'Nine distinct classes provide tactical variety',
    'Free-to-play with cosmetic-only monetization',
  ],
  promises_broken: [
    'Regular content updates (last major update was years ago)',
  ],
  hidden_strengths: [
    'Vibrant community-created content and modding scene',
    'Surprisingly deep competitive meta at high ranks',
  ],
  audience_match: 'partial_mismatch' as const,
  audience_match_note:
    'Store page targets new players but the current playerbase skews heavily toward veterans. Matchmaking issues mean new players face a steep onboarding curve not mentioned in the description.',
},
```

---

## Step 5: Playwright Tests

In `frontend/tests/game-report.spec.ts`:

1. Add `promise gap` to any existing "renders all report sections" assertion array
2. Add test: Promise Gap section renders verdict rows (check for "VALIDATED" and "UNDERDELIVERED" text)
3. Add test: Audience match badge is visible
4. Add test: Section not shown for unanalyzed games
5. Add test: Section not shown when `store_page_alignment` is null (legacy report)

---

## File Summary

### New files

| File | Purpose |
|------|---------|
| `frontend/components/game/PromiseGap.tsx` | Promise Gap verdict table + audience match callout |

### Modified files

| File | Change |
|------|--------|
| `frontend/lib/types.ts` | Add `StorePageAlignment` interface, add field to `GameReport` |
| `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` | Import + render `PromiseGap` section |
| `frontend/tests/fixtures/mock-data.ts` | Add `store_page_alignment` to `MOCK_REPORT` |
| `frontend/tests/game-report.spec.ts` | Add Promise Gap test assertions |

---

## Verification

1. **Build succeeds**: `cd frontend && npm run build` — no TypeScript errors.

2. **Dev server check**:
   - Navigate to an analyzed game page (e.g., `/games/440/team-fortress-2`)
   - Promise Gap section appears between Genre Context and Player Wishlist
   - Verdict rows show with correct color-coded badges
   - First 2 rows visible, remaining blurred with Pro CTA (when not pro)
   - Audience Match badge visible, note shows only for Pro
   - Navigate to an unanalyzed game — no Promise Gap section
   - Navigate to a game with a legacy report (no `store_page_alignment`) — no section

3. **Playwright tests**: `cd frontend && npm run test:e2e` — all existing + new tests pass.
