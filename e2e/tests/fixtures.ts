/**
 * Shared fixtures and helpers for all E2E tests.
 *
 * Strategy: most tests use Playwright's route() API to intercept /api/*
 * calls and return deterministic mock responses — no live exchange required.
 * Tests marked `@live` skip mocking and hit the real running API.
 */
import { test as base, expect, type Page, type Route } from "@playwright/test";

// ── Mock payloads ──────────────────────────────────────────────────────────

export const MOCK_STRATEGIES = [
  { name: "mean_reversion", description: "Z-score mean reversion", params: { ema_period: 20 }, param_grid: {} },
  { name: "ema_crossover", description: "EMA crossover momentum", params: { fast_ema: 9 }, param_grid: {} },
  { name: "bollinger_dca", description: "Bollinger DCA", params: { bb_period: 20 }, param_grid: {} },
  { name: "breakout", description: "Donchian channel breakout", params: { channel_period: 20 }, param_grid: {} },
  { name: "macd_rsi", description: "MACD + RSI confluence", params: { macd_fast: 12 }, param_grid: {} },
  { name: "rsi_mean_revert", description: "RSI oversold/overbought", params: { rsi_period: 14 }, param_grid: {} },
  { name: "grid_dynamic", description: "Dynamic grid trading", params: { grid_levels: 5 }, param_grid: {} },
  { name: "trend_following", description: "ADX trend filter", params: { fast_ema: 21 }, param_grid: {} },
  { name: "trend_following_ls", description: "Trend following long/short", params: { fast_ema: 21 }, param_grid: {} },
  { name: "scalping", description: "RSI+BB scalping", params: { rsi_period: 7 }, param_grid: {} },
  { name: "momentum_burst", description: "Momentum burst long/short", params: { surge_pct: 1.5 }, param_grid: {} },
  { name: "bb_squeeze", description: "Bollinger Band squeeze", params: { bb_period: 20 }, param_grid: {} },
  { name: "supertrend", description: "Supertrend ATR-based", params: { atr_period: 10 }, param_grid: {} },
  { name: "vwap_bounce", description: "VWAP mean reversion", params: { vwap_period: 20 }, param_grid: {} },
  { name: "stoch_rsi", description: "Stochastic RSI with EMA trend", params: { rsi_period: 14 }, param_grid: {} },
  { name: "ichimoku", description: "Ichimoku Cloud", params: { tenkan_period: 9 }, param_grid: {} },
  { name: "supertrend_pro", description: "Multi-timeframe Supertrend", params: { atr_fast: 7 }, param_grid: {} },
  { name: "funding_rate_arb", description: "Funding rate arbitrage", params: { fast_ema: 20 }, param_grid: {} },
  { name: "threshold_rebalance", description: "Threshold rebalancing", params: { rebalance_threshold: 8.0 }, param_grid: {} },
];

export const MOCK_BACKTEST_PENDING = {
  id: 1, strategy: "mean_reversion", pair: "BTC/USDT", period: "6m",
  timeframe: "1h", status: "pending", error_msg: null,
  metrics: null, equity_curve: null, equity_timestamps: null, params: null,
  created_at: "2026-01-01T00:00:00", started_at: null, finished_at: null,
};

export const MOCK_BACKTEST_DONE = {
  ...MOCK_BACKTEST_PENDING,
  status: "done",
  started_at: "2026-01-01T00:00:01",
  finished_at: "2026-01-01T00:00:10",
  params: { ema_period: 20 },
  metrics: {
    total_return_pct: 12.4,
    sharpe_ratio: 1.85,
    sortino_ratio: 2.1,
    max_drawdown_pct: 4.2,
    win_rate_pct: 64.3,
    profit_factor: 2.1,
    total_trades: 47,
    avg_trade_duration_bars: 8.2,
    expectancy_usd: 0.026,
    capital_utilization_pct: 23.5,
    final_capital: 22.48,
    initial_capital: 20,
  },
  equity_curve: Array.from({ length: 50 }, (_, i) => 20 + i * 0.05),
  equity_timestamps: Array.from({ length: 50 }, (_, i) =>
    `2026-01-${String(i + 1).padStart(2, "0")}T00:00:00`
  ),
};

