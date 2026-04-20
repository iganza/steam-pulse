# Fix Quick Stats "Reviews" tile — show Steam English total, not the analyzed count

## Problem

On an analyzed game's report page (e.g. Balatro at `/games/646570/balatro`), the
**Quick Stats → Reviews** tile renders the same number twice: the main value with
a small `"en"` suffix, and a `"N analyzed"` subtitle. For Balatro both read
`1,994`. The main value should be Balatro's **total English review count from
Steam metadata** (tens of thousands), with the subtitle showing `1,994 analyzed`.

Root cause in `frontend/components/game/QuickStats.tsx:57-59`:

```tsx
const reviewsValue = totalReviewsAnalyzed ?? reviewCount;
const showEnSuffix = totalReviewsAnalyzed != null;
const showAnalyzedSuffix = reviewCount != null && totalReviewsAnalyzed != null;
```

When the game is analyzed, the main value becomes `totalReviewsAnalyzed` (our
sampled subset) and is labeled `"en"` — but the analyzed count is not the Steam
English total. The subtitle at line 92 renders `totalReviewsAnalyzed.toLocaleString()`
so both numbers match.

`review_count_english` is already available on the Game payload
(`frontend/lib/api.ts:84`, `frontend/lib/types.ts:114`) but the page collapses it
into a single `reviewCount` field via a fallback at
`frontend/app/games/[appid]/[slug]/page.tsx:146-147`, so QuickStats can't
distinguish "this is the Steam English count" from "this is the all-language
fallback".

## Fix

Split the two quantities into independent props. Don't touch the existing
`reviewCount` semantics — `MarketReach` (line 297 in `GameReportClient.tsx`) and
the JSON-LD `numberOfPlayers` field (`page.tsx:205-207`) both depend on the
English-preferred fallback.

### 1. `frontend/app/games/[appid]/[slug]/page.tsx` (~line 146)

Add a new raw English-count field on `gameData` alongside the existing
English-aligned `reviewCount`:

```tsx
// BEFORE
const englishAlignedCount = g.review_count_english ?? g.review_count;
if (englishAlignedCount != null) gameData.reviewCount = englishAlignedCount;

// AFTER
const englishAlignedCount = g.review_count_english ?? g.review_count;
if (englishAlignedCount != null) gameData.reviewCount = englishAlignedCount;
if (g.review_count_english != null) gameData.reviewCountEnglish = g.review_count_english;
```

### 2. `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`

- Add `reviewCountEnglish?: number | null;` to `GameReportClientProps` next to
  `reviewCount?: number;` (line 57).
- Destructure `reviewCountEnglish` in the component signature (around line 112).
- Pass it through to `QuickStats` at lines 276-280:

```tsx
<QuickStats
  reviewCount={reviewCount ?? null}
  reviewCountEnglish={reviewCountEnglish ?? null}
  totalReviewsAnalyzed={report?.total_reviews_analyzed ?? null}
  ...
/>
```

- Leave the `MarketReach` `reviewCount={reviewCount ?? 0}` at line 297 untouched.

### 3. `frontend/components/game/QuickStats.tsx`

Add the new prop and rewrite the tile logic.

Add to `QuickStatsProps` (around line 8-25):

```tsx
/** Steam's English-only review count from game metadata. Drives the "en"
 *  suffix in the Reviews tile and takes precedence over `reviewCount` as the
 *  main value. */
reviewCountEnglish: number | null;
```

Update JSDoc on existing props to keep semantics clear:
- `reviewCount`: all-language total, used as fallback when `reviewCountEnglish`
  is null.
- `totalReviewsAnalyzed`: reviews our pipeline actually ingested; rendered only
  as the `"N analyzed"` subtitle.

Replace lines 57-59:

```tsx
// BEFORE
const reviewsValue = totalReviewsAnalyzed ?? reviewCount;
const showEnSuffix = totalReviewsAnalyzed != null;
const showAnalyzedSuffix = reviewCount != null && totalReviewsAnalyzed != null;

// AFTER
const reviewsValue = reviewCountEnglish ?? reviewCount;
const showEnSuffix = reviewCountEnglish != null;
const showAnalyzedSuffix = totalReviewsAnalyzed != null;
```

Line 92 (`{totalReviewsAnalyzed!.toLocaleString()} analyzed`) is already correct
and does not need to change.

## Behavior matrix after the fix

| State                                | Main value          | `"en"` suffix | Subtitle         |
|--------------------------------------|---------------------|---------------|------------------|
| Analyzed, English count present      | English count       | yes           | `N analyzed`     |
| Analyzed, no English count           | All-language count  | no            | `N analyzed`     |
| Not analyzed, English count present  | English count       | yes           | —                |
| Not analyzed, no English count       | All-language count  | no            | —                |

## What NOT to change

- `gameData.reviewCount` semantics: keep as English-preferred with fallback.
  `MarketReach` and JSON-LD depend on it.
- `tests/game-no-report.spec.ts:194-198` asserts `ratingCount` uses
  `review_count_english ?? review_count`. Untouched `gameData.reviewCount`
  preserves that.
- No backend changes. The matview (`mv_catalog_reports`) is not involved —
  this is entirely on the game detail page.

## Verification

1. `cd frontend && npm run dev`, open `http://localhost:3000/games/646570/balatro`:
   - Reviews tile main value ≈ Steam's English review count for Balatro (tens of
     thousands), with a faded `en` suffix.
   - Subtitle reads `1,994 analyzed`.
2. Open an unanalyzed game (any game on `/reports?tab=coming-soon`) — tile shows
   all-language review count, no `en` suffix, no subtitle.
3. Open a game where only `review_count` exists (no English count) — tile shows
   all-language count, no `en` suffix. Subtitle still shows `N analyzed` if
   analyzed.
4. `cd frontend && npm run build` to catch missed TypeScript updates.
5. `cd frontend && npm run test` — full suite green. Pay attention to
   `tests/game-no-report.spec.ts` (JSON-LD `ratingCount`).
