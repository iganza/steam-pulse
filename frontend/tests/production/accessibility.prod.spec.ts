import { test, expect } from '@playwright/test'
import { collectConsoleErrors, KNOWN_GAME_PATHS } from './fixtures/helpers'

test.describe('Accessibility — production', () => {
  let consoleCheck: ReturnType<typeof collectConsoleErrors>

  test.beforeEach(async ({ page }) => {
    consoleCheck = collectConsoleErrors(page)
  })

  test.afterEach(async () => {
    consoleCheck.check()
  })

  test('all images on home page have alt text', async ({ page }) => {
    await page.goto('/')
    const imagesWithoutAlt = await page.$$eval('img:not([alt])', (imgs) => imgs.length)
    expect(imagesWithoutAlt).toBe(0)
  })

  test('game report page has a main landmark', async ({ page }) => {
    await page.goto(KNOWN_GAME_PATHS.TF2)
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('search page filter inputs have accessible labels', async ({ page }) => {
    await page.goto('/search')
    const unlabelledInputs = await page.$$eval(
      'input[type="radio"], input[type="checkbox"]',
      (inputs) =>
        inputs.filter((input) => {
          const id = input.getAttribute('id')
          if (id && document.querySelector(`label[for="${id}"]`)) return false
          if (input.closest('label')) return false
          if (input.hasAttribute('aria-label') || input.hasAttribute('aria-labelledby'))
            return false
          return true
        }).length,
    )
    expect(unlabelledInputs).toBe(0)
  })

  test('search page pagination has navigation role', async ({ page }) => {
    await page.goto('/search')
    await expect(page.getByRole('navigation', { name: /pagination/i })).toBeVisible()
  })

  test('game report has breadcrumb navigation', async ({ page }) => {
    await page.goto(KNOWN_GAME_PATHS.TF2)
    await expect(page.getByRole('navigation', { name: /breadcrumb/i })).toBeVisible()
  })
})