export const MOCK_TRADES = [
  {
    id: 1, source: "backtest", backtest_job_id: 1, type: "buy",
    pair: "BTC/USDT", strategy: "mean_reversion", price: 42000,
    qty: 0.000119, fee: 0.005, pnl: null, pnl_pct: null,
    reason: "z-score entry -1.8 (level 1/3)", duration_bars: null,
    avg_cost: null, timestamp: "2026-01-05T08:00:00", logged_at: "2026-01-05T08:00:00",
  },
  {
    id: 2, source: "backtest", backtest_job_id: 1, type: "sell",
    pair: "BTC/USDT", strategy: "mean_reversion", price: 43200,
    qty: 0.000119, fee: 0.005, pnl: 0.1368, pnl_pct: 2.86,
    reason: "z-score exit 0.6 >= 0.5", duration_bars: 12,
    avg_cost: 42000, timestamp: "2026-01-05T20:00:00", logged_at: "2026-01-05T20:00:00",
  },
];

export const MOCK_TRADE_STATS = {
  total_trades: 47, win_rate_pct: 64.3,
  total_pnl: 2.48, avg_pnl: 0.053,
  best_trade: 0.42, worst_trade: -0.18,
};

export const MOCK_BOT_IDLE = {
  running: false, mode: null, strategy: null,
  pairs: [], started_at: null, error: null,
};

export const MOCK_BOT_RUNNING = {
  running: true, mode: "paper", strategy: "mean_reversion",
  pairs: ["BTC/USDT"], started_at: "2026-01-01T10:00:00", error: null,
};

export const MOCK_PROVIDER_STATUS = {
  exchange: "bybit", testnet: true,
  has_api_key: false, has_secret: false,
  pairs: ["BTC/USDT", "ETH/USDT"], active_strategy: "mean_reversion",
};

export const MOCK_WALLET_SUMMARY = {
  total_equity: 21.34,
  balance_usdt: 18.50,
  positions_value: 2.84,
  positions: { "BTC/USDT": { qty: 0.000066, avg_cost: 43000 } },
  pnl: 1.34,
  pnl_pct: 6.7,
  snapshots_count: 12,
};

export const MOCK_WALLET_HISTORY = Array.from({ length: 12 }, (_, i) => ({
  id: i + 1,
  source: "paper",
  balance_usdt: 20 - i * 0.1,
  positions_value: i * 0.2,
  total_equity: 20 + i * 0.1,
  positions: {},
  timestamp: `2026-01-${String(i + 1).padStart(2, "0")}T12:00:00`,
}));

export const MOCK_CONNECTION_OK = {
  exchange: "bybit", testnet: true,
  public_ok: true, auth_ok: null,
  ticker: { pair: "BTC/USDT", last: 65432.10, bid: 65430, ask: 65434 },
  balance: null, error: null,
};

export const MOCK_PRESETS = [
  {
    id: "conservative",
    label: "Conservative",
    description: "Capital preservation with steady yield via delta-neutral funding rate arb.",
    target_apy: "8–15%",
    max_drawdown_target: 5,
    recommended_capital_usd: 100,
    strategy: "funding_rate_arb",
    pairs: ["BTC/USDT", "ETH/USDT"],
    timeframe: "4h",
    period: "6m",
    leverage: 1.0,
    amount_per_trade: 10,
    max_concurrent_positions: 2,
    daily_loss_stop_pct: 3.0,
    use_futures: true,
    risk: { position_sizing: "fixed", atr_stop_enabled: false },
  },
  {
    id: "balanced",
    label: "Balanced",
    description: "Trend-following with moderate leverage. Long/short futures for adaptability.",
    target_apy: "20–40%",
    max_drawdown_target: 12,
    recommended_capital_usd: 50,
    strategy: "trend_following_ls",
    pairs: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    timeframe: "4h",
    period: "1y",
    leverage: 1.5,
    amount_per_trade: 10,
    max_concurrent_positions: 3,
    daily_loss_stop_pct: 5.0,
    use_futures: true,
    risk: { position_sizing: "atr_volatility", atr_stop_enabled: true, atr_stop_mult: 2.0 },
  },
  {
    id: "aggressive",
    label: "Aggressive",
    description: "High-frequency Stochastic RSI with 2.5× leverage. Best on NEAR/USDT 4h.",
    target_apy: "60–120%",
    max_drawdown_target: 20,
    recommended_capital_usd: 20,
    strategy: "stoch_rsi",
    pairs: ["NEAR/USDT", "SOL/USDT", "BTC/USDT"],
    timeframe: "4h",
    period: "6m",
    leverage: 2.5,
    amount_per_trade: 15,
    max_concurrent_positions: 3,
    daily_loss_stop_pct: 8.0,
    use_futures: true,
    risk: { position_sizing: "atr_volatility", atr_stop_enabled: true, atr_stop_mult: 2.0 },
  },
  {
    id: "scalper",
    label: "Scalper",
    description: "Momentum bursts on 1h candles — many quick trades, tight stops.",
    target_apy: "30–80%",
    max_drawdown_target: 15,
    recommended_capital_usd: 30,
    strategy: "momentum_burst",
    pairs: ["BTC/USDT", "ETH/USDT"],
    timeframe: "1h",
    period: "3m",
    leverage: 1.5,
    amount_per_trade: 10,
    max_concurrent_positions: 4,
    daily_loss_stop_pct: 6.0,
    use_futures: true,
    risk: { position_sizing: "atr_volatility", atr_stop_enabled: true, atr_stop_mult: 1.5 },
  },
  {
    id: "swing",
    label: "Swing",
    description: "Weekly swings using dual Supertrend Pro — low trade frequency, high R:R.",
    target_apy: "25–50%",
    max_drawdown_target: 18,
    recommended_capital_usd: 50,
    strategy: "supertrend_pro",
    pairs: ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    timeframe: "1d",
    period: "2y",
    leverage: 1.5,
    amount_per_trade: 10,
    max_concurrent_positions: 2,
    daily_loss_stop_pct: 4.0,
    use_futures: true,
    risk: { position_sizing: "atr_volatility", atr_stop_enabled: true, atr_stop_mult: 2.5 },
  },
];

