import path from 'node:path';
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
  },
  webServer: [
    {
      name: 'Frontend',
      command: 'npm run dev',
      cwd: __dirname,
      url: 'http://127.0.0.1:3000',
      reuseExistingServer: true,
      timeout: 20_000,
    },
    {
      name: 'Backend',
      command: 'META_HARNESS_API_PERSISTENT=memory uv run uvicorn app.main:app --port 8000',
      cwd: path.resolve(__dirname, '../../backend'),
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: true,
      timeout: 20_000,
    },
  ],
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
