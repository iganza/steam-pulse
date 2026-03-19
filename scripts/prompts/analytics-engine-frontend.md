# SteamPulse Analytics Engine — Frontend Implementation

## Prerequisite

The backend API endpoints from `analytics-engine-backend.md` must be
implemented and working before starting this prompt. All 11 endpoints
should be testable via curl.

## Goal

Add 11 analytics visualizations across the game report page, genre page,
tag page, and developer page. Uses Recharts (already installed) for charts
and follows the existing component patterns.

## Codebase Orientation

### File Layout
- **API client**: `frontend/lib/api.ts` — `apiFetch<T>(path)` wrapper
- **Types**: `frontend/lib/types.ts` — TypeScript interfaces
- **Game report page**: `frontend/app/games/[appid]/[slug]/GameReportClient.tsx`
- **Genre page**: `frontend/app/genre/[slug]/page.tsx`
- **Tag page**: `frontend/app/tag/[slug]/page.tsx`
- **Developer page**: `frontend/app/developer/[slug]/page.tsx`
- **Existing charts**: `frontend/components/game/`
  - `SentimentTimeline.tsx` — Recharts area chart (weekly sentiment)
  - `PlaytimeChart.tsx` — Custom horizontal bars (playtime buckets)
  - `CompetitiveBenchmark.tsx` — Percentile ranking display
  - `ScoreBar.tsx` — Sentiment score bar (0-100)
  - `HiddenGemBadge.tsx` — Badge display

### Existing API Pattern

```typescript
// api.ts
export async function getReviewStats(appid: number): Promise<ReviewStats> {
  return apiFetch<ReviewStats>(`/api/games/${appid}/review-stats`);
}
```

### Existing Component Pattern

```tsx
// "use client" components receive typed props, handle loading internally
"use client";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export function SentimentTimeline({ timeline }: { timeline: TimelineEntry[] }) {
  if (!timeline?.length) return null;
  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <h3 className="text-lg font-semibold text-white mb-4">Sentiment Over Time</h3>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={timeline}>...</AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
```

### Design System
- Background: `bg-gray-800` for cards, `bg-gray-900` for page
- Text: `text-white` headings, `text-gray-400` secondary
- Positive: `text-green-400` / `#4ade80` / `bg-green-500`
- Negative: `text-red-400` / `#f87171` / `bg-red-500`
- Neutral: `text-yellow-400` / `#facc15`
- Cards: `rounded-lg p-6` with section headings
- Charts: `ResponsiveContainer` with `height={300}` standard

---

## Step 1: TypeScript Types

Add to `frontend/lib/types.ts`:

```typescript
// Feature 1: Audience Overlap
export interface AudienceOverlap {
  total_reviewers: number;
  overlaps: AudienceOverlapEntry[];
}

export interface AudienceOverlapEntry {
  appid: number;
  name: string;
  slug: string;
  header_image: string;
  positive_pct: number;
  review_count: number;
  overlap_count: number;
  overlap_pct: number;
  shared_sentiment_pct: number;
}

// Feature 2: Playtime Sentiment
export interface PlaytimeSentiment {
  buckets: PlaytimeSentimentBucket[];
  churn_point: ChurnPoint | null;
  median_playtime_hours: number;
  value_score: number | null;
}

export interface PlaytimeSentimentBucket {
  bucket: string;
  total: number;
  positive: number;
  negative: number;
  pct_positive: number;
}

export interface ChurnPoint {
  bucket: string;
  drop_from: number;
  drop_to: number;
  delta: number;
}

// Feature 3: Early Access Impact
export interface EarlyAccessImpact {
  has_ea_reviews: boolean;
  early_access: ReviewSegment | null;
  post_launch: ReviewSegment | null;
  impact_delta: number | null;
  verdict: "improved" | "declined" | "stable" | "no_ea";
}

export interface ReviewSegment {
  total: number;
  positive: number;
  pct_positive: number;
  avg_playtime: number;
}

// Feature 4: Review Integrity
export interface ReviewIntegrity {
  paid_reviews: ReviewIntegritySegment;
  free_key_reviews: ReviewIntegritySegment | null;
  bias_delta: number | null;
  free_key_pct: number;
  integrity_flag: "clean" | "notable" | "suspicious" | "insufficient_data";
}

export interface ReviewIntegritySegment {
  total: number;
  positive: number;
  pct_positive: number;
  avg_playtime: number;
  avg_helpfulness: number;
}

// Feature 5: Review Velocity
export interface ReviewVelocity {
  monthly: VelocityMonth[];
  summary: VelocitySummary;
}

export interface VelocityMonth {
  month: string;
  total: number;
  positive: number;
  pct_positive: number;
}

export interface VelocitySummary {
  avg_monthly: number;
  last_30_days: number;
  last_3_months_avg: number;
  peak_month: { month: string; total: number };
  trend: "accelerating" | "stable" | "decelerating";
}

// Feature 6: Top Reviews
export interface TopReviewsResponse {
  sort: string;
  reviews: TopReview[];
}

export interface TopReview {
  steam_review_id: string;
  voted_up: boolean;
  playtime_hours: number;
  body_preview: string;
  votes_helpful: number;
  votes_funny: number;
  posted_at: string;
  written_during_early_access: boolean;
  received_for_free: boolean;
}

// Feature 7: Price Positioning
export interface PricePositioning {
  genre: string;
  genre_slug: string;
  distribution: PriceRange[];
  summary: PriceSummary;
}

export interface PriceRange {
  price_range: string;
  game_count: number;
  avg_sentiment: number;
  median_price: number;
}

export interface PriceSummary {
  avg_price: number;
  median_price: number;
  free_count: number;
  paid_count: number;
  sweet_spot: string;
}

// Feature 8: Release Timing
export interface ReleaseTiming {
  genre: string;
  monthly: ReleaseMonth[];
  best_month: MonthHighlight;
  worst_month: MonthHighlight;
  quietest_month: MonthHighlight;
  busiest_month: MonthHighlight;
}

export interface ReleaseMonth {
  month: number;
  month_name: string;
  releases: number;
  avg_sentiment: number;
  avg_reviews: number;
}

export interface MonthHighlight {
  month: number;
  month_name: string;
  releases?: number;
  avg_sentiment?: number;
}

// Feature 9: Platform Gaps
export interface PlatformGaps {
  genre: string;
  total_games: number;
  platforms: {
    windows: PlatformStats;
    mac: PlatformStats;
    linux: PlatformStats;
  };
  underserved: string;
}

export interface PlatformStats {
  count: number;
  pct: number;
  avg_sentiment: number;
}

// Feature 10: Tag Trend
export interface TagTrend {
  tag: string;
  tag_slug: string;
  yearly: TagYear[];
  growth_rate: number;
  peak_year: number;
  total_games: number;
}

export interface TagYear {
  year: number;
  game_count: number;
  avg_sentiment: number;
}

// Feature 11: Developer Portfolio
export interface DeveloperPortfolio {
  developer: string;
  developer_slug: string;
  summary: DeveloperSummary;
  games: DeveloperGame[];
}

export interface DeveloperSummary {
  total_games: number;
  total_reviews: number;
  avg_sentiment: number;
  first_release: string;
  latest_release: string;
  avg_price: number | null;
  free_games: number;
  well_received: number;
  poorly_received: number;
  sentiment_trajectory: "improving" | "stable" | "declining" | "single_title";
}

export interface DeveloperGame {
  appid: number;
  name: string;
  slug: string;
  header_image: string;
  release_date: string;
  price_usd: number | null;
  is_free: boolean;
  review_count: number;
  positive_pct: number;
  review_score_desc: string;
  metacritic_score: number | null;
  achievements_total: number | null;
}
```

