import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Market Reach card', () => {
  test('renders Pro-gated populated state on an analyzed game (free tier)', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')

    const card = page.getByTestId('market-reach')
    await expect(card).toBeVisible()

    // Labels and explainer remain readable even on the free tier.
    await expect(card.getByText(/estimated owners/i)).toBeVisible()
    await expect(card.getByText(/estimated gross revenue/i)).toBeVisible()
    await expect(card.getByText(/boxleiter ratio/i)).toBeVisible()

    // Numeric ranges are present in the DOM but blurred + aria-hidden.
    const blurred = card.locator('[aria-hidden="true"]').first()
    await expect(blurred).toHaveClass(/blur-sm/)

    // Unlock CTA is the focusable element.
    const cta = page.getByTestId('market-reach-cta')
    await expect(cta).toBeVisible()
    await expect(cta).toHaveText(/unlock with pro/i)
  })

  test('renders insufficient-reviews empty state (no blur, no CTA)', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/9999999/obscure-indie-game')

    const card = page.getByTestId('market-reach')
    await expect(card).toBeVisible()

    const empty = page.getByTestId('market-reach-empty')
    await expect(empty).toBeVisible()
    await expect(empty).toHaveText(/not enough reviews yet to estimate \(42\/50\)/i)

    // Empty state is not Pro-gated.
    await expect(page.getByTestId('market-reach-cta')).toHaveCount(0)
  })

  // TODO(pro-gating): the populated-Pro rendering path is currently
  // unreachable via E2E — `usePro()` returns false everywhere until the
  // auth/subscription wiring in scripts/prompts/pro-gating.md lands. When
  // that ships, enable this test: it should assert the card renders
  // ranges without blur and with no "Unlock with Pro" CTA.
  test.skip('renders populated state for Pro users without blur or CTA', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')

    const card = page.getByTestId('market-reach')
    await expect(card).toBeVisible()
    await expect(card.getByText(/estimated owners/i)).toBeVisible()
    await expect(card.getByText(/estimated gross revenue/i)).toBeVisible()
    await expect(page.getByTestId('market-reach-cta')).toHaveCount(0)
    await expect(card.locator('[aria-hidden="true"].blur-sm')).toHaveCount(0)
  })

  test('renders free-to-play empty state when reason is free_to_play', async ({ page }) => {
    // Register wildcard/fallback routes FIRST so the specific 220/report
    // handler below wins via Playwright's LIFO route matching.
    await mockAllApiRoutes(page)
    await page.route('**/api/games/220/report', route =>
      route.fulfill({
        json: {
          status: 'not_available',
          review_count: 5000,
          game: {
            short_desc: 'F2P title',
            developer: 'Valve',
            release_date: '2012-01-01',
            price_usd: null,
            is_free: true,
            is_early_access: false,
            positive_pct: 90,
            review_score_desc: 'Very Positive',
            review_count: 5000,
            revenue_estimate_reason: 'free_to_play',
          },
        },
      })
    )

    await page.goto('/games/220/dota-2')

    const empty = page.getByTestId('market-reach-empty')
    await expect(empty).toBeVisible()
    await expect(empty).toHaveText(/free-to-play — revenue estimates don't apply/i)
  })
})
