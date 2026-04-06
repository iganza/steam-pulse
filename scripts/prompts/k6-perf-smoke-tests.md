# k6 Performance Smoke Tests & Baseline Tracking

## Goal

Set up k6 for two purposes:
1. **Post-deploy smoke test** — verify all API endpoints return 200 within a threshold
2. **Performance baseline tracking** — measure p50/p95/p99 response times, track over time

## Why k6

- Free, single binary (`brew install k6`)
- TypeScript support (k6 v1.0+)
- Thresholds exit non-zero on failure — CI-friendly
- `handleSummary()` writes JSON per run — commit for trend tracking
- Covers both smoke testing and perf baselines with one tool
- No SaaS, no agents, no infrastructure cost

## What to create

### Directory structure

```
scripts/perf/
  smoke.ts          — post-deploy: all endpoints return 200 within threshold
  baseline.ts       — warm perf: multiple iterations, tighter thresholds
  utils.ts          — shared endpoint list and helpers
perf-results/       — JSON summaries per run (gitignored except README)
```

### `scripts/perf/utils.ts` — shared endpoint definitions

Define all API endpoints in one place. Group by category so smoke and baseline
can share the same list.

```typescript
export const BASE = __ENV.BASE_URL || 'https://staging.steampulse.io';
export const SAMPLE_APPID = __ENV.SAMPLE_APPID || '440';  // TF2
export const SAMPLE_GENRE = __ENV.SAMPLE_GENRE || 'indie';
export const SAMPLE_TAG = __ENV.SAMPLE_TAG || 'roguelike';
export const SAMPLE_DEV = __ENV.SAMPLE_DEV || 'valve';

export const endpoints = [
  // Health
  { name: 'health', path: '/health' },

  // Catalog browse (highest traffic)
  { name: 'games_unfiltered', path: '/api/games?limit=24' },
  { name: 'games_genre', path: `/api/games?genre=${SAMPLE_GENRE}&limit=24` },
  { name: 'games_tag', path: `/api/games?tag=${SAMPLE_TAG}&limit=24` },
  { name: 'games_genre_sentiment', path: `/api/games?genre=${SAMPLE_GENRE}&sort=sentiment_score&min_reviews=200&limit=3` },
  { name: 'genres', path: '/api/genres' },
  { name: 'tags_top', path: '/api/tags/top' },
  { name: 'tags_grouped', path: '/api/tags/grouped' },

  // Game detail (per-game)
  { name: 'report', path: `/api/games/${SAMPLE_APPID}/report` },
  { name: 'review_stats', path: `/api/games/${SAMPLE_APPID}/review-stats` },
  { name: 'benchmarks', path: `/api/games/${SAMPLE_APPID}/benchmarks` },
  { name: 'audience_overlap', path: `/api/games/${SAMPLE_APPID}/audience-overlap` },
  { name: 'playtime_sentiment', path: `/api/games/${SAMPLE_APPID}/playtime-sentiment` },
  { name: 'early_access', path: `/api/games/${SAMPLE_APPID}/early-access-impact` },
  { name: 'review_velocity', path: `/api/games/${SAMPLE_APPID}/review-velocity` },
  { name: 'top_reviews', path: `/api/games/${SAMPLE_APPID}/top-reviews` },

  // Analytics
  { name: 'price_positioning', path: `/api/analytics/price-positioning?genre=${SAMPLE_GENRE}` },
  { name: 'release_timing', path: `/api/analytics/release-timing?genre=${SAMPLE_GENRE}` },
  { name: 'platform_gaps', path: `/api/analytics/platform-gaps?genre=${SAMPLE_GENRE}` },
  { name: 'tag_trend', path: `/api/tags/${SAMPLE_TAG}/trend` },
  { name: 'developer', path: `/api/developers/${SAMPLE_DEV}/analytics` },

  // Trends (dashboard)
  { name: 'trend_release_volume', path: '/api/analytics/trends/release-volume' },
  { name: 'trend_sentiment', path: '/api/analytics/trends/sentiment' },
  { name: 'trend_genre_share', path: '/api/analytics/trends/genre-share' },
  { name: 'trend_velocity', path: '/api/analytics/trends/velocity' },
  { name: 'trend_pricing', path: '/api/analytics/trends/pricing' },
  { name: 'trend_early_access', path: '/api/analytics/trends/early-access' },
  { name: 'trend_platforms', path: '/api/analytics/trends/platforms' },
  { name: 'trend_engagement', path: '/api/analytics/trends/engagement' },
  { name: 'trend_categories', path: '/api/analytics/trends/categories' },
];
```

### `scripts/perf/smoke.ts` — post-deploy verification

- 1 VU, 1 iteration (single pass through all endpoints)
- Threshold: all requests succeed, p95 < 5s (allows cold starts)
- Exits non-zero on failure
- Writes JSON summary for tracking

