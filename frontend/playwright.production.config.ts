import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL
if (!baseURL) {
  throw new Error(
    'PLAYWRIGHT_BASE_URL is required for production tests.\n' +
      'Usage: PLAYWRIGHT_BASE_URL=https://steampulse.io npx playwright test --config playwright.production.config.ts',
  )
}

const allBrowsers = process.env.PRODUCTION_ALL_BROWSERS === 'true'

export default defineConfig({
  testDir: './tests/production',
  testMatch: '**/*.prod.spec.ts',
  fullyParallel: true,
  retries: 1,
  workers: process.env.CI ? 2 : undefined,
  timeout: 30_000,
  reporter: [
    ['html', { outputFolder: 'playwright-report-production', open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  expect: {
    timeout: 10_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    ...(allBrowsers
      ? [
          {
            name: 'firefox',
            use: { ...devices['Desktop Firefox'] },
          },
          {
            name: 'webkit',
            use: { ...devices['Desktop Safari'] },
          },
          {
            name: 'mobile-chrome',
            use: { ...devices['Pixel 5'] },
          },
        ]
      : []),
  ],
})
