import { test, expect } from '@playwright/test'
import { AUTHOR_NAME, ABOUT_URL } from '@/lib/author'
import { mockAllApiRoutes } from './fixtures/api-mock'
import { MOCK_GAME_ANALYZED } from './fixtures/mock-data'

test('homepage has OG tags', async ({ page }) => {
  await mockAllApiRoutes(page)
  await page.goto('/')
  const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content')
  expect(ogTitle).toContain('SteamPulse')
  const twitterCard = await page.locator('meta[name="twitter:card"]').getAttribute('content')
  expect(twitterCard).toBe('summary_large_image')
  const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
  expect(canonical).toBe('https://steampulse.io')
})

test('game page has OG image and canonical', async ({ page }) => {
  await mockAllApiRoutes(page)
  await page.goto('/games/440/team-fortress-2')
  const ogImage = await page.locator('meta[property="og:image"]').getAttribute('content')
  expect(ogImage).toContain('steam')
  const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
  expect(canonical).toContain('/games/440/')
  const jsonLds = await page.evaluate(() =>
    Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(
      (el) => el.textContent ?? ''
    )
  )
  const parsedJsonLds = jsonLds
    .map((s) => {
      try {
        return JSON.parse(s)
      } catch {
        return null
      }
    })
    .filter((v): v is Record<string, unknown> => v !== null)
  const videoGame = parsedJsonLds.find((obj) => obj['@type'] === 'VideoGame')
  expect(videoGame).toBeDefined()
  expect(videoGame).toMatchObject({
    '@type': 'VideoGame',
    datePublished: MOCK_GAME_ANALYZED.release_date,
  })

  // Article JSON-LD names a human author for the Google March-2026 AI-content
  // signal. Only emitted when a SteamPulse report exists for the game.
  const article = parsedJsonLds.find((obj) => obj['@type'] === 'Article')
  expect(article).toBeDefined()
  expect(article).toMatchObject({
    '@type': 'Article',
    author: { '@type': 'Person', name: AUTHOR_NAME },
  })
  expect((article as { author: { url: string } }).author.url).toBe(ABOUT_URL)
})

test('game page omits VideoGame.datePublished when coming_soon=true', async ({ page }) => {
  await mockAllApiRoutes(page)
  await page.route('**/api/games/8888888/report', route =>
    route.fulfill({
      json: {
        status: 'not_available',
        game: {
          name: 'Coming Soon Game',
          slug: 'coming-soon-game-8888888',
          short_desc: 'A game that has not released yet.',
          developer: 'Future Studio',
          release_date: '2028-10-31',
          coming_soon: true,
          price_usd: null,
          is_free: false,
          is_early_access: false,
        },
      },
    }),
  )
  await page.goto('/games/8888888/coming-soon-game-8888888')
  const jsonLds = await page.evaluate(() =>
    Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(
      (el) => el.textContent ?? ''
    )
  )
  const parsed = jsonLds
    .map((s) => {
      try { return JSON.parse(s) } catch { return null }
    })
    .filter((v): v is Record<string, unknown> => v !== null)
  const videoGame = parsed.find((obj) => obj['@type'] === 'VideoGame')
  expect(videoGame).toBeDefined()
  expect(videoGame).not.toHaveProperty('datePublished')
})

test('genre synthesis page has OG tags + Article JSON-LD', async ({ page }) => {
  await page.goto('/genre/rdb-base')
  const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content')
  expect(ogTitle).toContain('Players Want, Hate, and Praise')
  expect(ogTitle).toContain('SteamPulse')
  const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
  expect(canonical).toBe('https://steampulse.io/genre/rdb-base')
  const jsonLds = await page.evaluate(() =>
    Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(
      (el) => el.textContent ?? ''
    )
  )
  const parsed = jsonLds
    .map((s) => {
      try { return JSON.parse(s) } catch { return null }
    })
    .filter((v): v is Record<string, unknown> => v !== null)
  const article = parsed.find((obj) => obj['@type'] === 'Article')
  expect(article).toBeDefined()
  // author = named human expert (Google 2026 AI-content signal).
  expect(article).toMatchObject({
    '@type': 'Article',
    author: { '@type': 'Person', name: AUTHOR_NAME },
  })
})

test('robots.txt is accessible and correct', async ({ page }) => {
  const resp = await page.goto('/robots.txt')
  expect(resp?.status()).toBe(200)
  const body = await resp?.text()
  expect(body).toContain('sitemap')
  expect(body).toContain('Disallow: /api/')
})

test('sitemap.xml is accessible', async ({ page }) => {
  const resp = await page.goto('/sitemap.xml')
  expect(resp?.status()).toBe(200)
  const body = await resp?.text()
  expect(body).toMatch(/<urlset|<sitemapindex/)
  expect(body).toContain('steampulse.io')
  expect(body).toContain('/sitemap/')

  const childResp = await page.goto('/sitemap/0.xml')
  expect(childResp?.status()).toBe(200)
  expect(await childResp?.text()).toContain('<urlset')

  // Highest valid id (TOTAL_CHUNKS - 1); past current catalog end so urlset is empty but valid.
  const emptyValidChunkResp = await page.goto('/sitemap/12.xml')
  expect(emptyValidChunkResp?.status()).toBe(200)
  expect(await emptyValidChunkResp?.text()).toContain('<urlset')
})

test('search page canonical strips filter params', async ({ page }) => {
  await mockAllApiRoutes(page)
  await page.goto('/search?q=portal&sort=review_count&genre=puzzle')
  const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
  expect(canonical).toContain('q=portal')
  expect(canonical).not.toContain('sort=')
})
