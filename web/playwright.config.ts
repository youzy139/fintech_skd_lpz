import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    channel: process.env.E2E_CHANNEL || (process.env.CI ? undefined : 'chrome'),
    headless: true,
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `${process.env.CI ? 'python' : 'conda run -n fintech python'} ../server/benchmarks/e2e_server.py`,
      url: 'http://127.0.0.1:18000/api/health/ready',
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5174',
      url: 'http://127.0.0.1:5174',
      timeout: 30_000,
      reuseExistingServer: false,
      env: { VITE_API_TARGET: 'http://127.0.0.1:18000' },
    },
  ],
})