export const MOCK_ACTIVE_PRESET = {
  preset_id: "aggressive",
  preset: MOCK_PRESETS[2],
  risk: { leverage: 2.5, max_concurrent_positions: 3, daily_loss_stop_pct: 8.0 },
};

export const MOCK_WALK_FORWARD_RESULT = {
  pair: "BTC/USDT",
  strategy: "mean_reversion",
  n_segments: 5,
  period: "1y",
  timeframe: "4h",
  total_bars: 2190,
  walk_forward_bars: 1752,
  holdout_bars: 438,
  segments: [
    { index: 0, start: "2025-01-01", end: "2025-03-15", bars: 350, trades: 8, return_pct: 4.2, metrics: { sharpe_ratio: 1.4 } },
    { index: 1, start: "2025-03-16", end: "2025-05-28", bars: 350, trades: 11, return_pct: -1.8, metrics: { sharpe_ratio: -0.3 } },
    { index: 2, start: "2025-05-29", end: "2025-08-09", bars: 350, trades: 9, return_pct: 7.1, metrics: { sharpe_ratio: 2.1 } },
    { index: 3, start: "2025-08-10", end: "2025-10-22", bars: 350, trades: 6, return_pct: 3.5, metrics: { sharpe_ratio: 1.2 } },
    { index: 4, start: "2025-10-23", end: "2026-01-03", bars: 352, trades: 13, return_pct: 5.9, metrics: { sharpe_ratio: 1.8 } },
  ],
  aggregate: {
    avg_return_pct: 3.78,
    std_return_pct: 3.12,
    median_return_pct: 4.2,
    consistency_score: 80.0,
    positive_segments: 4,
    avg_sharpe: 1.24,
    avg_max_drawdown_pct: 3.5,
    worst_segment_return: -1.8,
    best_segment_return: 7.1,
  },
};

export const MOCK_MONTE_CARLO_RESULT = {
  n_runs: 1000,
  original_return_pct: 12.4,
  mean_return_pct: 11.8,
  median_return_pct: 12.1,
  std_return_pct: 4.3,
  percentile_5_pct: 4.2,
  percentile_95_pct: 19.6,
  max_drawdown_distribution: {
    mean: 5.1,
    median: 4.8,
    percentile_95: 9.3,
  },
  probability_profit: 91.4,
  histogram: [
    { bucket_pct: -5, count: 12 },
    { bucket_pct: 0, count: 76 },
    { bucket_pct: 5, count: 198 },
    { bucket_pct: 10, count: 312 },
    { bucket_pct: 15, count: 248 },
    { bucket_pct: 20, count: 154 },
  ],
  note: "Trade sequence shuffled 1000× using backtest trades.",
};

export const MOCK_OHLCV = Array.from({ length: 100 }, (_, i) => ({
  t: new Date("2026-01-01").getTime() + i * 4 * 60 * 60 * 1000,
  o: 65000 + Math.sin(i * 0.3) * 500,
  h: 65000 + Math.sin(i * 0.3) * 500 + 200,
  l: 65000 + Math.sin(i * 0.3) * 500 - 200,
  c: 65000 + Math.sin(i * 0.3 + 0.1) * 500,
  v: 1000 + i * 10,
}));

