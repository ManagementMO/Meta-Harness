import { test, expect } from '@playwright/test';

test('live dashboard renders immutable provenance from FastAPI', async ({ page, request }) => {
  const runId = `playwright-live-${Date.now()}`;
  const created = await request.post('http://127.0.0.1:8000/runs', {
    data: {
      run_name: runId,
      proposer: 'mock',
      mock_bench: true,
      budget: 1,
      trials: 2,
      workers: 1,
      fresh: true,
      mode: 'research',
    },
  });
  expect(created.status()).toBe(201);

  try {
    await expect.poll(async () => {
      const response = await request.get(`http://127.0.0.1:8000/runs/${runId}`);
      return (await response.json()).status;
    }).toBe('completed');

    await page.goto(`/runs/${runId}`);
    await expect(page.getByText('SSE connected')).toBeVisible();
    await expect(page.getByTestId('trajectory-node')).toHaveCount(2);
    await expect(page.getByText(/Synthetic fixture — not a research result/)).toBeVisible();

    await page.getByRole('button', { name: /evidence/i }).click();
    await expect(page.getByText('Candidate identity')).toBeVisible();
    await expect(page.getByText('Evaluation contract')).toBeVisible();
    await expect(page.getByText('content-addressed')).toBeVisible();
    await expect(page.getByText(/cand_[0-9a-f]{16}/).first()).toBeVisible();

    const report = await request.get(`http://127.0.0.1:8000/runs/${runId}/report`);
    expect(report.status()).toBe(200);
    const reportBody = await report.json();
    expect(reportBody.synthetic).toBe(true);
    expect(reportBody.frontier_ids.length).toBeGreaterThan(0);
  } finally {
    await request.delete(`http://127.0.0.1:8000/runs/${runId}`);
  }
});
