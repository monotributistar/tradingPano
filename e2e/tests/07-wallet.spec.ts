/**
 * Wallet page E2E tests
 * Tests equity display, open positions, and history chart.
 */
import { test, expect, mockAllRoutes, MOCK_WALLET_SUMMARY } from "./fixtures";

test.describe("Wallet", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Wallet/i }).click();
  });

  test("shows total equity card", async ({ page }) => {
    await expect(page.getByText("Total Equity")).toBeVisible();
    await expect(page.getByText(/21\.34.*USDT/)).toBeVisible();
  });

  test("shows free USDT card", async ({ page }) => {
    await expect(page.getByText("Free USDT")).toBeVisible();
    await expect(page.getByText(/18\.50.*USDT/)).toBeVisible();
  });

  test("shows positions value card", async ({ page }) => {
    await expect(page.getByText("Positions Value")).toBeVisible();
    await expect(page.getByText(/2\.84.*USDT/)).toBeVisible();
  });

  test("shows total P&L with percentage", async ({ page }) => {
    await expect(page.getByText(/Total P&L/i)).toBeVisible();
    await expect(page.getByText(/\+1\.34.*USDT/)).toBeVisible();
    await expect(page.getByText(/\+6\.70%/)).toBeVisible();
  });

  test("shows equity curve chart", async ({ page }) => {
    await expect(page.getByText(/Equity Over Time/i)).toBeVisible();
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("shows open positions table", async ({ page }) => {
    await expect(page.getByText("Open Positions").first()).toBeVisible();
    await expect(page.getByText("BTC/USDT").first()).toBeVisible();
    await expect(page.getByText(/43000/).first()).toBeVisible();
  });

  test("shows snapshot count", async ({ page }) => {
    await expect(page.getByText(/snapshots recorded/)).toBeVisible();
  });

  test("shows empty state when no data", async ({ page }) => {
    await page.route("**/api/wallet/summary", (r) =>
      r.fulfill({
        json: {
          total_equity: null, balance_usdt: null, positions_value: null,
          positions: {}, pnl: null, pnl_pct: null, snapshots_count: 0,
        },
      })
    );
    await page.route("**/api/wallet/history", (r) => r.fulfill({ json: [] }));
    await page.goto("/");
    await page.getByRole("button", { name: /Wallet/i }).click();
    await expect(page.getByText(/No wallet history yet/)).toBeVisible();
    await expect(page.getByText(/No open positions\./)).toBeVisible();
  });
});
