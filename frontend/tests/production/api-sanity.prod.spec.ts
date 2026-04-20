import { test, expect } from '@playwright/test'
import { fetchApiJson, KNOWN_APPIDS } from './fixtures/helpers'

const isLocalDev = (() => {
  const baseUrl = process.env.PLAYWRIGHT_BASE_URL
  if (!baseUrl) return true
  try {
    const hostname = new URL(baseUrl).hostname
    return hostname === 'localhost' || hostname === '127.0.0.1'
  } catch {
    return true
  }
})()

test.describe('API response shape sanity — production', () => {
  // Every test navigates to / first so fetchApiJson can resolve the origin
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('GET /health returns 200', async ({ page }) => {
    // /health is a FastAPI route — only reachable via CloudFront in deployed envs
    test.skip(isLocalDev, '/health is not proxied by Next.js locally')
    const resp = await fetchApiJson(page, '/health')
    expect(resp.status).toBe(200)
  })

  test('GET /api/games returns games with total > 0', async ({ page }) => {
    const resp = await fetchApiJson(page, '/api/games?limit=5')
    expect(resp.status).toBe(200)
    expect(resp.body.total).toBeGreaterThan(0)
    expect(resp.body.games.length).toBeGreaterThan(0)
    const game = resp.body.games[0]
    expect(game).toHaveProperty('appid')
    expect(game).toHaveProperty('name')
  })

  test('GET /api/games/{appid}/report returns response', async ({ page }) => {
    const resp = await fetchApiJson(page, `/api/games/${KNOWN_APPIDS.TF2}/report`)
    expect(resp.status).toBe(200)
    // Report may be 'available' (production) or 'not_available' (local)
    expect(['available', 'not_available']).toContain(resp.body.status)
    if (resp.body.status === 'available') {
      expect(resp.body.report).toBeDefined()
      const report = resp.body.report
      expect(report).toHaveProperty('game_name')
      expect(report).toHaveProperty('one_liner')
      expect(report).toHaveProperty('design_strengths')
    }
    // Game metadata is always present
    expect(resp.body.game).toBeDefined()
    expect(resp.body.game.positive_pct).toBeGreaterThan(0)
  })

  test('GET /api/genres returns genres with counts', async ({ page }) => {
    const resp = await fetchApiJson(page, '/api/genres')
    expect(resp.status).toBe(200)
    expect(resp.body.length).toBeGreaterThanOrEqual(3)
    const genre = resp.body[0]
    expect(genre).toHaveProperty('name')
    expect(genre).toHaveProperty('slug')
    expect(genre).toHaveProperty('game_count')
    expect(genre.game_count).toBeGreaterThan(0)
  })

  test('GET /api/tags/top returns tags', async ({ page }) => {
    const resp = await fetchApiJson(page, '/api/tags/top')
    expect(resp.status).toBe(200)
    expect(resp.body.length).toBeGreaterThan(0)
  })

  test('GET /api/games/{appid}/review-stats returns timeline and buckets', async ({ page }) => {
    const resp = await fetchApiJson(page, `/api/games/${KNOWN_APPIDS.TF2}/review-stats`)
    expect(resp.status).toBe(200)
    expect(resp.body).toHaveProperty('timeline')
    expect(resp.body).toHaveProperty('playtime_buckets')
    // Local DB may have empty arrays if reviews haven't been crawled
    expect(Array.isArray(resp.body.timeline)).toBe(true)
    expect(Array.isArray(resp.body.playtime_buckets)).toBe(true)
  })

  test('GET /api/games/{appid}/benchmarks returns ranks', async ({ page }) => {
    const resp = await fetchApiJson(page, `/api/games/${KNOWN_APPIDS.TF2}/benchmarks`)
    expect(resp.status).toBe(200)
    expect(resp.body).toHaveProperty('sentiment_rank')
    expect(resp.body).toHaveProperty('popularity_rank')
    expect(resp.body).toHaveProperty('cohort_size')
  })
})
