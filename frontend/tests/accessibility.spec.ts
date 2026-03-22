import { test, expect } from '@playwright/test'
import { mockAllApiRoutes } from './fixtures/api-mock'

test.describe('Accessibility basics', () => {
  test('all images have alt text', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/')
    const imagesWithoutAlt = await page.$$eval(
      'img:not([alt])',
      imgs => imgs.length
    )
    expect(imagesWithoutAlt).toBe(0)
  })

  test('game report page has a main landmark', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/games/440/team-fortress-2')
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('search page filter inputs have accessible labels', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/search')
    // All inputs (radio/checkbox) must have a label via explicit for/id or implicit wrapping
    const unlabelledInputs = await page.$$eval(
      'input[type="radio"], input[type="checkbox"]',
      inputs => inputs.filter(input => {
        // Check explicit label association
        const id = input.getAttribute('id')
        if (id && document.querySelector(`label[for="${id}"]`)) return false
        // Check implicit label (input inside label element)
        if (input.closest('label')) return false
        // Check aria-label or aria-labelledby
        if (input.hasAttribute('aria-label') || input.hasAttribute('aria-labelledby')) return false
        return true
      }).length
    )
    expect(unlabelledInputs).toBe(0)
  })

  test('pagination has navigation role', async ({ page }) => {
    await mockAllApiRoutes(page)
    await page.goto('/search')
    await expect(page.getByRole('navigation', { name: /pagination/i })).toBeVisible()
  })
})
