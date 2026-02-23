import { defineConfig, devices } from '@playwright/test';

/**
 * VeritasAI Playwright E2E Configuration
 *
 * Requires the Vite dev server (npm run dev) and FastAPI backend to be running.
 * Set BACKEND_URL env var to override the default FastAPI base URL.
 *
 * Run:
 *   npx playwright test                  # headless, all projects
 *   npx playwright test --headed         # headed Chrome
 *   npx playwright test --project=Desktop
 *   npx playwright test --project=Mobile
 *   npx playwright test --ui             # interactive UI mode
 */
export default defineConfig({
  testDir: './tests/e2e',

  /* Max time one test can run */
  timeout: 45_000,

  /* Expect assertion timeout */
  expect: { timeout: 10_000 },

  /* Re-run failing tests once on CI */
  retries: process.env.CI ? 2 : 0,

  /* Parallel workers — reduce to 1 when tests share backend state */
  workers: process.env.CI ? 1 : 1,

  /* Reporter */
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],

  use: {
    /* Frontend base URL */
    baseURL: 'http://localhost:5173',

    /* Collect trace on first retry for easier debugging */
    trace: 'on-first-retry',

    /* Screenshot on failure */
    screenshot: 'only-on-failure',

    /* Video on failure */
    video: 'retain-on-failure',

    /* Consistent locale */
    locale: 'en-US',
  },

  projects: [
    {
      name: 'Desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 720 },
      },
    },
    {
      name: 'Mobile',
      use: {
        ...devices['iPhone 12'],
        /* iPhone 12: 390 × 844 */
      },
    },
  ],

  /* Auto-start Vite dev server when not already running */
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