---

## Step 2: API Client Functions

Add to `frontend/lib/api.ts`:

```typescript
// Per-game analytics
export async function getAudienceOverlap(appid: number, limit = 20): Promise<AudienceOverlap> {
  return apiFetch<AudienceOverlap>(`/api/games/${appid}/audience-overlap?limit=${limit}`);
}

export async function getPlaytimeSentiment(appid: number): Promise<PlaytimeSentiment> {
  return apiFetch<PlaytimeSentiment>(`/api/games/${appid}/playtime-sentiment`);
}

export async function getEarlyAccessImpact(appid: number): Promise<EarlyAccessImpact> {
  return apiFetch<EarlyAccessImpact>(`/api/games/${appid}/early-access-impact`);
}

export async function getReviewIntegrity(appid: number): Promise<ReviewIntegrity> {
  return apiFetch<ReviewIntegrity>(`/api/games/${appid}/review-integrity`);
}

export async function getReviewVelocity(appid: number): Promise<ReviewVelocity> {
  return apiFetch<ReviewVelocity>(`/api/games/${appid}/review-velocity`);
}

export async function getTopReviews(
  appid: number, sort: "helpful" | "funny" = "helpful", limit = 10
): Promise<TopReviewsResponse> {
  return apiFetch<TopReviewsResponse>(
    `/api/games/${appid}/top-reviews?sort=${sort}&limit=${limit}`
  );
}

// Market analytics
export async function getPricePositioning(genre: string): Promise<PricePositioning> {
  return apiFetch<PricePositioning>(`/api/analytics/price-positioning?genre=${genre}`);
}

export async function getReleaseTiming(genre: string): Promise<ReleaseTiming> {
  return apiFetch<ReleaseTiming>(`/api/analytics/release-timing?genre=${genre}`);
}

export async function getPlatformGaps(genre: string): Promise<PlatformGaps> {
  return apiFetch<PlatformGaps>(`/api/analytics/platform-gaps?genre=${genre}`);
}

export async function getTagTrend(slug: string): Promise<TagTrend> {
  return apiFetch<TagTrend>(`/api/tags/${slug}/trend`);
}

export async function getDeveloperAnalytics(slug: string): Promise<DeveloperPortfolio> {
  return apiFetch<DeveloperPortfolio>(`/api/developers/${slug}/analytics`);
}
```

---

## Step 3: New Components

Create all in `frontend/components/analytics/`. Each is a "use client"
component that receives typed props and renders a self-contained card.

### 3a. AudienceOverlap.tsx

**Props:** `{ data: AudienceOverlap; gameName: string }`

Display a ranked list of games with the most shared reviewers. Each row shows:
- Game header image (small thumbnail, 60x28px)
- Game name (linked to `/games/{appid}/{slug}`)
- Overlap bar (visual, proportional to max overlap_pct)
- `overlap_count` shared players, `overlap_pct`% overlap
- `shared_sentiment_pct`% — small colored indicator showing if shared players
  liked the other game (green ≥70, yellow 50-70, red <50)

**Layout:** Vertical list within a `bg-gray-800 rounded-lg p-6` card.
Header: "🎮 Audience Overlap — Players who reviewed {gameName} also reviewed..."
Show total_reviewers as subtext: "Based on {n} unique reviewers"

**Free tier:** Show top 5 with a "See all {n} games →" CTA for Pro.
Implement this as a `showAll` boolean prop defaulting to false. When false,
slice to 5 items and show the CTA.

