/** Browser tests against the real console and API.
 *
 *  Assumes the API is already serving on 127.0.0.1:8000 (`make dev`); Vite is
 *  started here if it is not. Intake and route selection write to the database,
 *  so run `make reset && make ingest` (and restart the API) to return to the
 *  pristine corpus afterwards.
 */

import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
