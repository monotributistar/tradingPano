/**
 * Navigation & layout tests
 * Verifies all tabs render without errors and header shows correct state.
 */
import { test, expect, mockAllRoutes } from "./fixtures";

test.describe("Navigation", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
  });

  test("loads dashboard by default", async ({ page }) => {
    await expect(page).toHaveTitle(/Crypto Bot/);
    // Dashboard cards visible
    await expect(page.getByText("Total PnL")).toBeVisible();
    await expect(page.getByText("Win Rate")).toBeVisible();
  });

  test("header shows all 7 tabs", async ({ page }) => {
    for (const label of ["Dashboard", "Presets", "Backtests", "Trades", "Wallet", "Bot", "Provider"]) {
      await expect(page.getByRole("button", { name: new RegExp(label, "i") })).toBeVisible();
    }
  });

  test("header shows IDLE status when bot not running", async ({ page }) => {
    await expect(page.getByText("IDLE")).toBeVisible();
  });

  test("header shows RUNNING status when bot is active", async ({ page }) => {
    // Override bot status to running
    await page.route("**/api/bot/status", (r) =>
      r.fulfill({
        json: {
          running: true, mode: "paper", strategy: "mean_reversion",
          pairs: ["BTC/USDT"], started_at: "2026-01-01T10:00:00", error: null,
        },
      })
    );
    await page.goto("/");
    await expect(page.getByText(/PAPER/).first()).toBeVisible();
    await expect(page.getByText(/mean_reversion/).first()).toBeVisible();
    // Green dot on Bot tab
    await expect(page.getByRole("button", { name: /Bot/i }).locator('[class*="dot"]')).toBeVisible();
  });

  test("navigates to each tab without errors", async ({ page }) => {
    const tabs = [
      { btn: /Backtests/i, content: /New Backtest/i },
      { btn: /Presets/i, content: /Investment Profiles/i },
      { btn: /Trades/i, content: /\d+ trades/i },
      { btn: /Wallet/i, content: /Total Equity/i },
      { btn: /Bot/i, content: /Start Bot/i },
      { btn: /Provider/i, content: /Current Connection/i },
      { btn: /Dashboard/i, content: /Total PnL/i },
    ];
    for (const { btn, content } of tabs) {
      await page.getByRole("button", { name: btn }).click();
      await expect(page.getByText(content).first()).toBeVisible();
    }
  });
});
