import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

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
  const videoGameScript = jsonLds.find((s) => s.includes('VideoGame'))
  expect(videoGameScript).toBeDefined()
  expect(JSON.parse(videoGameScript ?? '{}')).toMatchObject({ '@type': 'VideoGame' })
})

test('genre page has OG tags', async ({ page }) => {
  await mockAllApiRoutes(page)
  await page.goto('/genre/action')
  const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content')
  expect(ogTitle).toContain('Action')
  expect(ogTitle).toContain('SteamPulse')
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
  expect(body).toContain('<urlset')
  expect(body).toContain('steampulse.io')
})

test('search page canonical strips filter params', async ({ page }) => {
  await mockAllApiRoutes(page)
  await page.goto('/search?q=portal&sort=review_count&genre=puzzle')
  const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
  expect(canonical).toContain('q=portal')
  expect(canonical).not.toContain('sort=')
})
