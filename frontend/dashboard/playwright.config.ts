import path from 'node:path';
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:3100',
    headless: true,
  },
  webServer: [
    {
      name: 'Frontend',
      command: 'npm run dev -- -p 3100',
      cwd: __dirname,
      env: { META_HARNESS_BACKEND_URL: 'http://127.0.0.1:8100' },
      url: 'http://127.0.0.1:3100',
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      name: 'Backend',
      command: 'META_HARNESS_API_PERSISTENT=memory uv run uvicorn app.main:app --port 8100',
      cwd: path.resolve(__dirname, '../../backend'),
      url: 'http://127.0.0.1:8100/health',
      reuseExistingServer: false,
      timeout: 20_000,
    },
  ],
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
