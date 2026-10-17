import { defineConfig, devices } from '@playwright/test';

// Not the app's port or the smoke test's, so it never meets a running Orchard. UI_TEST_PORT picks another.
export const PORT = Number(process.env.UI_TEST_PORT || 4498);

export default defineConfig({
  testDir: '.',
  globalSetup: './server.ts',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
});
