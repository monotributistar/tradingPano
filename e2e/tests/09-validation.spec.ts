/**
 * ValidationPanel (Walk-forward + Monte Carlo) E2E tests
 *
 * These tests focus on the two-panel validation section that appears below
 * the MetricsCard for every completed backtest.  We mock the walk-forward and
 * Monte Carlo endpoints to return deterministic results and verify that:
 *   - Controls (segments, period, runs) are visible and changeable
 *   - "Run" buttons fire the correct API requests
 *   - Results render the right metric values and charts
 *   - Errors from the API surface in a readable error box
 */
import { test, expect, mockAllRoutes, MOCK_WALK_FORWARD_RESULT, MOCK_MONTE_CARLO_RESULT } from "./fixtures";

test.describe("ValidationPanel – Walk-forward", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Backtests/i }).click();
    // Select the pre-loaded done backtest job
    await page.getByText("mean_reversion").nth(1).click();
  });

  test("walk-forward panel title and description are visible", async ({ page }) => {
    await expect(page.getByText(/Walk-forward validation/i)).toBeVisible();
    await expect(page.getByText(/Split the dataset into N chunks/i)).toBeVisible();
  });

  test("segments input and period select are visible with defaults", async ({ page }) => {
    // Segments number input defaults to 5
    const segInput = page.locator("input[type='number']");
    await expect(segInput).toBeVisible();
    await expect(segInput).toHaveValue("5");
    // Period select defaults to 1y
    const periodSelect = page.locator("select[value='1y'], select").filter({ hasText: "1 year" }).first();
    await expect(periodSelect).toBeVisible();
  });

  test("can change segments and period", async ({ page }) => {
    const segInput = page.locator("input[type='number']");
    await segInput.fill("3");
    await expect(segInput).toHaveValue("3");

    // Change period to 2y
    const controls = page.getByText(/Walk-forward validation/i).locator("..").locator("..");
    const periodSelect = controls.locator("select").first();
    await periodSelect.selectOption("2y");
    await expect(periodSelect).toHaveValue("2y");
  });

  test("Run walk-forward button fires API and renders aggregate stats", async ({ page }) => {
    let called = false;
    await page.route("**/api/backtests/1/walk-forward**", async (r) => {
      called = true;
      await r.fulfill({ json: MOCK_WALK_FORWARD_RESULT });
    });

    await page.getByRole("button", { name: /^Run$/i }).first().click();

    await expect(page.getByText(/Avg return/i)).toBeVisible();
    await expect(page.getByText(/Consistency/i)).toBeVisible();
    await expect(page.getByText(/Avg Sharpe/i)).toBeVisible();
    await expect(page.getByText(/Best segment/i)).toBeVisible();
    await expect(page.getByText(/Worst segment/i)).toBeVisible();
    await expect(page.getByText(/Std dev/i)).toBeVisible();
  });

  test("walk-forward shows correct aggregate values from mock", async ({ page }) => {
    await page.route("**/api/backtests/1/walk-forward**", async (r) => {
      await r.fulfill({ json: MOCK_WALK_FORWARD_RESULT });
    });

    await page.getByRole("button", { name: /^Run$/i }).first().click();

    // avg_return_pct: 3.78 → "+3.78%"
    await expect(page.getByText("+3.78%")).toBeVisible();
    // consistency_score: 80.0 → "80%"
    await expect(page.getByText("80%")).toBeVisible();
    // avg_sharpe: 1.24
    await expect(page.getByText("1.24")).toBeVisible();
    // best_segment_return: 7.1 → "+7.10%"
    await expect(page.getByText("+7.10%")).toBeVisible();
    // worst_segment_return: -1.8 → "-1.80%"
    await expect(page.getByText("-1.80%")).toBeVisible();
  });

  test("walk-forward renders a bar chart with segment bars", async ({ page }) => {
    await page.route("**/api/backtests/1/walk-forward**", async (r) => {
      await r.fulfill({ json: MOCK_WALK_FORWARD_RESULT });
    });

    await page.getByRole("button", { name: /^Run$/i }).first().click();

    // recharts renders an SVG — the chart area should be visible
    await expect(page.locator("svg").first()).toBeVisible();
    // Segment labels Seg 1 … Seg 5 appear as XAxis ticks
    await expect(page.getByText("Seg 1")).toBeVisible();
    await expect(page.getByText("Seg 5")).toBeVisible();
  });

  test("walk-forward button shows 'Running…' while pending", async ({ page }) => {
    // Delay the response to observe the pending label
    await page.route("**/api/backtests/1/walk-forward**", async (r) => {
      await new Promise((res) => setTimeout(res, 300));
      await r.fulfill({ json: MOCK_WALK_FORWARD_RESULT });
    });

    const runBtn = page.getByRole("button", { name: /^Run$/i }).first();
    await runBtn.click();
    await expect(page.getByText("Running…").first()).toBeVisible();
  });

  test("walk-forward API error shows error box", async ({ page }) => {
    await page.route("**/api/backtests/1/walk-forward**", async (r) => {
      await r.fulfill({
        status: 422,
        json: { detail: "Insufficient data for walk-forward (120 bars available)" },
      });
    });

    await page.getByRole("button", { name: /^Run$/i }).first().click();
    await expect(page.getByText(/Insufficient data for walk-forward/i)).toBeVisible();
  });

  test("walk-forward result with backend error field shows error", async ({ page }) => {
    await page.route("**/api/backtests/1/walk-forward**", async (r) => {
      await r.fulfill({
        json: {
          ...MOCK_WALK_FORWARD_RESULT,
          error: "no data",
          segments: [],
        },
      });
    });

    await page.getByRole("button", { name: /^Run$/i }).first().click();
    await expect(page.getByText("no data")).toBeVisible();
  });
});