### 3b. PlaytimeSentimentChart.tsx

**Props:** `{ data: PlaytimeSentiment }`

A **combo chart** (Recharts ComposedChart):
- X axis: playtime buckets
- Left Y axis: review count (bars, gray)
- Right Y axis: sentiment % (line, gradient green→red)
- If `churn_point` exists, draw a vertical annotation line at that bucket
  with a label: "⚠️ Churn wall: sentiment drops {delta}% at {bucket}"

Below the chart, show stat cards:
- Median Playtime: `{median_playtime_hours}h`
- Value Score: `{value_score} hrs/$` (or "Free" if null)

**Design note:** The churn wall annotation is the key insight — make it
visually prominent (dashed red line + label).

### 3c. EarlyAccessImpact.tsx

**Props:** `{ data: EarlyAccessImpact }`

If `verdict === "no_ea"`, render nothing (return null).

Otherwise, show a **side-by-side comparison card**:
- Left column: "Early Access" — total reviews, pct_positive (with ScoreBar),
  avg_playtime
- Right column: "Post-Launch" — same stats
- Center: Arrow with delta and verdict badge
  - "improved" → green arrow up, "📈 +{delta}%"
  - "declined" → red arrow down, "📉 {delta}%"
  - "stable" → gray dash, "➡️ Stable"

Color the verdict badge: green for improved, red for declined, gray for stable.

### 3d. ReviewIntegrity.tsx

**Props:** `{ data: ReviewIntegrity }`

If `integrity_flag === "insufficient_data"`, render nothing.

Otherwise, show a **comparison card** similar to EarlyAccessImpact:
- Left: "Paid Reviews" — count, sentiment, avg playtime, avg helpfulness
- Right: "Free Key Reviews" — same metrics
- Badge in header:
  - `"clean"` → green badge "✅ Review Integrity: Clean"
  - `"notable"` → yellow badge "⚠️ Free Key Bias: Notable (+{delta}%)"
  - `"suspicious"` → red badge "🚩 Free Key Bias: Suspicious (+{delta}%)"

Additional context line: "{free_key_pct}% of reviews are from free keys"

### 3e. ReviewVelocityChart.tsx

**Props:** `{ data: ReviewVelocity }`

A **Recharts AreaChart** showing monthly review volume:
- X axis: months (formatted "Jan '24")
- Y axis: total reviews per month
- Area fill: gradient blue
- Horizontal reference line at avg_monthly (dashed, with label)

Below the chart, show summary stats in a row:
- Trend badge: "🚀 Accelerating" (green), "📊 Stable" (gray),
  "📉 Decelerating" (red)
- Last 30 days: {n} reviews
- Monthly avg: {n}
- Peak: {month} ({n} reviews)

### 3f. TopReviews.tsx

**Props:** `{ data: TopReviewsResponse }`

A list of review cards. Each card shows:
- 👍/👎 icon (voted_up)
- body_preview text (max 3 lines, truncated with "...")
- Stats row: `⏱ {playtime_hours}h played` · `👍 {votes_helpful} helpful` ·
  `😄 {votes_funny} funny`
- Badge row: if written_during_early_access → "Early Access" badge;
  if received_for_free → "Free Key" badge
- Posted date

Add a toggle at top: "Most Helpful" / "Most Funny" (switches the `sort`
prop — parent component should handle refetching).

### 3g. PricePositioning.tsx

**Props:** `{ data: PricePositioning }`

A **Recharts ComposedChart**:
- X axis: price ranges
- Left Y axis: game count (bars, blue)
- Right Y axis: avg sentiment (line, green)
- Highlight the sweet_spot bar with a different color (gold/amber)

Summary cards below:
- "💰 Sweet Spot: {sweet_spot}" (highlighted)
- "Avg Price: ${avg_price}" · "Median: ${median_price}"
- "{free_count} free games, {paid_count} paid"

### 3h. ReleaseTiming.tsx

**Props:** `{ data: ReleaseTiming }`

A **Recharts ComposedChart** showing 12 months:
- X axis: month names (Jan–Dec)
- Left Y axis: releases count (bars, blue-gray)
- Right Y axis: avg sentiment (line, green)

Highlight callouts below:
- "🏆 Best month to launch: {best_month.month_name} ({avg_sentiment}% avg)"
- "⚠️ Most competitive: {busiest_month.month_name} ({releases} releases)"
- "🎯 Least competition: {quietest_month.month_name} ({releases} releases)"

### 3i. PlatformGaps.tsx

**Props:** `{ data: PlatformGaps }`

Three **horizontal progress bars** showing platform support:
- Windows: {pct}% (always nearly 100%)
- macOS: {pct}%
- Linux: {pct}%

Each bar shows `{count}/{total_games} games` and `{avg_sentiment}% avg sentiment`.

Highlight the underserved platform with a "🔵 Opportunity" badge:
"Only {pct}% of {genre} games support {platform} — those that do average
{avg_sentiment}% positive reviews"

### 3j. TagTrendChart.tsx

**Props:** `{ data: TagTrend }`

A **Recharts ComposedChart** by year:
- X axis: years (2015–present)
- Left Y axis: game count (bars, gradient purple)
- Right Y axis: avg sentiment (line, green)

Stats below:
- "📈 Growth rate: {growth_rate * 100}% since 2015"
- "Peak year: {peak_year}"
- "Total games: {total_games}"

### 3k. DeveloperPortfolio.tsx

**Props:** `{ data: DeveloperPortfolio }`

**Summary section** (stat cards in a row):
- Total Games: {total_games}
- Total Reviews: {total_reviews} (formatted: "2.5M")
- Avg Sentiment: {avg_sentiment}% (with color)
- Trajectory: badge (improving/stable/declining with icons)

