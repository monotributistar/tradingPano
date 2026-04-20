/**
 * Presets / Investment Profiles E2E tests
 *
 * Verifies the Presets page renders all 5 profiles, shows the active preset
 * badge, and that applying a preset fires the correct API call and shows a
 * success toast.
 */
import { test, expect, mockAllRoutes, MOCK_PRESETS, MOCK_ACTIVE_PRESET } from "./fixtures";

test.describe("Presets – Investment Profiles", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Presets/i }).click();
  });

  test("shows Investment Profiles heading", async ({ page }) => {
    await expect(page.getByText("Investment Profiles")).toBeVisible();
  });

  test("renders all 5 preset cards", async ({ page }) => {
    const labels = ["Conservative", "Balanced", "Aggressive", "Scalper", "Swing"];
    for (const label of labels) {
      await expect(page.getByText(label).first()).toBeVisible();
    }
  });

  test("each card shows target APY and max drawdown", async ({ page }) => {
    // Conservative card
    await expect(page.getByText("8–15%")).toBeVisible();
    await expect(page.getByText("5%")).toBeVisible();
    // Aggressive card
    await expect(page.getByText("60–120%")).toBeVisible();
    await expect(page.getByText("20%")).toBeVisible();
  });

  test("each card shows strategy name, timeframe and leverage", async ({ page }) => {
    // funding_rate_arb on Conservative
    await expect(page.getByText("funding_rate_arb")).toBeVisible();
    // stoch_rsi on Aggressive
    await expect(page.getByText("stoch_rsi")).toBeVisible();
    // supertrend_pro on Swing
    await expect(page.getByText("supertrend_pro")).toBeVisible();
    // Timeframes
    await expect(page.getByText("4h").first()).toBeVisible();
    await expect(page.getByText("1d")).toBeVisible();
    // Leverage values
    await expect(page.getByText("1x")).toBeVisible();
    await expect(page.getByText("2.5x")).toBeVisible();
  });

  test("active preset badge is shown for current preset", async ({ page }) => {
    // MOCK_ACTIVE_PRESET has preset_id: "aggressive"
    await expect(page.getByText(/ACTIVE/i).first()).toBeVisible();
    // The header subtitle should mention the active preset id
    await expect(page.getByText(/aggressive/i).first()).toBeVisible();
  });

  test("active card has apply button showing '✓ Applied'", async ({ page }) => {
    // The Aggressive card is active — its button should say ✓ Applied
    const aggressiveCard = page.getByText("Aggressive").locator("..");
    await expect(aggressiveCard.getByRole("button", { name: /Applied/i })).toBeVisible();
  });

  test("inactive cards show 'Apply Preset' button", async ({ page }) => {
    // Conservative and Balanced are not active
    const buttons = page.getByRole("button", { name: /Apply Preset/i });
    await expect(buttons.first()).toBeVisible();
    // There should be 4 inactive preset Apply buttons (5 total − 1 active)
    await expect(buttons).toHaveCount(4);
  });

  test("each card shows pairs badges", async ({ page }) => {
    await expect(page.getByText("BTC/USDT").first()).toBeVisible();
    await expect(page.getByText("NEAR/USDT")).toBeVisible();
  });

  test("each card shows risk controls (daily loss stop, max positions)", async ({ page }) => {
    await expect(page.getByText(/Daily loss stop/i).first()).toBeVisible();
    await expect(page.getByText(/Max positions/i).first()).toBeVisible();
  });

  test("applying a preset fires API and shows success toast", async ({ page }) => {
    let applyCalled = false;
    let appliedPresetId = "";

    await page.route("**/api/presets/*/apply", async (r) => {
      applyCalled = true;
      appliedPresetId = r.request().url().split("/").slice(-2, -1)[0];
      await r.fulfill({ json: { ok: true, preset_id: appliedPresetId, changes: {} } });
    });

    // Re-mock /api/presets/active/current to return no preset initially
    await page.route("**/api/presets/active/current", async (r) => {
      await r.fulfill({ json: { preset_id: null, risk: {} } });
    });

    await page.goto("/");
    await page.getByRole("button", { name: /Presets/i }).click();

    // Click "Apply Preset" on Conservative card (first inactive card)
    await page.getByRole("button", { name: /Apply Preset/i }).first().click();

    await expect(page.getByText(/Preset .* applied/i)).toBeVisible();
  });

  test("apply error shows toast with error detail", async ({ page }) => {
    await page.route("**/api/presets/*/apply", async (r) => {
      await r.fulfill({
        status: 400,
        json: { detail: "Cannot apply preset while bot is running" },
      });
    });
    await page.route("**/api/presets/active/current", async (r) => {
      await r.fulfill({ json: { preset_id: null, risk: {} } });
    });

    await page.goto("/");
    await page.getByRole("button", { name: /Presets/i }).click();
    await page.getByRole("button", { name: /Apply Preset/i }).first().click();

    await expect(page.getByText(/Cannot apply preset while bot is running/i)).toBeVisible();
  });

  test("futures presets show '📈 Futures' badge", async ({ page }) => {
    // All mock presets have use_futures: true
    await expect(page.getByText(/Futures/i).first()).toBeVisible();
  });

  test("ATR stop info shows on presets that have it enabled", async ({ page }) => {
    // Balanced, Aggressive, Scalper, Swing have atr_stop_enabled: true
    await expect(page.getByText(/ATR stop/i).first()).toBeVisible();
  });
});