test.describe("ValidationPanel – Monte Carlo", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Backtests/i }).click();
    await page.getByText("mean_reversion").nth(1).click();
  });

  test("Monte Carlo panel title and description are visible", async ({ page }) => {
    await expect(page.getByText(/Monte Carlo/i)).toBeVisible();
    await expect(page.getByText(/Shuffles the trade sequence/i)).toBeVisible();
  });

  test("runs select has expected options", async ({ page }) => {
    // The MC runs select is inside the Monte Carlo panel (second panel)
    const mcPanel = page.getByText(/Monte Carlo/).locator("..").locator("..");
    const runsSelect = mcPanel.locator("select").first();
    await expect(runsSelect.locator("option[value='100']")).toBeAttached();
    await expect(runsSelect.locator("option[value='1000']")).toBeAttached();
    await expect(runsSelect.locator("option[value='10000']")).toBeAttached();
  });

  test("can change runs count before running", async ({ page }) => {
    const mcPanel = page.getByText(/Monte Carlo/).locator("..").locator("..");
    const runsSelect = mcPanel.locator("select").first();
    await runsSelect.selectOption("5000");
    await expect(runsSelect).toHaveValue("5000");
  });

  test("Run Monte Carlo fires API and renders metrics", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await r.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    });

    // Click second Run button (Monte Carlo)
    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();

    await expect(page.getByText(/Mean return/i)).toBeVisible();
    await expect(page.getByText(/Prob profit/i)).toBeVisible();
    await expect(page.getByText(/Median DD/i)).toBeVisible();
    await expect(page.getByText(/P5 \(worst 5%\)/i)).toBeVisible();
    await expect(page.getByText(/P95 \(best 5%\)/i)).toBeVisible();
    await expect(page.getByText(/P95 max DD/i)).toBeVisible();
  });

  test("Monte Carlo shows correct values from mock", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await r.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    });

    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();

    // mean_return_pct: 11.8 → "+11.80%"
    await expect(page.getByText("+11.80%")).toBeVisible();
    // probability_profit: 91.4 → "91.4%"
    await expect(page.getByText("91.4%")).toBeVisible();
    // median drawdown: 4.80
    await expect(page.getByText(/-4\.80%/)).toBeVisible();
    // P5: 4.2 → "4.20%"
    await expect(page.getByText(/4\.20%/)).toBeVisible();
    // P95: 19.6 → "+19.60%"
    await expect(page.getByText(/\+19\.60%/)).toBeVisible();
  });

  test("Monte Carlo renders histogram bar chart", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await r.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    });

    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();
    // SVG chart should be present
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("note text from backend is shown", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await r.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    });

    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();
    await expect(page.getByText(/Trade sequence shuffled/i)).toBeVisible();
  });

  test("Monte Carlo button shows 'Running…' while pending", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await new Promise((res) => setTimeout(res, 300));
      await r.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    });

    const mcRunBtn = page.getByRole("button", { name: /^Run$/i }).nth(1);
    await mcRunBtn.click();
    await expect(page.getByText("Running…").first()).toBeVisible();
  });

  test("Monte Carlo API error shows error box", async ({ page }) => {
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await r.fulfill({
        status: 422,
        json: { detail: "No trades found for this backtest job" },
      });
    });

    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();
    await expect(page.getByText(/No trades found for this backtest job/i)).toBeVisible();
  });

  test("probability of profit is displayed as percentage not fraction", async ({ page }) => {
    // probability_profit comes back as 91.4 (0-100), not 0.914.
    // A regression guard: we should see "91.4%" not "9140%"
    await page.route("**/api/backtests/1/monte-carlo**", async (r) => {
      await r.fulfill({ json: { ...MOCK_MONTE_CARLO_RESULT, probability_profit: 91.4 } });
    });

    await page.getByRole("button", { name: /^Run$/i }).nth(1).click();
    await expect(page.getByText("91.4%")).toBeVisible();
    await expect(page.getByText("9140%")).not.toBeVisible();
  });
});

test.describe("PriceChart – trade markers", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Backtests/i }).click();
    await page.getByText("mean_reversion").nth(1).click();
  });

  test("Price Chart section header is visible", async ({ page }) => {
    await expect(page.getByText(/Price Chart/i)).toBeVisible();
  });

  test("price chart legend shows all three trade types", async ({ page }) => {
    await expect(page.getByText(/Buy \/ Cover/i)).toBeVisible();
    await expect(page.getByText(/Short/i)).toBeVisible();
    await expect(page.getByText(/Sell/i)).toBeVisible();
  });

  test("price chart renders SVG canvas when OHLCV data is available", async ({ page }) => {
    // MOCK_OHLCV is returned by default from mockAllRoutes
    // We need to wait for the chart to load
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("loading placeholder shown while OHLCV is fetching", async ({ page }) => {
    // Delay the OHLCV response
    await page.route("**/api/provider/ohlcv/**", async (r) => {
      await new Promise((res) => setTimeout(res, 500));
      await r.fulfill({ json: [] });
    });

    await page.goto("/");
    await page.getByRole("button", { name: /Backtests/i }).click();
    await page.getByText("mean_reversion").nth(1).click();

    await expect(page.getByText(/Loading price data/i)).toBeVisible();
  });
});
