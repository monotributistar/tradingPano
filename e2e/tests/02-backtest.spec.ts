/**
 * Backtest flow E2E tests
 * Tests the full lifecycle: submit → pending → running → done → view results.
 * Also covers ValidationPanel (walk-forward + Monte Carlo) and PriceChart.
 */
import { test, expect, mockAllRoutes, MOCK_BACKTEST_PENDING, MOCK_BACKTEST_DONE, MOCK_WALK_FORWARD_RESULT, MOCK_MONTE_CARLO_RESULT } from "./fixtures";

test.describe("Backtest Flow", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Backtests/i }).click();
  });

  test("shows backtest form with strategy, pair, period selects", async ({ page }) => {
    await expect(page.getByText("New Backtest")).toBeVisible();
    await expect(page.locator("select").nth(0)).toBeVisible(); // strategy
    await expect(page.locator("select").nth(1)).toBeVisible(); // pair
    await expect(page.locator("select").nth(2)).toBeVisible(); // period
    await expect(page.getByRole("button", { name: /Run Backtest/i })).toBeVisible();
  });

  test("strategy dropdown is populated from API with all 19 strategies", async ({ page }) => {
    const stratSelect = page.locator("select").nth(0);
    await expect(stratSelect.locator("option")).toHaveCount(19);
    await expect(stratSelect.locator("option").nth(0)).toHaveText("mean_reversion");
    // Verify new strategies are present
    await expect(stratSelect.locator("option[value='stoch_rsi']")).toBeAttached();
    await expect(stratSelect.locator("option[value='supertrend_pro']")).toBeAttached();
    await expect(stratSelect.locator("option[value='funding_rate_arb']")).toBeAttached();
    await expect(stratSelect.locator("option[value='momentum_burst']")).toBeAttached();
    await expect(stratSelect.locator("option[value='ichimoku']")).toBeAttached();
  });

  test("submits backtest and shows pending state", async ({ page }) => {
    // Override to return pending on POST, then done on GET
    let postCalled = false;
    await page.route("**/api/backtests", async (r) => {
      if (r.request().method() === "POST") {
        postCalled = true;
        await r.fulfill({ status: 202, json: MOCK_BACKTEST_PENDING });
      } else {
        await r.fulfill({ json: postCalled ? [MOCK_BACKTEST_PENDING] : [] });
      }
    });
    await page.route("**/api/backtests/1", (r) => r.fulfill({ json: MOCK_BACKTEST_PENDING }));

    await page.getByRole("button", { name: /Run Backtest/i }).click();
    await expect(page.getByText(/pending|Waiting/i).first()).toBeVisible();
  });

  test("shows completed backtest metrics", async ({ page }) => {
    // Click the completed job in the sidebar
    await page.getByText("mean_reversion").nth(1).click();

    // Metrics should be visible
    await expect(page.getByText("Total Return")).toBeVisible();
    await expect(page.getByText("+12.4%")).toBeVisible();
    await expect(page.getByText("1.85")).toBeVisible(); // sharpe
    await expect(page.getByText("64.30%")).toBeVisible(); // win rate
    await expect(page.getByText("47")).toBeVisible();   // trades
  });

  test("shows equity curve chart for done backtest", async ({ page }) => {
    await page.getByText("mean_reversion").nth(1).click();
    await expect(page.getByText("Equity Curve")).toBeVisible();
    // recharts renders an SVG
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("shows trade table for done backtest", async ({ page }) => {
    await page.getByText("mean_reversion").nth(1).click();
    await expect(page.getByText(/Trades \(/)).toBeVisible();
    await expect(page.getByText("BUY")).toBeVisible();
    await expect(page.getByText("SELL")).toBeVisible();
  });

  test("can change strategy and pair before submitting", async ({ page }) => {
    const stratSelect = page.locator("select").nth(0);
    const pairSelect = page.locator("select").nth(1);
    const periodSelect = page.locator("select").nth(2);

    await stratSelect.selectOption("ema_crossover");
    await pairSelect.selectOption("ETH/USDT");
    await periodSelect.selectOption("1y");

    await expect(stratSelect).toHaveValue("ema_crossover");
    await expect(pairSelect).toHaveValue("ETH/USDT");
    await expect(periodSelect).toHaveValue("1y");
  });

  test("delete button removes backtest", async ({ page }) => {
    await page.route("**/api/backtests/1", async (r) => {
      if (r.request().method() === "DELETE") {
        await r.fulfill({ status: 204, body: "" });
      } else {
        await r.fulfill({ json: MOCK_BACKTEST_DONE });
      }
    });

    await page.getByText("mean_reversion").nth(1).click();
    await expect(page.getByRole("button", { name: /Delete/i })).toBeVisible();
    await page.getByRole("button", { name: /Delete/i }).click();

    // After delete, detail panel should clear
    await expect(page.getByText("Select or submit a backtest")).toBeVisible();
  });

  test("shows walk-forward validation panel for done backtest", async ({ page }) => {
    await page.getByText("mean_reversion").nth(1).click();
    await expect(page.getByText(/Walk-forward validation/i)).toBeVisible();
    await expect(page.getByText(/Monte Carlo/i)).toBeVisible();
    // Both "Run" buttons should be present
    await expect(page.getByRole("button", { name: /^Run$/i })).toHaveCount(2);
  });

  test("shows price chart section for done backtest", async ({ page }) => {
    await page.getByText("mean_reversion").nth(1).click();
    await expect(page.getByText(/Price Chart/i)).toBeVisible();
    // Legend items
    await expect(page.getByText(/Buy \/ Cover/i)).toBeVisible();
    await expect(page.getByText(/Short/i)).toBeVisible();
    await expect(page.getByText(/Sell/i)).toBeVisible();
  });

  test("walk-forward Run triggers API call and shows results", async ({ page }) => {
    let wfCalled = false;
    await page.route("**/api/backtests/1/walk-forward", async (r) => {
      wfCalled = true;
      await r.fulfill({ json: MOCK_WALK_FORWARD_RESULT });
    });

    await page.getByText("mean_reversion").nth(1).click();
    // Click the first "Run" button (walk-forward)
    await page.getByRole("button", { name: /^Run$/i }).first().click();

    await expect(page.getByText(/Avg return/i)).toBeVisible();
    await expect(page.getByText(/Consistency/i)).toBeVisible();
    await expect(page.getByText(/Avg Sharpe/i)).toBeVisible();
    // Bar chart for segments
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("monte carlo Run triggers API call and shows results", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo", async (r) => {
      await r.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    });

    await page.getByText("mean_reversion").nth(1).click();
    // Click the second "Run" button (Monte Carlo)
    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();

    await expect(page.getByText(/Mean return/i)).toBeVisible();
    await expect(page.getByText(/Prob profit/i)).toBeVisible();
    await expect(page.getByText(/Median DD/i)).toBeVisible();
    await expect(page.getByText(/91.4%/)).toBeVisible(); // probability_profit
  });

  test("error state shows error message", async ({ page }) => {
    await page.route("**/api/backtests/1", (r) =>
      r.fulfill({
        json: {
          ...MOCK_BACKTEST_PENDING,
          status: "error",
          error_msg: "Exchange timeout: failed to fetch BTC/USDT",
        },
      })
    );
    await page.route("**/api/backtests", (r) =>
      r.fulfill({ json: [{ ...MOCK_BACKTEST_PENDING, status: "error", error_msg: "Exchange timeout" }] })
    );

    await page.getByText("mean_reversion").nth(1).click();
    await expect(page.getByText(/Exchange timeout/)).toBeVisible();
  });
});