**Games table/grid**: Cards for each game showing:
- header_image
- name (linked to game page)
- release_date, price
- review_count, positive_pct (with small ScoreBar)
- Sorted by release_date DESC (newest first)

**Sentiment timeline**: If developer has 3+ games, show a simple line chart
with release_date on X axis, positive_pct on Y axis, game names as labels.
This visualizes the developer's quality trajectory.

---

## Step 4: Page Integration

### Game Report Page (`GameReportClient.tsx`)

Add an "Analytics" section below the existing report content. Fetch all
per-game analytics in parallel when the page loads:

```typescript
const [overlap, playtime, eaImpact, integrity, velocity, topReviews] =
  await Promise.all([
    getAudienceOverlap(appid),
    getPlaytimeSentiment(appid),
    getEarlyAccessImpact(appid),
    getReviewIntegrity(appid),
    getReviewVelocity(appid),
    getTopReviews(appid),
  ]);
```

**Layout order** within the Analytics section:
1. PlaytimeSentimentChart (always show — replaces or supplements existing
   PlaytimeChart. Keep the existing PlaytimeChart as-is; add the new one
   as a separate "Deep Dive" section below it)
2. ReviewVelocityChart
3. EarlyAccessImpact (only renders if game has EA reviews)
4. ReviewIntegrity (only renders if flag is not insufficient_data)
5. TopReviews
6. AudienceOverlap (the showcase feature — last so user scrolls through
   other insights first)

Each component is wrapped in error boundaries that return null on failure
(fetch errors should not break the page).

### Genre Page (`genre/[slug]/page.tsx`)

Add a "Market Intelligence" section. Fetch:

```typescript
const [pricing, timing, platforms] = await Promise.all([
  getPricePositioning(slug),
  getReleaseTiming(slug),
  getPlatformGaps(slug),
]);
```

**Layout order:**
1. PricePositioning
2. ReleaseTiming
3. PlatformGaps

### Tag Page (`tag/[slug]/page.tsx`)

Add a "Tag Trends" section with TagTrendChart:

```typescript
const trend = await getTagTrend(slug);
```

### Developer Page (`developer/[slug]/page.tsx`)

Replace or enhance the existing developer content with the full
DeveloperPortfolio component:

```typescript
const portfolio = await getDeveloperAnalytics(slug);
```

---

## Step 5: Pro Gating (UI Only)

For v1, implement a visual gate — no actual authentication. Create a
reusable wrapper component:

### ProGate.tsx (`frontend/components/ProGate.tsx`)

```tsx
"use client";

export function ProGate({
  children,
  feature,
  teaser,
}: {
  children: React.ReactNode;
  feature: string;
  teaser?: React.ReactNode;
}) {
  // For v1: always show full content (no actual gating)
  // When pro auth is added later, check auth state here
  const isPro = true; // TODO: replace with actual auth check

  if (isPro) return <>{children}</>;

  return (
    <div className="relative">
      {teaser && <div>{teaser}</div>}
      <div className="relative overflow-hidden rounded-lg" style={{ maxHeight: 200 }}>
        <div className="blur-sm pointer-events-none">{children}</div>
        <div className="absolute inset-0 flex items-center justify-center
                        bg-gradient-to-t from-gray-900 via-gray-900/80 to-transparent">
          <div className="text-center p-6">
            <p className="text-lg font-semibold text-white mb-2">
              🔒 {feature}
            </p>
            <p className="text-gray-400 mb-4">
              Unlock detailed analytics with SteamPulse Pro
            </p>
            <a href="/pro" className="bg-blue-600 hover:bg-blue-700 text-white
                                      px-6 py-2 rounded-lg font-medium">
              Learn More
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
```

### Which features are pro-gated:

| Feature | Free | Pro |
|---------|------|-----|
| Audience Overlap | Top 5 (teaser) | Full list (50+) |
| Playtime Sentiment | Basic (existing chart) | Fine-grained + churn wall |
| Early Access Impact | ❌ | ✅ |
| Review Integrity | ❌ | ✅ |
| Review Velocity | Basic (existing stats) | Full monthly chart + trend |
| Top Reviews | Top 3 | Top 10+ |
| Price Positioning | ❌ | ✅ |
| Release Timing | ❌ | ✅ |
| Platform Gaps | ✅ (simple) | ✅ (full) |
| Tag Trends | ✅ | ✅ |
| Developer Portfolio | Basic (game list) | Full stats + trajectory |

For v1: set `isPro = true` so everything renders. When auth is added,
wrap pro features in `<ProGate feature="...">`.

---

## Step 6: Loading States

Each analytics component should handle its own loading state. Use a
consistent skeleton pattern:

```tsx
function AnalyticsSkeleton({ height = 300 }: { height?: number }) {
  return (
    <div className="bg-gray-800 rounded-lg p-6 animate-pulse">
      <div className="h-5 bg-gray-700 rounded w-1/3 mb-4" />
      <div className="bg-gray-700 rounded" style={{ height }} />
    </div>
  );
}
```

In the page component, use React Suspense or conditional rendering:
- Show skeleton while data is loading
- Show nothing (return null) if the endpoint returns empty/error data
- Never show an error message to the user for analytics — degrade gracefully

---

## Step 7: Playwright Tests

### Test Infrastructure (already exists — follow these patterns)

- **Test files**: `frontend/tests/*.spec.ts`
- **API mocking**: `frontend/tests/fixtures/api-mock.ts` — `mockAllApiRoutes(page)`
  registers `page.route()` handlers for all API endpoints
