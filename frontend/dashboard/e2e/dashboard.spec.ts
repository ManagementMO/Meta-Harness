import { test, expect } from '@playwright/test';

test.describe('Dashboard (mock mode, no backend)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('http://localhost:8000/health', route => route.abort());
    await page.goto('/runs/demo-2026-04-25');
    await page.getByText('SSE connected').waitFor({ timeout: 10_000 });
  });

  test('trajectory tree renders nodes', async ({ page }) => {
    const nodes = page.getByTestId('trajectory-node');
    await expect(nodes.first()).toBeVisible({ timeout: 8_000 });
    await expect(nodes).toHaveCount(7, { timeout: 15_000 });
  });

  test('decision log shows iteration chapters', async ({ page }) => {
    const chapter = page.getByText('ITER 4 — more-specific-descriptions');
    await expect(chapter).toBeVisible({ timeout: 10_000 });
  });

  test('score chart renders data points', async ({ page }) => {
    // Switch to chart tab explicitly
    const chartTab = page.getByRole('button', { name: /chart/i });
    await chartTab.click();

    // ScoreChart circles have fill colors matching the whisper palette, not the dot-grid bg
    const dataCircles = page.locator('svg circle[fill="#6a9e78"], svg circle[fill="#8878a8"], svg circle[fill="#b06068"]');
    await expect(dataCircles.first()).toBeVisible({ timeout: 12_000 });
    expect(await dataCircles.count()).toBeGreaterThanOrEqual(1);
  });

  test('diff tab shows diff content', async ({ page }) => {
    // Select a tree node first
    const node = page.getByTestId('trajectory-node').first();
    if (await node.isVisible()) {
      await node.click();
    }

    const diffTab = page.getByRole('button', { name: /diff/i });
    await diffTab.click();

    await expect(
      page.getByText(/Mock task patch preview|No diff available for/),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('right-click tree node opens fork modal', async ({ page }) => {
    const node = page.getByTestId('trajectory-node').first();
    await expect(node).toBeVisible({ timeout: 8_000 });

    await node.click({ button: 'right' });

    // Use the modal title which has the fork symbol prefix
    const modalTitle = page.locator('text=⑂ Create Fork');
    await expect(modalTitle).toBeVisible({ timeout: 5_000 });
  });

  test('SSE status indicator shows connected', async ({ page }) => {
    const indicator = page.locator('text=SSE connected');
    await expect(indicator).toBeVisible({ timeout: 8_000 });
  });

  test('META-HARNESS link navigates home', async ({ page }) => {
    const link = page.locator('a', { hasText: 'META-HARNESS' });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', '/');
  });
});
