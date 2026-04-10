import { test, expect } from '@playwright/test'
import { collectConsoleErrors, KNOWN_GAME_PATHS } from './fixtures/helpers'

const isProduction = process.env.PLAYWRIGHT_BASE_URL?.includes('steampulse.io') ?? false

test.describe('SEO — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
  })

  test.afterEach(async () => {
    consoleCheck.check()
  })

  test('robots.txt is accessible', async ({ page }) => {
    const resp = await page.goto('/robots.txt')
    expect(resp?.status()).toBe(200)
    const body = await resp?.text()
    expect(body).toContain('Disallow: /api/')
  })

  test('sitemap.xml is accessible', async ({ page }) => {
    const resp = await page.goto('/sitemap.xml')
    expect(resp?.status()).toBe(200)
    const body = await resp?.text()
    expect(body).toContain('<urlset')
  })

  test('homepage has OG tags', async ({ page }) => {
    await page.goto('/')
    const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content')
    expect(ogTitle).toContain('SteamPulse')
    const twitterCard = await page.locator('meta[name="twitter:card"]').getAttribute('content')
    expect(twitterCard).toBe('summary_large_image')
  })

  test('homepage canonical URL points to steampulse.io', async ({ page }) => {
    test.skip(!isProduction, 'Canonical URL only valid on production')
    await page.goto('/')
    const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
    expect(canonical).toBe('https://steampulse.io')
  })

  test('game page has OG image and JSON-LD', async ({ page }) => {
    await page.goto(KNOWN_GAME_PATHS.TF2)
    const ogImage = await page.locator('meta[property="og:image"]').getAttribute('content')
    expect(ogImage).toContain('steam')
    const canonical = await page.locator('link[rel="canonical"]').getAttribute('href')
    expect(canonical).toContain('/games/440/')
    const jsonLds = await page.evaluate(() =>
      Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(
        (el) => el.textContent ?? '',
      ),
    )
    const videoGameScript = jsonLds.find((s) => s.includes('VideoGame'))
    expect(videoGameScript).toBeDefined()
    expect(JSON.parse(videoGameScript ?? '{}')).toMatchObject({ '@type': 'VideoGame' })
  })

  test('genre page has OG title with genre name', async ({ page }) => {
    await page.goto('/genre/action')
    const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content')
    expect(ogTitle).toContain('Action')
    expect(ogTitle).toContain('SteamPulse')
  })
})
