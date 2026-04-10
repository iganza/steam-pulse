import { expect, type Locator, type Page } from '@playwright/test'

/** Valve flagship titles — permanent on Steam, always analyzed in SteamPulse. */
export const KNOWN_APPIDS = { TF2: 440, DOTA2: 570, CS2: 730 } as const

/** Full game page paths (appid + slug) — avoids relying on server-side redirects. */
export const KNOWN_GAME_PATHS = {
  TF2: '/games/440/team-fortress-2',
  DOTA2: '/games/570/dota-2',
  CS2: '/games/730/counter-strike-2',
} as const

export const KNOWN_GENRE_SLUG = 'action'
export const KNOWN_TAG_SLUG = 'multiplayer'
export const KNOWN_DEVELOPER_SLUG = 'valve'

/**
 * Collect console errors and uncaught page errors during a test.
 * Call in beforeEach; call check() in afterEach to fail on any errors.
 */
export function collectConsoleErrors(page: Page) {
  const errors: string[] = []

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text()
      // Ignore noisy but harmless browser warnings
      if (text.includes('Failed to load resource')) return // Network errors (404, 500) for assets
      if (text.includes('Hydration')) return // Next.js dev-mode hydration warnings
      if (text.includes('next-dev.js')) return // Next.js dev overlay noise
      errors.push(`[console.error] ${text}`)
    }
  })

  page.on('pageerror', (err) => {
    // Hydration mismatches in dev mode are noisy but not actionable in smoke tests
    if (err.message.includes('Hydration')) return
    if (err.message.includes('Minified React error')) return
    errors.push(`[pageerror] ${err.message}`)
  })

  return {
    errors,
    check() {
      if (errors.length > 0) {
        throw new Error(
          `Page errors detected (${errors.length}):\n${errors.map((e) => `  • ${e}`).join('\n')}`,
        )
      }
    },
  }
}

/** Fail if the rendered page text contains garbage strings. */
export async function assertNoVisibleGarbage(page: Page) {
  const body = await page.locator('body').innerText()
  // Each entry: [literal string to search for, regex to match it in context]
  const checks: Array<[string, RegExp]> = [
    ['undefined', /\bundefined\b/],
    ['NaN', /\bNaN\b/],
    ['[object Object]', /\[object Object\]/],
  ]
  for (const [label, regex] of checks) {
    if (regex.test(body)) {
      const lines = body.split('\n').filter((l) => regex.test(l))
      // Filter out lines that are likely game titles/descriptions containing the word
      const suspicious = lines.filter(
        (l) => !l.includes('code') && !l.includes('```') && l.trim().length < 200,
      )
      if (suspicious.length > 0) {
        throw new Error(
          `Visible garbage "${label}" found on page:\n${suspicious.map((l) => `  • ${l.trim()}`).join('\n')}`,
        )
      }
    }
  }
}

/** Assert the page loaded without error boundaries and has content. */
export async function assertPageLoadsOk(page: Page) {
  // Some pages may not have a <main> landmark — check for either main or body content
  const main = page.getByRole('main')
  const hasMain = (await main.count()) > 0
  if (hasMain) {
    await expect(main).toBeVisible()
  }
  await expect(page.locator('[data-testid="error-boundary"]')).toHaveCount(0)
  const title = await page.title()
  expect(title.length).toBeGreaterThan(0)
}

/** Assert a locator has at least `min` child elements. */
export async function assertListHasItems(locator: Locator, min = 1) {
  const count = await locator.count()
  expect(count).toBeGreaterThanOrEqual(min)
}

/** Make a direct API call against the production base URL and return parsed JSON. */
export async function fetchApiJson(page: Page, path: string) {
  const baseURL = page.url().startsWith('about:')
    ? process.env.PLAYWRIGHT_BASE_URL
    : new URL(page.url()).origin
  const resp = await page.evaluate(
    async ({ url }) => {
      const r = await fetch(url)
      const contentType = r.headers.get('content-type') ?? ''
      if (contentType.includes('application/json')) {
        return { status: r.status, body: await r.json() }
      }
      // Non-JSON response (e.g. HTML 404 from Next.js for non-proxied routes)
      return { status: r.status, body: { _text: await r.text() } }
    },
    { url: `${baseURL}${path}` },
  )
  return resp
}
