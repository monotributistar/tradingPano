/**
 * Bot Control E2E tests
 * Tests start/stop flows, mode selection, pair selection, live warnings.
 */
import { test, expect, mockAllRoutes, MOCK_BOT_IDLE, MOCK_BOT_RUNNING } from "./fixtures";

test.describe("Bot Control", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Bot/i }).click();
  });

  test("shows IDLE status initially", async ({ page }) => {
    // Use exact match to avoid matching the header badge "● IDLE" vs status card "IDLE"
    await expect(page.getByText("IDLE", { exact: true })).toBeVisible();
    await expect(page.getByText(/RUNNING/)).not.toBeVisible();
  });

  test("shows Start Bot form when idle", async ({ page }) => {
    await expect(page.getByText("Start Bot")).toBeVisible();
    // Use exact name to avoid matching "▶ Start paper bot"
    await expect(page.getByRole("button", { name: "📋 Paper", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "⚡ Live", exact: true })).toBeVisible();
  });

  test("strategy dropdown is populated", async ({ page }) => {
    const sel = page.locator("select").first();
    await expect(sel.locator("option")).toHaveCount(3);
  });

  test("BTC/USDT pair button is pre-selected", async ({ page }) => {
    const btcBtn = page.getByRole("button", { name: "BTC/USDT", exact: true });
    await expect(btcBtn).toHaveClass(/pairBtnActive/);
  });

  test("can toggle pairs on/off", async ({ page }) => {
    const ethBtn = page.getByRole("button", { name: "ETH/USDT", exact: true });
    await ethBtn.click();
    await expect(ethBtn).toHaveClass(/pairBtnActive/);

    await ethBtn.click();
    await expect(ethBtn).not.toHaveClass(/pairBtnActive/);
  });

  test("paper mode is default, live mode shows warning", async ({ page }) => {
    await expect(page.getByText(/real trades/i)).not.toBeVisible();
    // Click the Live mode button
    await page.getByRole("button", { name: "⚡ Live", exact: true }).click();
    await expect(page.getByText(/real trades/i)).toBeVisible();
  });

  test("start button disabled when no pairs selected", async ({ page }) => {
    // Deselect BTC/USDT (the only pre-selected pair)
    await page.getByRole("button", { name: "BTC/USDT", exact: true }).click();
    const startBtn = page.getByRole("button", { name: /Start.*bot/i });
    await expect(startBtn).toBeDisabled();
  });

  test("clicking Start Paper Bot calls API and updates status", async ({ page }) => {
    let startCalled = false;
    await page.route("**/api/bot/start", async (r) => {
      startCalled = true;
      await r.fulfill({ json: { ok: true, detail: "paper bot started" } });
    });
    // After start, /status returns running
    await page.route("**/api/bot/status", (r) => r.fulfill({ json: MOCK_BOT_RUNNING }));

    await page.getByRole("button", { name: /Start.*bot/i }).click();
    await expect(page.getByText(/RUNNING/i)).toBeVisible({ timeout: 8000 });
    expect(startCalled).toBe(true);
  });

  test("running state shows stop button and hides form", async ({ page }) => {
    await page.route("**/api/bot/status", (r) => r.fulfill({ json: MOCK_BOT_RUNNING }));
    await page.goto("/");
    await page.getByRole("button", { name: /Bot/i }).click();

    await expect(page.getByRole("button", { name: /Stop Bot/i })).toBeVisible();
    await expect(page.getByText("Start Bot")).not.toBeVisible();
  });

  test("running state shows mode, strategy, pairs", async ({ page }) => {
    await page.route("**/api/bot/status", (r) => r.fulfill({ json: MOCK_BOT_RUNNING }));
    await page.goto("/");
    await page.getByRole("button", { name: /Bot/i }).click();

    // Mode shows in status details, not the mode toggle buttons
    await expect(page.getByText("PAPER", { exact: true })).toBeVisible();
    await expect(page.getByText("mean_reversion", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("BTC/USDT", { exact: true }).first()).toBeVisible();
  });

  test("stop button calls API and returns to idle", async ({ page }) => {
    // Start in running state
    await page.route("**/api/bot/status", (r) => r.fulfill({ json: MOCK_BOT_RUNNING }));
    await page.goto("/");
    await page.getByRole("button", { name: /Bot/i }).click();

    let stopCalled = false;
    await page.route("**/api/bot/stop", async (r) => {
      stopCalled = true;
      await r.fulfill({ json: { ok: true, detail: "Bot stopped" } });
    });
    await page.route("**/api/bot/status", (r) => r.fulfill({ json: MOCK_BOT_IDLE }));

    await page.getByRole("button", { name: /Stop Bot/i }).click();
    await expect(page.getByText("IDLE", { exact: true })).toBeVisible({ timeout: 8000 });
    expect(stopCalled).toBe(true);
  });

  test("error from API shows error message", async ({ page }) => {
    await page.route("**/api/bot/start", (r) =>
      r.fulfill({ status: 409, json: { detail: "Bot already running" } })
    );
    await page.getByRole("button", { name: /Start.*bot/i }).click();
    await expect(page.getByText(/Bot already running/)).toBeVisible();
  });
});