- **Mock data**: `frontend/tests/fixtures/mock-data.ts` — exported constants
  for each API response shape
- **Pattern**: Each test calls `mockAllApiRoutes(page)` in `beforeEach`,
  navigates to a page, and asserts visibility of elements

### Update mock-data.ts

Add mock response constants for all 11 new analytics endpoints:

```typescript
// Feature 1: Audience Overlap
export const MOCK_AUDIENCE_OVERLAP = {
  total_reviewers: 5432,
  overlaps: [
    {
      appid: 570, name: "Dota 2", slug: "dota-2-570",
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/570/header.jpg",
      positive_pct: 82, review_count: 1800000,
      overlap_count: 342, overlap_pct: 6.3, shared_sentiment_pct: 78.5,
    },
    {
      appid: 730, name: "Counter-Strike 2", slug: "counter-strike-2-730",
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg",
      positive_pct: 85, review_count: 8500000,
      overlap_count: 289, overlap_pct: 5.3, shared_sentiment_pct: 71.2,
    },
    {
      appid: 730, name: "Half-Life 2", slug: "half-life-2-220",
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/220/header.jpg",
      positive_pct: 97, review_count: 180000,
      overlap_count: 156, overlap_pct: 2.9, shared_sentiment_pct: 95.1,
    },
  ],
};

// Feature 2: Playtime Sentiment
export const MOCK_PLAYTIME_SENTIMENT = {
  buckets: [
    { bucket: "0h", total: 50, positive: 20, negative: 30, pct_positive: 40.0 },
    { bucket: "<1h", total: 120, positive: 60, negative: 60, pct_positive: 50.0 },
    { bucket: "1-2h", total: 200, positive: 140, negative: 60, pct_positive: 70.0 },
    { bucket: "2-5h", total: 300, positive: 240, negative: 60, pct_positive: 80.0 },
    { bucket: "5-10h", total: 250, positive: 210, negative: 40, pct_positive: 84.0 },
    { bucket: "10-20h", total: 180, positive: 135, negative: 45, pct_positive: 75.0 },
    { bucket: "20-50h", total: 100, positive: 60, negative: 40, pct_positive: 60.0 },
  ],
  churn_point: { bucket: "20-50h", drop_from: 75.0, drop_to: 60.0, delta: -15.0 },
  median_playtime_hours: 8,
  value_score: 1.6,
};

// Feature 3: Early Access Impact
export const MOCK_EA_IMPACT = {
  has_ea_reviews: true,
  early_access: { total: 500, positive: 360, pct_positive: 72.0, avg_playtime: 8.5 },
  post_launch: { total: 1200, positive: 1020, pct_positive: 85.0, avg_playtime: 24.3 },
  impact_delta: 13.0,
  verdict: "improved" as const,
};

// Feature 4: Review Integrity
export const MOCK_REVIEW_INTEGRITY = {
  paid_reviews: { total: 1000, positive: 780, pct_positive: 78.0, avg_playtime: 22.5, avg_helpfulness: 2.1 },
  free_key_reviews: { total: 50, positive: 48, pct_positive: 96.0, avg_playtime: 3.2, avg_helpfulness: 0.5 },
  bias_delta: 18.0,
  free_key_pct: 4.8,
  integrity_flag: "notable" as const,
};

// Feature 5: Review Velocity
export const MOCK_REVIEW_VELOCITY = {
  monthly: [
    { month: "2025-01", total: 85, positive: 68, pct_positive: 80.0 },
    { month: "2025-02", total: 92, positive: 76, pct_positive: 82.6 },
    { month: "2025-03", total: 110, positive: 88, pct_positive: 80.0 },
  ],
  summary: {
    avg_monthly: 85.5,
    last_30_days: 110,
    last_3_months_avg: 95.7,
    peak_month: { month: "2025-03", total: 110 },
    trend: "accelerating" as const,
  },
};

// Feature 6: Top Reviews
export const MOCK_TOP_REVIEWS = {
  sort: "helpful",
  reviews: [
    {
      steam_review_id: "170501_440", voted_up: true, playtime_hours: 450,
      body_preview: "This game is an absolute masterpiece that changed how I think about multiplayer...",
      votes_helpful: 1523, votes_funny: 42,
      posted_at: "2024-01-15T12:00:00Z",
      written_during_early_access: false, received_for_free: false,
    },
    {
      steam_review_id: "170502_440", voted_up: false, playtime_hours: 2,
      body_preview: "Constant crashes on startup. Refunded after 30 minutes of troubleshooting.",
      votes_helpful: 892, votes_funny: 5,
      posted_at: "2024-02-20T15:30:00Z",
      written_during_early_access: false, received_for_free: false,
    },
  ],
};

// Feature 7: Price Positioning
export const MOCK_PRICE_POSITIONING = {
  genre: "Action",
  genre_slug: "action",
  distribution: [
    { price_range: "Free", game_count: 45, avg_sentiment: 72.3, median_price: 0 },
    { price_range: "$5-10", game_count: 120, avg_sentiment: 68.5, median_price: 7.99 },
    { price_range: "$10-15", game_count: 95, avg_sentiment: 78.2, median_price: 12.99 },
    { price_range: "$15-20", game_count: 68, avg_sentiment: 74.1, median_price: 17.49 },
    { price_range: "$20-30", game_count: 42, avg_sentiment: 71.8, median_price: 24.99 },
  ],
  summary: {
    avg_price: 14.99, median_price: 9.99,
    free_count: 45, paid_count: 325, sweet_spot: "$10-15",
  },
};

// Feature 8: Release Timing
export const MOCK_RELEASE_TIMING = {
  genre: "Action",
  monthly: [
    { month: 1, month_name: "January", releases: 28, avg_sentiment: 74.2, avg_reviews: 320 },
    { month: 2, month_name: "February", releases: 35, avg_sentiment: 78.3, avg_reviews: 410 },
    { month: 3, month_name: "March", releases: 42, avg_sentiment: 72.1, avg_reviews: 350 },
    // ... (include all 12 months for realistic mock)
  ],
  best_month: { month: 2, month_name: "February", avg_sentiment: 78.3 },
  worst_month: { month: 11, month_name: "November", avg_sentiment: 64.2 },
  quietest_month: { month: 1, month_name: "January", releases: 28 },
  busiest_month: { month: 10, month_name: "October", releases: 85 },
};

// Feature 9: Platform Gaps
export const MOCK_PLATFORM_GAPS = {
  genre: "Action",
  total_games: 500,
  platforms: {
    windows: { count: 498, pct: 99.6, avg_sentiment: 71.2 },
    mac: { count: 175, pct: 35.0, avg_sentiment: 73.5 },
    linux: { count: 110, pct: 22.0, avg_sentiment: 75.1 },
  },
  underserved: "linux",
};

// Feature 10: Tag Trend
export const MOCK_TAG_TREND = {
  tag: "Roguelike", tag_slug: "roguelike",
  yearly: [
    { year: 2018, game_count: 45, avg_sentiment: 71.2 },
    { year: 2019, game_count: 62, avg_sentiment: 69.8 },
    { year: 2020, game_count: 78, avg_sentiment: 73.5 },
    { year: 2021, game_count: 95, avg_sentiment: 74.1 },
    { year: 2022, game_count: 110, avg_sentiment: 72.8 },
    { year: 2023, game_count: 130, avg_sentiment: 75.2 },
  ],
  growth_rate: 1.89, peak_year: 2023, total_games: 520,
};

// Feature 11: Developer Portfolio
export const MOCK_DEVELOPER_PORTFOLIO = {
  developer: "Valve", developer_slug: "valve",
  summary: {
    total_games: 3, total_reviews: 10500000, avg_sentiment: 88.5,
    first_release: "2004-11-16", latest_release: "2023-09-27",
    avg_price: 9.99, free_games: 2, well_received: 3, poorly_received: 0,
    sentiment_trajectory: "stable" as const,
  },
  games: [
    {
      appid: 730, name: "Counter-Strike 2", slug: "counter-strike-2-730",
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg",
      release_date: "2023-09-27", price_usd: null, is_free: true,
      review_count: 8500000, positive_pct: 82, review_score_desc: "Very Positive",
      metacritic_score: null, achievements_total: 168,
    },
  ],
};

// Empty/edge-case variants for degradation tests
export const MOCK_EA_IMPACT_NO_EA = {
  has_ea_reviews: false,
  early_access: null, post_launch: { total: 100, positive: 80, pct_positive: 80.0, avg_playtime: 15.0 },
  impact_delta: null, verdict: "no_ea" as const,
};

export const MOCK_INTEGRITY_INSUFFICIENT = {
  paid_reviews: { total: 5, positive: 4, pct_positive: 80.0, avg_playtime: 10.0, avg_helpfulness: 1.0 },
  free_key_reviews: null,
  bias_delta: null, free_key_pct: 0, integrity_flag: "insufficient_data" as const,
};

export const MOCK_PLAYTIME_SENTIMENT_NO_CHURN = {
  buckets: [
    { bucket: "0h", total: 50, positive: 40, negative: 10, pct_positive: 80.0 },
    { bucket: "<1h", total: 120, positive: 100, negative: 20, pct_positive: 83.3 },
  ],
  churn_point: null,
  median_playtime_hours: 5,
  value_score: null,
};
```

