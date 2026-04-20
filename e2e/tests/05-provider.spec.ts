/**
 * Provider / Settings page E2E tests
 * Tests exchange config, connection test, live ticker display.
 */
import { test, expect, mockAllRoutes, MOCK_PROVIDER_STATUS, MOCK_CONNECTION_OK } from "./fixtures";

test.describe("Provider Settings", () => {
  test.beforeEach(async ({ page }) => {
    await mockAllRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Provider/i }).click();
  });

  test("shows current connection status card", async ({ page }) => {
    await expect(page.getByText("Current Connection")).toBeVisible();
    await expect(page.getByText("bybit").first()).toBeVisible();
    await expect(page.getByText("TESTNET", { exact: true }).first()).toBeVisible();
  });

  test("shows Not set when no API keys configured", async ({ page }) => {
    await expect(page.getByText("✗ Not set").first()).toBeVisible();
  });

  test("shows Configured when API keys present", async ({ page }) => {
    await page.route("**/api/provider/status", (r) =>
      r.fulfill({
        json: { ...MOCK_PROVIDER_STATUS, has_api_key: true, has_secret: true },
      })
    );
    await page.goto("/");
    await page.getByRole("button", { name: /Provider/i }).click();
    await expect(page.getByText("✓ Configured").first()).toBeVisible();
  });

  test("shows live tickers for BTC, ETH, SOL", async ({ page }) => {
    await expect(page.getByText("BTC/USDT").first()).toBeVisible();
    await expect(page.getByText("ETH/USDT").first()).toBeVisible();
    await expect(page.getByText("SOL/USDT")).toBeVisible();
    // Price displayed
    await expect(page.getByText(/\$65,000|\$65000/).first()).toBeVisible();
  });

  test("Test Connection button calls API and shows result", async ({ page }) => {
    await page.getByTestId("test-connection-btn").click();
    await expect(page.getByTestId("connection-result")).toBeVisible({ timeout: 8000 });
    await expect(page.getByText("✓ Connection Successful")).toBeVisible();
    await expect(page.getByText(/65,432/)).toBeVisible(); // ticker price from mock
  });

  test("failed connection shows error panel", async ({ page }) => {
    await page.route("**/api/provider/test", (r) =>
      r.fulfill({
        json: {
          exchange: "bybit", testnet: true,
          public_ok: false, auth_ok: false,
          ticker: null,
          error: "NetworkError: connection refused",
        },
      })
    );
    await page.getByTestId("test-connection-btn").click();
    await expect(page.getByText("✗ Connection Failed")).toBeVisible();
    await expect(page.getByText(/connection refused/)).toBeVisible();
  });

  test("exchange select has multiple options", async ({ page }) => {
    const sel = page.getByTestId("exchange-select");
    await expect(sel.locator("option")).toHaveCount(5);
  });

  test("switching to mainnet shows danger warning", async ({ page }) => {
    await expect(page.getByText(/Mainnet.*real funds|real funds/i)).not.toBeVisible();
    await page.getByTestId("mainnet-btn").click();
    await expect(page.getByText(/real funds/i)).toBeVisible();
  });

  test("save config button calls PATCH endpoint", async ({ page }) => {
    let patchBody: unknown = null;
    await page.route("**/api/provider/config", async (r) => {
      patchBody = await r.request().postDataJSON();
      await r.fulfill({ json: { ok: true, updated: ["exchange"] } });
    });

    await page.getByTestId("exchange-select").selectOption("binance");
    await page.getByTestId("save-config-btn").click();
    await expect(page.getByText("✓ Configuration saved")).toBeVisible({ timeout: 8000 });
    expect((patchBody as any)?.exchange).toBe("binance");
  });

  test("API key and secret inputs are password type", async ({ page }) => {
    await expect(page.getByTestId("api-key-input")).toHaveAttribute("type", "password");
    await expect(page.getByTestId("secret-input")).toHaveAttribute("type", "password");
  });

  test("shows exchange testnet setup info table", async ({ page }) => {
    await expect(page.getByText("Supported Exchanges")).toBeVisible();
    await expect(page.locator("strong").getByText("Bybit", { exact: true })).toBeVisible();
    await expect(page.locator("strong").getByText("Binance", { exact: true })).toBeVisible();
  });
});
