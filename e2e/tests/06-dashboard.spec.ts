/**
 * Dashboard E2E tests
 * Tests summary cards, equity curve, recent trades/backtests.
 */
import { test, expect, mockAllRoutes, MOCK_TRADE_STATS, MOCK_BACKTEST_DONE, MOCK_TRADES } from "./fixtures";

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
  });

  test("shows 6 summary cards", async ({ page }) => {
    const cardLabels = ["Total PnL", "Win Rate", "Avg PnL/trade", "Best Trade", "Worst Trade", "Backtests Run"];
    for (const label of cardLabels) {
      await expect(page.getByText(label)).toBeVisible();
    }
  });

  test("shows trade stats from API", async ({ page }) => {
    // win rate from MOCK_TRADE_STATS
    await expect(page.getByText("64.3%")).toBeVisible();
    await expect(page.getByText("47")).toBeVisible();
  });

  test("shows recent backtests table", async ({ page }) => {
    await expect(page.getByText("Recent Backtests")).toBeVisible();
    await expect(page.getByText("mean_reversion")).toBeVisible();
    await expect(page.getByText("6m")).toBeVisible();
    // return from MOCK_BACKTEST_DONE
    await expect(page.getByText("+12.4%")).toBeVisible();
  });

  test("shows recent trades table", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Recent Trades" })).toBeVisible();
    // type badge
    await expect(page.getByText("BUY").first()).toBeVisible();
  });

  test("equity curve section visible (empty state without paper trades)", async ({ page }) => {
    await page.route("**/api/trades**", (r) =>
      r.request().url().includes("/trades/stats") ? r.continue() : r.fulfill({ json: [] })
    );
    await page.goto("/");
    await expect(page.getByText("Paper Trading Equity")).toBeVisible();
    await expect(page.getByText(/No paper trades yet/)).toBeVisible();
  });

  test("equity curve renders SVG when paper trades exist", async ({ page }) => {
    // Return sell trades so cumulative equity is computed
    await page.route("**/api/trades**", (r) => {
      if (r.request().url().includes("/trades/stats")) return r.continue();
      return r.fulfill({
        json: [
          { ...MOCK_TRADES[1], source: "paper" },
          { ...MOCK_TRADES[1], id: 3, source: "paper", pnl: 0.22 },
        ],
      });
    });
    await page.goto("/");
    await expect(page.locator("svg").first()).toBeVisible({ timeout: 8000 });
  });

  test("zero state when no data", async ({ page }) => {
    // Register broad route first, specific ones last (LIFO: last wins)
    await page.route("**/api/trades**", (r) =>
      r.request().url().includes("/trades/stats") ? r.continue() : r.fulfill({ json: [] })
    );
    await page.route("**/api/backtests", (r) => r.fulfill({ json: [] }));
    await page.route("**/api/trades/stats", (r) =>
      r.fulfill({ json: { total_trades: 0, win_rate_pct: 0, total_pnl: 0, avg_pnl: 0, best_trade: 0, worst_trade: 0 } })
    );
    await page.goto("/");
    await expect(page.getByText("No completed backtests yet")).toBeVisible();
    await expect(page.getByText("No recent trades")).toBeVisible();
  });
});