### Update api-mock.ts

Add route handlers for all 11 new endpoints inside `mockAllApiRoutes()`:

```typescript
// Per-game analytics — register BEFORE the wildcard /api/games** route
await page.route('**/api/games/*/audience-overlap*', route =>
  route.fulfill({ json: MOCK_AUDIENCE_OVERLAP })
);
await page.route('**/api/games/*/playtime-sentiment', route =>
  route.fulfill({ json: MOCK_PLAYTIME_SENTIMENT })
);
await page.route('**/api/games/*/early-access-impact', route =>
  route.fulfill({ json: MOCK_EA_IMPACT })
);
await page.route('**/api/games/*/review-integrity', route =>
  route.fulfill({ json: MOCK_REVIEW_INTEGRITY })
);
await page.route('**/api/games/*/review-velocity', route =>
  route.fulfill({ json: MOCK_REVIEW_VELOCITY })
);
await page.route('**/api/games/*/top-reviews*', route =>
  route.fulfill({ json: MOCK_TOP_REVIEWS })
);

// Market analytics
await page.route('**/api/analytics/price-positioning*', route =>
  route.fulfill({ json: MOCK_PRICE_POSITIONING })
);
await page.route('**/api/analytics/release-timing*', route =>
  route.fulfill({ json: MOCK_RELEASE_TIMING })
);
await page.route('**/api/analytics/platform-gaps*', route =>
  route.fulfill({ json: MOCK_PLATFORM_GAPS })
);
await page.route('**/api/tags/*/trend', route =>
  route.fulfill({ json: MOCK_TAG_TREND })
);
await page.route('**/api/developers/*/analytics', route =>
  route.fulfill({ json: MOCK_DEVELOPER_PORTFOLIO })
);
```