// ── Custom fixture with pre-wired mocks ───────────────────────────────────

type Fixtures = {
  mockedPage: Page;
};

export const test = base.extend<Fixtures>({
  mockedPage: async ({ page }, use) => {
    // Default mock for all /api/* routes
    await mockAllRoutes(page);
    await use(page);
  },
});

export { expect };

// ── Route mocking helpers ──────────────────────────────────────────────────

// Match only real API calls (HTTP to :8000 or the Vite proxy path /api/*)
// We use a URL predicate to avoid matching Vite's own module requests like /@vite/...
function isApiCall(url: string): boolean {
  return url.includes("localhost:8000/api/") ||
         (url.includes("localhost:5173/api/") && !url.includes("@"));
}

export async function mockAllRoutes(page: Page) {
  // Use a single catch-all with URL predicate, then route based on path
  await page.route((url) => isApiCall(url.toString()), async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    // Strip query-string before matching so ?n_segments=5 doesn't break equality checks
    const path = url.replace(/^.*\/(api\/)/, "$1").split("?")[0];

    if (path === "api/strategies") {
      return route.fulfill({ json: MOCK_STRATEGIES });
    }
    if (path === "api/backtests" && method === "POST") {
      return route.fulfill({ status: 202, json: MOCK_BACKTEST_PENDING });
    }
    if (path === "api/backtests") {
      return route.fulfill({ json: [MOCK_BACKTEST_DONE] });
    }
    if (path === "api/backtests/1" && method === "DELETE") {
      return route.fulfill({ status: 204, body: "" });
    }
    if (path === "api/backtests/1") {
      return route.fulfill({ json: MOCK_BACKTEST_DONE });
    }
    if (path === "api/trades/stats") {
      return route.fulfill({ json: MOCK_TRADE_STATS });
    }
    if (path.startsWith("api/trades")) {
      return route.fulfill({ json: MOCK_TRADES });
    }
    if (path === "api/bot/status") {
      return route.fulfill({ json: MOCK_BOT_IDLE });
    }
    if (path === "api/bot/start") {
      return route.fulfill({ json: { ok: true, detail: "paper bot started" } });
    }
    if (path === "api/bot/stop") {
      return route.fulfill({ json: { ok: true, detail: "Bot stopped" } });
    }
    if (path.startsWith("api/wallet/summary")) {
      return route.fulfill({ json: MOCK_WALLET_SUMMARY });
    }
    if (path.startsWith("api/wallet/history")) {
      return route.fulfill({ json: MOCK_WALLET_HISTORY });
    }
    if (path === "api/provider/status") {
      return route.fulfill({ json: MOCK_PROVIDER_STATUS });
    }
    if (path === "api/provider/test") {
      return route.fulfill({ json: MOCK_CONNECTION_OK });
    }
    if (path.startsWith("api/provider/ticker/")) {
      const pair = decodeURIComponent(path.replace("api/provider/ticker/", ""));
      return route.fulfill({ json: { pair, last: 65000, bid: 64998, ask: 65002, volume: 1234, change_pct: 1.23 } });
    }
    if (path === "api/provider/config") {
      return route.fulfill({ json: { ok: true, updated: ["exchange"] } });
    }
    if (path.startsWith("api/provider/ohlcv/")) {
      return route.fulfill({ json: MOCK_OHLCV });
    }
    if (path === "api/presets/active/current") {
      return route.fulfill({ json: MOCK_ACTIVE_PRESET });
    }
    if (path.match(/^api\/presets\/[^/]+\/apply$/) && method === "POST") {
      const presetId = path.split("/")[2];
      return route.fulfill({ json: { ok: true, preset_id: presetId, changes: { strategy: presetId } } });
    }
    if (path === "api/presets") {
      return route.fulfill({ json: MOCK_PRESETS });
    }
    if (path.match(/^api\/backtests\/\d+\/walk-forward$/) && method === "POST") {
      return route.fulfill({ json: MOCK_WALK_FORWARD_RESULT });
    }
    if (path.match(/^api\/backtests\/\d+\/monte-carlo$/) && method === "POST") {
      return route.fulfill({ json: MOCK_MONTE_CARLO_RESULT });
    }
    if (path === "api/health") {
      return route.fulfill({ json: { status: "ok" } });
    }
    // Fallback — pass through unknown routes
    return route.continue();
  });
}