```typescript
import http from 'k6/http';
import { check, group } from 'k6';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.1.0/index.js';
import { BASE, endpoints } from './utils.ts';

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    http_req_failed: ['rate==0'],
    http_req_duration: ['p(95)<5000'],
  },
};

export default function () {
  for (const ep of endpoints) {
    const res = http.get(`${BASE}${ep.path}`, { tags: { endpoint: ep.name } });
    check(res, {
      [`${ep.name} → 200`]: (r) => r.status === 200,
      [`${ep.name} < 5s`]: (r) => r.timings.duration < 5000,
    });
  }
}

export function handleSummary(data) {
  const ts = new Date().toISOString().slice(0, 10);
  return {
    [`perf-results/smoke-${ts}.json`]: JSON.stringify(data, null, 2),
    stdout: textSummary(data, { indent: '  ', enableColors: true }),
  };
}
```

### `scripts/perf/baseline.ts` — warm performance measurement

- 1 VU, 5 iterations (first warms Lambda, next 4 measure warm perf)
- Tighter thresholds: p95 < 1s for browse endpoints, p95 < 3s for detail pages
- Writes JSON per run for trend comparison

```typescript
import http from 'k6/http';
import { check } from 'k6';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.1.0/index.js';
import { BASE, endpoints } from './utils.ts';

export const options = {
  vus: 1,
  iterations: 5,
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    'http_req_duration{endpoint:games_genre}': ['p(95)<1000'],
    'http_req_duration{endpoint:genres}': ['p(95)<500'],
    'http_req_duration{endpoint:tags_top}': ['p(95)<500'],
    'http_req_duration{endpoint:tags_grouped}': ['p(95)<500'],
  },
};

export default function () {
  for (const ep of endpoints) {
    const res = http.get(`${BASE}${ep.path}`, { tags: { endpoint: ep.name } });
    check(res, {
      [`${ep.name} → 200`]: (r) => r.status === 200,
    });
  }
}

export function handleSummary(data) {
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return {
    [`perf-results/baseline-${ts}.json`]: JSON.stringify(data, null, 2),
    stdout: textSummary(data, { indent: '  ', enableColors: true }),
  };
}
```

## Usage

```bash
# Install k6
brew install k6

# Post-deploy smoke test (staging)
k6 run scripts/perf/smoke.ts -e BASE_URL=https://staging.steampulse.io

# Post-deploy smoke test (production)
k6 run scripts/perf/smoke.ts -e BASE_URL=https://steampulse.io

# Performance baseline (warm measurement)
k6 run scripts/perf/baseline.ts -e BASE_URL=https://steampulse.io

# Override sample game/genre
k6 run scripts/perf/smoke.ts -e BASE_URL=https://steampulse.io -e SAMPLE_APPID=570 -e SAMPLE_GENRE=action
```

## Integration with deploy script

Add to `scripts/deploy.sh` after CDK deploy + migration:

```bash
# Post-deploy smoke test
echo "▶ Running post-deploy smoke test..."
if k6 run scripts/perf/smoke.ts -e BASE_URL="$DEPLOY_URL"; then
  echo "✓ Smoke test passed"
else
  echo "✗ Smoke test FAILED — check perf-results/"
  exit 1
fi
```

## Trend tracking

Option 1 (simplest): Git-commit the JSON summaries in `perf-results/`. Use `git log` to see
trends. Add a `.gitkeep` to the directory.

Option 2 (better): A small Python script that reads all `perf-results/baseline-*.json` files,
extracts p95 per endpoint, and prints a comparison table or writes a CSV.

Option 3 (best UX, free): Use Grafana Cloud k6 free tier (50 runs/month). Replace `k6 run`
with `k6 cloud` for visual dashboard with historical comparison.

## Files to create

| File | Purpose |
|------|---------|
| `scripts/perf/smoke.ts` | Post-deploy smoke test |
| `scripts/perf/baseline.ts` | Warm performance baseline |
| `scripts/perf/utils.ts` | Shared endpoint list |
| `perf-results/.gitkeep` | Directory for JSON summaries |
| `.gitignore` entry | `perf-results/*.json` (or commit them for tracking) |

## Thresholds rationale

| Endpoint type | Smoke threshold | Baseline threshold | Why |
|---------------|-----------------|-------------------|-----|
| Health | < 5s | < 500ms | Cold start allowance |
| Browse (genre/tag) | < 5s | < 1s | Matview fast path, should be instant warm |
| Matview counts (genres/tags) | < 5s | < 500ms | Single matview read |
| Game detail | < 5s | < 3s | Per-game queries, some hit reviews table |
| Analytics | < 5s | < 3s | Matview reads, but some still hit base tables |
| Dashboard trends | < 5s | < 3s | Catalog-wide queries, tolerate slower |

## Sources

- [k6 API Load Testing Guide](https://grafana.com/docs/k6/latest/testing-guides/api-load-testing/)
- [k6 Smoke Test Example](https://grafana.com/docs/k6/latest/testing-guides/test-types/smoke-testing/)
- [k6 Thresholds](https://grafana.com/docs/k6/latest/using-k6/thresholds/)
- [k6 Custom Summary](https://grafana.com/docs/k6/latest/results-output/end-of-test/custom-summary/)
- [k6 Testing Serverless APIs on AWS](https://k6.io/blog/serverless-api-on-aws-test/)
