import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: process.env.MESHCORIUM_BASE_URL || 'http://127.0.0.1:8080',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
    launchOptions: {
      executablePath: process.env.MESHCORIUM_CHROMIUM_PATH || '/usr/bin/chromium',
    },
  },
})
