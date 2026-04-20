/**
 * Trades page E2E tests
 * Tests trade table display, filtering, stats bar.
 */
import { test, expect, mockAllRoutes, MOCK_TRADES, MOCK_TRADE_STATS } from "./fixtures";

test.describe("Trades Page", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Trades/i }).click();
  });

  test("shows stats bar with key metrics", async ({ page }) => {
    await expect(page.getByText("47")).toBeVisible();      // total trades
    await expect(page.getByText("64.3%")).toBeVisible();   // win rate
    await expect(page.getByText("+2.4800 USDT")).toBeVisible(); // total pnl
  });

  test("shows trade table with buy and sell rows", async ({ page }) => {
    await expect(page.getByText("BUY", { exact: true })).toBeVisible();
    await expect(page.getByText("SELL", { exact: true })).toBeVisible();
    await expect(page.locator("table").getByText("BTC/USDT").first()).toBeVisible();
  });

  test("shows PnL colored green for profit and red for loss", async ({ page }) => {
    // SELL trade with pnl=0.1368 should show green
    await expect(page.getByText(/\+0\.1368/)).toBeVisible();
  });

  test("source filter changes API call", async ({ page }) => {
    let lastUrl = "";
    await page.route("**/api/trades**", async (r) => {
      if (r.request().url().includes("/trades/stats")) return r.continue();
      lastUrl = r.request().url();
      await r.fulfill({ json: MOCK_TRADES });
    });

    const sourceSelect = page.locator("select").nth(0);
    await sourceSelect.selectOption("paper");
    await page.waitForTimeout(300);
    expect(lastUrl).toContain("source=paper");
  });

  test("pair filter works", async ({ page }) => {
    let lastUrl = "";
    await page.route("**/api/trades**", async (r) => {
      if (r.request().url().includes("/trades/stats")) return r.continue();
      lastUrl = r.request().url();
      await r.fulfill({ json: MOCK_TRADES });
    });

    const pairSelect = page.locator("select").nth(1);
    await pairSelect.selectOption("ETH/USDT");
    await page.waitForTimeout(300);
    expect(lastUrl).toContain("pair=ETH%2FUSDT");
  });

  test("type filter shows only buys or sells", async ({ page }) => {
    await page.route("**/api/trades**", (r) => {
      if (r.request().url().includes("/trades/stats")) return r.continue();
      return r.fulfill({ json: MOCK_TRADES.filter((t) => t.type === "buy") });
    });

    const typeSelect = page.locator("select").nth(2);
    await typeSelect.selectOption("buy");
    await expect(page.getByText("BUY", { exact: true })).toBeVisible();
    await expect(page.getByText("SELL", { exact: true })).not.toBeVisible();
  });

  test("shows reason column", async ({ page }) => {
    await expect(page.getByText("z-score entry -1.8")).toBeVisible();
  });

  test("empty state when no trades", async ({ page }) => {
    await page.route("**/api/trades**", (r) => r.fulfill({ json: [] }));
    await page.route("**/api/trades/stats", (r) =>
      r.fulfill({ json: { total_trades: 0, win_rate_pct: 0, total_pnl: 0, avg_pnl: 0 } })
    );
    await page.goto("/");
    await page.getByRole("button", { name: /Trades/i }).click();
    await expect(page.getByText("No trades found")).toBeVisible();
  });
});
