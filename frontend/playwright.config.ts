import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
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
  ],
  webServer: [
    {
      // Mock API server: handles server-side Next.js fetch calls that page.route()
      // cannot intercept (those are Node.js-level HTTP, not browser requests).
      command: 'node tests/mock-api-server.mjs',
      url: 'http://localhost:3001',
      reuseExistingServer: !process.env.CI,
      timeout: 10_000,
    },
    {
      command: 'npm run build && npm run start',
      url: 'http://localhost:3000',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      // Point server-side fetches at the mock API server (port 3001) so
      // page.tsx's getGameReport() etc. resolve during tests. Without this
      // override, .env.local's API_URL=http://localhost:8000 wins and every
      // server fetch fails.
      env: {
        ...process.env as Record<string, string>,
        API_URL: 'http://localhost:3001',
        // Defense-in-depth: never load Plausible during e2e runs, even if
        // the surrounding shell has NEXT_PUBLIC_PLAUSIBLE_ENABLED=true set.
        NEXT_PUBLIC_PLAUSIBLE_ENABLED: 'false',
      },
    },
  ],
})