**Important:** Register these BEFORE the wildcard `**/api/games**` catch-all
route. Playwright uses LIFO (last registered wins for the same URL), so
specific routes must be registered after generic ones. Since the existing
code registers wildcards first and specifics last, put the new per-game
routes after the existing specific routes (e.g., after the
`**/api/games/440/report` route).

### New test file: frontend/tests/analytics.spec.ts

Create a dedicated test file for all analytics features.

```typescript
import { test, expect } from '@playwright/test';
import { mockAllApiRoutes } from './fixtures/api-mock';
import {
  MOCK_EA_IMPACT_NO_EA,
  MOCK_INTEGRITY_INSUFFICIENT,
  MOCK_PLAYTIME_SENTIMENT_NO_CHURN,
} from './fixtures/mock-data';

// ──────────────────────────────────────────────
// Game Report Page — Analytics Section
// ──────────────────────────────────────────────

test.describe('Game report — analytics features', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto('/games/440/team-fortress-2');
  });

  // Feature 1: Audience Overlap
  test('audience overlap section renders with game names', async ({ page }) => {
    await expect(page.getByText(/audience overlap/i)).toBeVisible();
    await expect(page.getByText('Dota 2')).toBeVisible();
    await expect(page.getByText('Counter-Strike 2')).toBeVisible();
  });

  test('audience overlap shows overlap percentages', async ({ page }) => {
    await expect(page.getByText(/6\.3%/)).toBeVisible();
  });

  test('audience overlap game links navigate to game pages', async ({ page }) => {
    const link = page.getByRole('link', { name: /dota 2/i }).first();
    await expect(link).toHaveAttribute('href', /\/games\/570\//);
  });

  // Feature 2: Playtime Sentiment
  test('playtime sentiment chart renders', async ({ page }) => {
    await expect(page.getByText(/playtime.*sentiment|sentiment.*playtime/i)).toBeVisible();
  });

  test('churn wall annotation is visible when present', async ({ page }) => {
    await expect(page.getByText(/churn/i)).toBeVisible();
  });

  test('no churn annotation when churn_point is null', async ({ page }) => {
    await page.route('**/api/games/*/playtime-sentiment', route =>
      route.fulfill({ json: MOCK_PLAYTIME_SENTIMENT_NO_CHURN })
    );
    await page.goto('/games/440/team-fortress-2');
    // Chart should render but no churn annotation
    await expect(page.getByText(/churn/i)).not.toBeVisible();
  });

  test('median playtime and value score stats shown', async ({ page }) => {
    await expect(page.getByText(/median/i)).toBeVisible();
    await expect(page.getByText(/value/i)).toBeVisible();
  });

  // Feature 3: Early Access Impact
  test('early access impact shows comparison when EA data exists', async ({ page }) => {
    await expect(page.getByText(/early access/i)).toBeVisible();
    await expect(page.getByText(/improved/i)).toBeVisible();
  });

  test('early access section hidden when no EA reviews', async ({ page }) => {
    await page.route('**/api/games/*/early-access-impact', route =>
      route.fulfill({ json: MOCK_EA_IMPACT_NO_EA })
    );
    await page.goto('/games/440/team-fortress-2');
    // Should NOT render the EA impact section
    await expect(page.getByText(/early access impact/i)).not.toBeVisible();
  });

  // Feature 4: Review Integrity
  test('review integrity badge renders with flag', async ({ page }) => {
    await expect(page.getByText(/review integrity|free key bias/i)).toBeVisible();
    await expect(page.getByText(/notable/i)).toBeVisible();
  });

  test('review integrity hidden when insufficient data', async ({ page }) => {
    await page.route('**/api/games/*/review-integrity', route =>
      route.fulfill({ json: MOCK_INTEGRITY_INSUFFICIENT })
    );
    await page.goto('/games/440/team-fortress-2');
    await expect(page.getByText(/free key bias/i)).not.toBeVisible();
  });

  // Feature 5: Review Velocity
  test('review velocity chart renders with trend badge', async ({ page }) => {
    await expect(page.getByText(/velocity|momentum/i)).toBeVisible();
    await expect(page.getByText(/accelerating/i)).toBeVisible();
  });

  test('review velocity shows monthly average', async ({ page }) => {
    await expect(page.getByText(/monthly avg|avg.*monthly/i)).toBeVisible();
  });

  // Feature 6: Top Reviews
  test('top reviews section renders review cards', async ({ page }) => {
    await expect(page.getByText(/top reviews|most helpful/i)).toBeVisible();
    await expect(page.getByText(/masterpiece/i)).toBeVisible(); // from body_preview
  });

  test('top reviews show helpful vote counts', async ({ page }) => {
    await expect(page.getByText(/1,?523/)).toBeVisible(); // votes_helpful
  });

  test('top reviews show playtime hours', async ({ page }) => {
    await expect(page.getByText(/450.*h|450 hours/i)).toBeVisible();
  });
});

// ──────────────────────────────────────────────
// Genre Page — Market Analytics
// ──────────────────────────────────────────────

test.describe('Genre page — market analytics', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto('/genre/action');
  });

  // Feature 7: Price Positioning
  test('price positioning chart renders with sweet spot', async ({ page }) => {
    await expect(page.getByText(/price.*positioning|pricing/i)).toBeVisible();
    await expect(page.getByText(/sweet spot/i)).toBeVisible();
    await expect(page.getByText(/\$10-15/)).toBeVisible();
  });

  test('price summary stats shown', async ({ page }) => {
    await expect(page.getByText(/median/i)).toBeVisible();
    await expect(page.getByText(/45.*free/i)).toBeVisible();
  });

  // Feature 8: Release Timing
  test('release timing chart renders with month highlights', async ({ page }) => {
    await expect(page.getByText(/release timing|launch.*window/i)).toBeVisible();
    await expect(page.getByText(/february/i)).toBeVisible(); // best month
  });

  test('best and worst months are highlighted', async ({ page }) => {
    await expect(page.getByText(/best.*month|best.*launch/i)).toBeVisible();
  });

  // Feature 9: Platform Gaps
  test('platform distribution renders with underserved indicator', async ({ page }) => {
    await expect(page.getByText(/platform/i)).toBeVisible();
    await expect(page.getByText(/linux/i)).toBeVisible();
    await expect(page.getByText(/opportunity/i)).toBeVisible();
  });
});

// ──────────────────────────────────────────────
// Tag Page — Tag Trends
// ──────────────────────────────────────────────

test.describe('Tag page — tag trend', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto('/tag/roguelike');
  });

  // Feature 10: Tag Trend
  test('tag trend chart renders with growth rate', async ({ page }) => {
    await expect(page.getByText(/trend|growth/i)).toBeVisible();
    await expect(page.getByText(/roguelike/i)).toBeVisible();
  });

  test('peak year is shown', async ({ page }) => {
    await expect(page.getByText(/2023/)).toBeVisible(); // peak year
  });
});

// ──────────────────────────────────────────────
// Developer Page — Portfolio Analytics
// ──────────────────────────────────────────────

test.describe('Developer page — portfolio analytics', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApiRoutes(page);
    await page.goto('/developer/valve');
  });

  // Feature 11: Developer Portfolio
  test('developer portfolio summary renders', async ({ page }) => {
    await expect(page.getByText(/valve/i)).toBeVisible();
    await expect(page.getByText(/3.*games|games.*3/i)).toBeVisible();
  });

  test('sentiment trajectory badge shown', async ({ page }) => {
    await expect(page.getByText(/stable|improving|declining/i)).toBeVisible();
  });

  test('developer games list renders with links', async ({ page }) => {
    await expect(page.getByText('Counter-Strike 2')).toBeVisible();
    const link = page.getByRole('link', { name: /counter-strike 2/i }).first();
    await expect(link).toHaveAttribute('href', /\/games\/730\//);
  });
});

// ──────────────────────────────────────────────
// Graceful Degradation
// ──────────────────────────────────────────────

test.describe('Analytics — graceful degradation', () => {
  test('page renders without analytics when endpoints fail', async ({ page }) => {
    await mockAllApiRoutes(page);
    // Override all analytics endpoints to return 500
    for (const pattern of [
      '**/audience-overlap*', '**/playtime-sentiment',
      '**/early-access-impact', '**/review-integrity',
      '**/review-velocity', '**/top-reviews*',
    ]) {
      await page.route(`**/api/games/*/${pattern.replace('**/', '')}`, route =>
        route.fulfill({ status: 500, body: 'Internal Server Error' })
      );
    }
    await page.goto('/games/440/team-fortress-2');
    // Core page should still render — analytics sections just don't appear
    await expect(page.getByRole('heading', { name: 'Team Fortress 2' })).toBeVisible();
  });

  test('genre page renders without analytics when endpoints fail', async ({ page }) => {
    await mockAllApiRoutes(page);
    for (const ep of ['price-positioning', 'release-timing', 'platform-gaps']) {
      await page.route(`**/api/analytics/${ep}*`, route =>
        route.fulfill({ status: 500, body: 'error' })
      );
    }
    await page.goto('/genre/action');
    // Genre page should still render game listings
    await expect(page.getByText(/action/i).first()).toBeVisible();
  });
});
```

### Enhance existing test files

#### game-report.spec.ts

The existing game-report tests should continue to pass unchanged. The
new analytics sections render below the existing content. If any existing
tests use scroll or check for specific "last section" patterns, they may
need minor adjustments to account for the new sections.

Add a test to the existing describe block:

```typescript
test('analytics sections render below report', async ({ page }) => {
  // Scroll down to see analytics
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  // At least one analytics section should be visible
  await expect(
    page.getByText(/audience overlap|playtime.*sentiment|review velocity/i)
  ).toBeVisible();
});
```

#### genre-tag-developer.spec.ts

If this file tests genre/tag/developer pages, add assertions for the new
analytics sections. If the tests check that specific content is on the
page, add the analytics headings to the expected content list.

### Run Playwright tests

```bash
cd frontend && npx playwright test --project=chromium
```

All existing tests must continue to pass. New tests should cover:
- **Visibility**: Each analytics section renders with expected content
- **Data binding**: Numbers, percentages, and labels from mock data appear
- **Navigation**: Links in analytics sections go to correct URLs
- **Degradation**: Pages render without crashing when endpoints return errors
- **Conditional rendering**: Sections hide when data indicates they should
  (no EA reviews → no EA section, insufficient data → no integrity section)

---

## Notes

- **Recharts** is already installed. Import from `recharts`.
- **All data fetching** happens server-side (Next.js server components) or
  in useEffect for client components. Follow existing patterns.
- **Responsive design**: All charts must work on mobile. Use
  `ResponsiveContainer` with percentage width.
- **No new dependencies**: Use only Recharts + existing libs. No D3, no
  chart.js, no additional packages.
- **Number formatting**: Use `Intl.NumberFormat` for large numbers
  (1,234,567 → "1.2M"). Create a shared utility if one doesn't exist.
- **Date formatting**: Use consistent format across all charts.
  Month charts: "Jan", "Feb". Timeline: "Jan '24". Full dates: "Jan 15, 2024".
