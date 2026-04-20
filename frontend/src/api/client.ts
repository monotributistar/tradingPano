/**
 * @file client.ts
 * Axios API client and TypeScript type contracts for the CryptoBot API.
 *
 * ## Authentication
 * Every request automatically includes the `X-API-Key` header read from
 * `localStorage.getItem("bot_api_key")`.  Set the key once via the Settings
 * page — it persists across browser sessions.
 *
 * If the key is missing the server returns HTTP 403.  The axios interceptor
 * below catches that and dispatches a custom `"bot:auth-error"` event so the
 * UI can prompt the user to enter their key.
 *
 * ## Contract notes
 * - All timestamps are ISO 8601 UTC strings
 * - All monetary values are in USDT
 * - Candle timestamps (`OHLCVCandle.t`) are Unix milliseconds (UTC)
 * - Trade PnL is absolute USD; pnl_pct is a percentage
 */
import axios from "axios";

// ── API key helpers ────────────────────────────────────────────────────────────

const LS_KEY = "bot_api_key";

export function getApiKey(): string {
  return localStorage.getItem(LS_KEY) ?? "";
}

export function setApiKey(key: string): void {
  localStorage.setItem(LS_KEY, key.trim());
}

export function clearApiKey(): void {
  localStorage.removeItem(LS_KEY);
}

// ── Axios instance ─────────────────────────────────────────────────────────────

export const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Inject X-API-Key on every outgoing request
api.interceptors.request.use((config) => {
  const key = getApiKey();
  if (key) {
    config.headers["X-API-Key"] = key;
  }
  return config;
});

// On 403: dispatch a global event so the Settings panel can open
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 403) {
      window.dispatchEvent(new CustomEvent("bot:auth-error"));
    }
    return Promise.reject(err);
  },
);

// ── Backtest types ─────────────────────────────────────────────────────────────

/**
 * Backtest job record as returned by GET /api/backtests/*.
 *
 * Lifecycle: pending → running → done | error
 * When `status === "done"`, `metrics`, `equity_curve`, and `equity_timestamps` are populated.
 */
export interface BacktestJob {
  id: number;
  strategy: string;
  pair: string;
  /** History window used, e.g. "6m" or "1y" */
  period: string;
  /** Candle size used, e.g. "1h" or "4h" */
  timeframe: string;
  status: "pending" | "running" | "done" | "error";
  error_msg?: string;
  metrics?: BacktestMetrics;
  /** Portfolio value in USDT per simulated bar (post-warmup) */
  equity_curve?: number[];
  /** ISO 8601 UTC timestamp per equity_curve entry */
  equity_timestamps?: string[];
  params?: Record<string, unknown>;
  created_at: string;
  started_at?: string;
  finished_at?: string;
}

/**
 * Performance metrics returned inside a completed BacktestJob.
 *
 * Return/drawdown values are percentage points (e.g. 27.3 = +27.3%).
 * Monetary values are in USDT.
 */
export interface BacktestMetrics {
  total_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  /** Maximum peak-to-trough drawdown as a positive percentage */
  max_drawdown_pct: number;
  max_drawdown_duration_bars?: number;
  win_rate_pct: number;
  /** Gross profit divided by gross loss (>1 is profitable) */
  profit_factor: number;
  total_trades: number;
  avg_trade_duration_bars: number;
  /** Expected profit per trade in USDT */
  expectancy_usd: number;
  capital_utilization_pct: number;
  final_capital: number;
  initial_capital: number;
  avg_win_usd?: number;
  /** Negative value — average losing trade in USDT */
  avg_loss_usd?: number;
}

/** Valid candle timeframe strings accepted by the backtest API. */
export type Timeframe = "15m" | "30m" | "1h" | "2h" | "4h" | "6h" | "8h" | "12h" | "1d" | "1w";

/** Valid history window strings accepted by the backtest API. */
export type Period =
  | "1w" | "2w" | "1m" | "2m" | "3m" | "6m" | "9m"
  | "1y" | "18m" | "2y" | "3y" | "4y" | "5y";

// ── Trade types ────────────────────────────────────────────────────────────────

/** A single trade record from GET /api/trades. */
export interface Trade {
  id: number;
  /** "backtest" or "paper" or "live" */
  source: string;
  backtest_job_id?: number;
  /** "buy" | "sell" | "short" | "cover" | "sell_eod" | "cover_eod" */
  type: string;
  pair: string;
  strategy?: string;
  price: number;
  qty: number;
  fee: number;
  pnl?: number;
  pnl_pct?: number;
  reason?: string;
  duration_bars?: number;
  avg_cost?: number;
  /** ISO 8601 UTC — the bar timestamp when the trade was executed */
  timestamp?: string;
  logged_at: string;
}

/** Aggregate trade statistics from GET /api/trades/stats. */
export interface TradeStats {
  total_trades: number;
  win_rate_pct: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
}

// ── Bot types ──────────────────────────────────────────────────────────────────

/** Live/paper trading engine status from GET /api/bot/status. */
export interface BotStatus {
  running: boolean;
  /** True when the watchdog detected an unexpected thread death */
  crashed: boolean;
  mode?: string;
  strategy?: string;
  pairs: string[];
  started_at?: string;
  uptime_seconds?: number;
  error?: string;
  /** ID of the active StrategyConfig (null = quick-start / manual) */
  strategy_config_id?: number | null;
  /** Display name of the active StrategyConfig */
  strategy_config_name?: string | null;
}

/** Bot lifecycle audit event from GET /api/bot/events. */
export interface BotEvent {
  id: number;
  /** 'start' | 'stop' | 'crash' | 'halt' | 'resume' | 'watchdog' */
  event_type: string;
  mode?: string;
  strategy?: string;
  pairs?: string[];
  detail?: string;
  positions?: Record<string, unknown>;
  occurred_at: string;
}

// ── Strategy types ─────────────────────────────────────────────────────────────

// ── Strategy Engine types ──────────────────────────────────────────────────────

/** Per-strategy risk defaults from the strategy class. */
export interface RiskProfileData {
  stop_loss_pct: number;
  take_profit_pct: number;
  position_size_pct: number;
}

/**
 * Strategy descriptor from GET /api/strategies.
 *
 * The metadata fields are used by the strategy selector UI to:
 * - Sort strategies by relevance for the selected timeframe
 * - Show market-type and liquidity badges
 * - Power the recommendation engine (Phase 4)
 */
export interface Strategy {
  name: string;
  description: string;
  /** Candle timeframes this strategy is optimised for, e.g. ["1h","4h"] */
  ideal_timeframes: string[];
  /** Minimum recommended backtest window, e.g. "3m" */
  min_period: string;
  /** Market regime suitability */
  market_type: "trending" | "ranging" | "both";
  /** Expected trades per week */
  trade_frequency: "high" | "medium" | "low";
  /** Minimum pair liquidity required */
  min_liquidity: "high" | "medium" | "any";
  params: Record<string, unknown>;
  param_grid: Record<string, unknown[]>;
  /** Timeframes the strategy is most suitable for */
  suitable_timeframes: string[];
  /** Market conditions this strategy works well in */
  suitable_market_conditions: string[];
  /** Recommended leverage multiplier */
  recommended_leverage: number;
  /** Maximum leverage ceiling for this strategy (hard cap: 15×) */
  max_leverage: number;
  /** Default risk parameters for this strategy */
  risk_profile: RiskProfileData;
}

/**
 * A composed strategy configuration stored in the DB.
 * Returned by GET /api/strategy-configs.
 */
export interface StrategyConfigData {
  id: number;
  name: string;
  /** The primary (entry/exit) strategy */
  execution_strategy: string;
  /** Candle timeframe for the execution strategy */
  execution_timeframe: Timeframe;
  /** Optional higher-timeframe trend filter strategy */
  trend_filter_strategy?: string | null;
  /** Timeframe for the trend filter (must be higher than execution_timeframe) */
  trend_filter_timeframe?: Timeframe | null;
  /** Override risk parameters (merged with strategy defaults) */
  risk_profile?: Partial<RiskProfileData> & {
    leverage?: number;
    max_drawdown_pct?: number;
    daily_loss_stop_pct?: number;
  };
  /** Pairs this strategy config is limited to (empty = all pairs) */
  pairs?: string[];
  notes?: string;
  created_at: string;
  updated_at: string;
}

/** Payload for POST /api/strategy-configs. */
export type StrategyConfigCreate = Omit<StrategyConfigData, "id" | "created_at" | "updated_at">;

/** Response from POST /api/strategy-configs/{id}/activate. */
export interface ActivateStrategyConfigResult {
  ok: boolean;
  active_strategy: string;
  active_config_id: number;
}

// ── Provider types ─────────────────────────────────────────────────────────────

/** Exchange connection config from GET /api/provider/status. */
export interface ProviderStatus {
  exchange: string;
  testnet: boolean;
  has_api_key: boolean;
  has_secret: boolean;
  pairs: string[];
  active_strategy: string;
}

/** Result of POST /api/provider/test. */
export interface ConnectionResult {
  exchange: string;
  testnet: boolean;
  public_ok: boolean;
  auth_ok: boolean | null;
  ticker?: { pair: string; last: number; bid: number; ask: number } | null;
  balance?: Record<string, number>;
  error?: string | null;
}

/** Live price ticker from GET /api/provider/ticker/{pair}. */
export interface Ticker {
  pair: string;
  last: number;
  bid: number;
  ask: number;
  volume: number;
  change_pct: number;
}

/**
 * OHLCV candle from GET /api/provider/ohlcv/{pair}.
 * `t` is a Unix millisecond timestamp (UTC).
 */
export interface OHLCVCandle {
  /** Unix milliseconds (UTC) */
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

// ── Wallet types ───────────────────────────────────────────────────────────────

/** Portfolio snapshot from GET /api/wallet/history. */
export interface WalletSnapshot {
  id: number;
  source: string;
  balance_usdt: number;
  positions_value: number;
  total_equity: number;
  positions: Record<string, { qty: number; avg_cost: number }>;
  timestamp: string;
}

/** Aggregate wallet summary from GET /api/wallet/summary. */
export interface WalletSummary {
  total_equity: number | null;
  balance_usdt: number | null;
  positions_value: number | null;
  positions: Record<string, { qty: number; avg_cost: number }>;
  pnl: number | null;
  pnl_pct: number | null;
  snapshots_count: number;
}

// ── Preset types ───────────────────────────────────────────────────────────────

/** Investment profile preset from GET /api/presets. */
export interface Preset {
  id: string;
  label: string;
  description: string;
  target_apy: string;
  max_drawdown_target: number;
  recommended_capital_usd: number;
  strategy: string;
  pairs: string[];
  timeframe: string;
  period: string;
  leverage: number;
  amount_per_trade: number;
  max_concurrent_positions: number;
  daily_loss_stop_pct: number;
  use_futures: boolean;
  risk: {
    position_sizing?: string;
    atr_stop_enabled?: boolean;
    atr_stop_mult?: number;
  };
}

/** Result of POST /api/presets/{id}/apply. */
export interface ApplyPresetResult {
  ok: boolean;
  preset_id: string;
  changes: Record<string, unknown>;
}

// ── Validation types ───────────────────────────────────────────────────────────

/** Single out-of-sample segment in a walk-forward result. */
export interface WalkForwardSegment {
  index: number;
  start: string;
  end: string;
  bars?: number;
  trades: number;
  return_pct: number;
  metrics?: Record<string, number>;
  error?: string;
}

/** Full walk-forward validation result from POST /api/backtests/{id}/walk-forward. */
export interface WalkForwardResult {
  pair: string;
  strategy: string;
  n_segments: number;
  period?: string;
  segments: WalkForwardSegment[];
  aggregate: {
    avg_return_pct: number;
    std_return_pct: number;
    consistency_score: number;
    avg_sharpe: number;
    worst_segment_return: number;
    best_segment_return: number;
    avg_max_drawdown_pct?: number;
  };
  error?: string;
}

/** Monte Carlo simulation result from POST /api/backtests/{id}/monte-carlo. */
export interface MonteCarloResult {
  n_runs: number;
  original_return_pct: number;
  mean_return_pct: number;
  median_return_pct: number;
  std_return_pct: number;
  percentile_5_pct: number;
  percentile_95_pct: number;
  max_drawdown_distribution: {
    mean: number;
    median: number;
    percentile_95: number;
  };
  /** Probability of profit as a percentage (0–100) */
  probability_profit: number;
  histogram: Array<{ bucket_pct: number; count: number }>;
  note?: string;
}

// ── Market Scanner types ───────────────────────────────────────────────────────

/** Strategy suggestion returned inside a MarketSnapshot. */
export interface StrategySuggestion {
  name: string;
  reason: string;
}

/**
 * Per-pair market metrics from GET /api/market/scanner.
 *
 * All percentage values are in percentage points (e.g. 2.5 = +2.5%).
 * `volume_24h_usd` is approximate (sum of close × volume over last 24 bars).
 */
export interface MarketSnapshot {
  pair: string;
  price: number;

  /** Rolling price change over the last candle (= 1h when timeframe=1h) */
  change_1h_pct: number;
  change_4h_pct: number;
  change_24h_pct: number;
  change_7d_pct: number;

  /** Approximate 24-hour volume in USDT */
  volume_24h_usd: number;

  /** ATR(14) as percentage of price — normalised volatility measure */
  atr_pct: number;
  /** Volatility regime derived from ATR% */
  volatility: "low" | "medium" | "high";

  /** ADX(14) directional movement strength (0–100, >25 = trending) */
  adx: number;
  /** RSI(14) momentum oscillator (0–100) */
  rsi: number;
  /** Detected market regime */
  market_type: "trending" | "ranging" | "mixed";
  /** Detected price direction */
  trend_direction: "up" | "down" | "sideways";

  /** 14-day price range extremes */
  support: number;
  resistance: number;
  /** 0 = at support, 100 = at resistance */
  price_in_range_pct: number;

  /** Top 3 strategy suggestions for current market conditions */
  top_strategies: StrategySuggestion[];
}

/** High-level market overview from GET /api/market/summary. */
export interface MarketSummary {
  scanned_pairs: number;
  market_mood: "bullish" | "bearish" | "neutral";
  gainers: number;
  losers: number;
  avg_atr_pct: number;
  trending_count: number;
  ranging_count: number;
  top_gainer: { pair: string; change_24h_pct: number; price: number };
  top_loser: { pair: string; change_24h_pct: number; price: number };
  most_volatile: { pair: string; atr_pct: number; volatility: string };
  highest_volume: { pair: string; volume_24h_usd: number };
  error?: string;
}

// ── API functions ──────────────────────────────────────────────────────────────

/** Fetch all strategies with metadata. */
export const fetchStrategies = () =>
  api.get<Strategy[]>("/strategies").then((r) => r.data);

/** List backtest jobs, optionally filtered by strategy or pair. */
export const fetchBacktests = (params?: { strategy?: string; pair?: string }) =>
  api.get<BacktestJob[]>("/backtests", { params }).then((r) => r.data);

/** Get a single backtest job by ID (includes metrics + equity curve). */
export const fetchBacktest = (id: number) =>
  api.get<BacktestJob>(`/backtests/${id}`).then((r) => r.data);

/**
 * Submit a new backtest job. Returns immediately with status='pending'.
 * Poll `fetchBacktest(id)` until `status === 'done'`.
 */
export const createBacktest = (body: {
  strategy: string;
  pair: string;
  period: string;
  timeframe: string;
}) => api.post<BacktestJob>("/backtests", body).then((r) => r.data);

/** Delete a backtest job and all its associated trades. */
export const deleteBacktest = (id: number) => api.delete(`/backtests/${id}`);

/** Fetch trades, filterable by job ID, pair, strategy, source, and type. */
export const fetchTrades = (params?: {
  pair?: string;
  strategy?: string;
  source?: string;
  type?: string;
  backtest_job_id?: number;
  limit?: number;
}) => api.get<Trade[]>("/trades", { params }).then((r) => r.data);

/** Aggregate trade statistics. */
export const fetchTradeStats = (params?: { source?: string; strategy?: string }) =>
  api.get<TradeStats>("/trades/stats", { params }).then((r) => r.data);

/** Per-strategy performance breakdown from GET /api/trades/strategy-performance. */
export interface StrategyPerf {
  strategy:      string;
  sources:       string[];
  total_trades:  number;
  wins:          number;
  losses:        number;
  win_rate_pct:  number;
  total_pnl:     number;
  avg_pnl:       number;
  avg_win:       number;
  avg_loss:      number;
  best_trade:    number;
  worst_trade:   number;
  profit_factor: number;
  last_trade_at?: string;
}

/** Fetch per-strategy P&L breakdown. */
export const fetchStrategyPerformance = (params?: { source?: string }) =>
  api.get<StrategyPerf[]>("/trades/strategy-performance", { params }).then((r) => r.data);

/** Get the live/paper trading engine status. */
export const fetchBotStatus = () =>
  api.get<BotStatus>("/bot/status").then((r) => r.data);

/** Parameters for POST /api/bot/start. */
export interface BotStartParams {
  mode: "paper" | "live";
  strategy: string;
  pairs: string[];
  restore?: boolean;
  /** Optional saved StrategyConfig ID to use (overrides strategy/pairs/timeframe/risk). */
  strategy_config_id?: number | null;
}

/** Start the trading engine (paper or live). */
export const startBot = (body: BotStartParams) =>
  api.post<{ ok: boolean; detail: string }>("/bot/start", body).then((r) => r.data);

/** Stop the trading engine. */
export const stopBot = () => api.post("/bot/stop").then((r) => r.data);

/** Fetch bot lifecycle audit events. */
export const fetchBotEvents = (limit = 50) =>
  api.get<BotEvent[]>("/bot/events", { params: { limit } }).then((r) => r.data);

/** Fetch the application config (secrets stripped). */
export const fetchConfig = () =>
  api.get<Record<string, unknown>>("/config").then((r) => r.data);

/** Fetch wallet portfolio history snapshots. */
export const fetchWalletHistory = (params?: { source?: string; limit?: number }) =>
  api.get<WalletSnapshot[]>("/wallet/history", { params }).then((r) => r.data);

/** Fetch aggregated wallet summary. */
export const fetchWalletSummary = (params?: { source?: string }) =>
  api.get<WalletSummary>("/wallet/summary", { params }).then((r) => r.data);

/** Fetch exchange connection status. */
export const fetchProviderStatus = () =>
  api.get<ProviderStatus>("/provider/status").then((r) => r.data);

/** Test exchange connectivity (public + optional auth). */
export const testConnection = () =>
  api.post<ConnectionResult>("/provider/test").then((r) => r.data);

/** Fetch current price ticker for a pair. */
export const fetchTicker = (pair: string) =>
  api.get<Ticker>(`/provider/ticker/${pair}`).then((r) => r.data);

/** Fetch OHLCV candles. `t` is Unix milliseconds (UTC). */
export const fetchOHLCV = (
  pair: string,
  params?: { timeframe?: string; period?: string; limit?: number },
) => api.get<OHLCVCandle[]>(`/provider/ohlcv/${pair}`, { params }).then((r) => r.data);

/** Update exchange configuration (persisted to config.yaml). */
export const updateProviderConfig = (patch: {
  exchange?: string;
  testnet?: boolean;
  api_key?: string;
  secret?: string;
  active_strategy?: string;
  pairs?: string[];
}) => api.patch("/provider/config", patch).then((r) => r.data);

/** Fetch all investment profile presets. */
export const fetchPresets = () =>
  api.get<Preset[]>("/presets").then((r) => r.data);

/** Apply a preset — writes to config.yaml. */
export const applyPreset = (preset_id: string) =>
  api.post<ApplyPresetResult>(`/presets/${preset_id}/apply`).then((r) => r.data);

/** Fetch currently active preset info. */
export const fetchActivePreset = () =>
  api.get<{ preset_id: string | null; preset?: Preset; risk: Record<string, unknown> }>(
    "/presets/active/current",
  ).then((r) => r.data);

/** Run walk-forward out-of-sample validation for a completed backtest job. */
export const runWalkForward = (jobId: number, n_segments = 5, period = "1y") =>
  api.post<WalkForwardResult>(
    `/backtests/${jobId}/walk-forward`,
    null,
    { params: { n_segments, period } },
  ).then((r) => r.data);

/** Run Monte Carlo trade-shuffle simulation for a completed backtest job. */
export const runMonteCarlo = (jobId: number, n_runs = 1000) =>
  api.post<MonteCarloResult>(
    `/backtests/${jobId}/monte-carlo`,
    null,
    { params: { n_runs } },
  ).then((r) => r.data);

/** Fetch volatility + trend metrics for multiple pairs. */
export const fetchMarketScanner = (params?: { pairs?: string; timeframe?: string }) =>
  api.get<MarketSnapshot[]>("/market/scanner", { params }).then((r) => r.data);

/** Fetch high-level market overview (top movers, volatility regime). */
export const fetchMarketSummary = (params?: { timeframe?: string }) =>
  api.get<MarketSummary>("/market/summary", { params }).then((r) => r.data);

// ── Market cache types & functions ────────────────────────────────────────────

/** A single entry in the server-side market data cache. */
export interface MarketCacheEntry {
  key:          string;
  timeframe:    string;
  pairs:        string[];
  pairs_count:  number;
  pairs_cached: number;
  age_seconds:  number;
  is_fresh:     boolean;
  fetched_at:   string;
}

/** Response from GET /api/market/cache. */
export interface MarketCacheStatus {
  ttl_seconds:   number;
  total_entries: number;
  entries:       MarketCacheEntry[];
}

/** Fetch the current state of the server-side market data cache. */
export const fetchMarketCache = () =>
  api.get<MarketCacheStatus>("/market/cache").then((r) => r.data);

/** Trigger a background re-scan to pre-warm the market cache. */
export const warmMarketCache = (params?: { timeframe?: string; pairs?: string }) =>
  api.post<{ ok: boolean; pairs: number; timeframe: string; detail: string }>(
    "/market/cache/warm", null, { params },
  ).then((r) => r.data);

/** Invalidate (clear) the entire market cache. */
export const clearMarketCache = () =>
  api.delete<{ ok: boolean; cleared: number }>("/market/cache").then((r) => r.data);

// ── System metrics types ───────────────────────────────────────────────────────

/** VPS / container system metrics from GET /api/system/metrics. */
export interface SystemMetrics {
  cpu_pct: number;
  ram_pct: number;
  ram_used_mb: number;
  ram_total_mb: number;
  disk: {
    path: string;
    used_gb: number;
    total_gb: number;
    pct: number;
  };
  process_rss_mb: number;
  process_cpu_pct: number;
  process_uptime_s: number;
  process_threads: number;
  os_uptime_s?: number;
  data_dir_mb?: number;
}

/** Fetch VPS system metrics (CPU, RAM, disk, process). */
export const fetchSystemMetrics = () =>
  api.get<SystemMetrics>("/system/metrics").then((r) => r.data);

// ── Portfolio types ────────────────────────────────────────────────────────────

/** Status of a single strategy slot in the portfolio. */
export interface PortfolioSlot {
  index: number;
  name: string;
  pairs: string[];
  capital_pct: number;
  mode: string;
  running: boolean;
  crashed: boolean;
  started_at?: string;
  uptime_s?: number;
  trade_count: number;
  error?: string;
}

/** Aggregate portfolio status from GET /api/portfolio/status. */
export interface PortfolioStatus {
  running: boolean;
  alive_slots: number;
  total_slots: number;
  crashed_slots: number;
  total_trades: number;
  started_at?: string;
  uptime_s?: number;
  slots: PortfolioSlot[];
}

/** Fetch portfolio status. */
export const fetchPortfolioStatus = () =>
  api.get<PortfolioStatus>("/portfolio/status").then((r) => r.data);

/** Start all portfolio slots. */
export const startPortfolio = (body: { mode: string }) =>
  api.post<PortfolioStatus>("/portfolio/start", body).then((r) => r.data);

/** Stop all portfolio slots. */
export const stopPortfolio = () =>
  api.post<PortfolioStatus>("/portfolio/stop").then((r) => r.data);

// ── Settings types ─────────────────────────────────────────────────────────────

/**
 * Flat snapshot of all user-editable config values.
 * Returned by GET /api/config/settings.
 */
export interface SettingsSnapshot {
  // Risk circuit breakers
  daily_loss_stop_pct:      number;
  max_drawdown_pct:         number;
  max_daily_trades:         number;
  max_consecutive_losses:   number;
  max_concurrent_positions: number;
  leverage:                 number;
  blackout_hours:           string;
  // Anomaly thresholds
  slippage_alert_pct:       number;
  balance_gap_pct:          number;
  stale_price_candles:      number;
  // Bot settings
  active_strategy: string;
  pairs:           string[];
  // Paper settings
  paper_initial_balance: number;
  paper_fee_pct:         number;
}

/** Fields accepted by PATCH /api/config/risk. */
export interface RiskPatch {
  daily_loss_stop_pct?:      number;
  max_drawdown_pct?:         number;
  max_daily_trades?:         number;
  max_consecutive_losses?:   number;
  max_concurrent_positions?: number;
  leverage?:                 number;
  blackout_hours?:           string;
  slippage_alert_pct?:       number;
  balance_gap_pct?:          number;
  stale_price_candles?:      number;
}

/** Fields accepted by PATCH /api/config/bot. */
export interface BotConfigPatch {
  active_strategy?: string;
  pairs?:           string[];
  paper?: {
    initial_balance?: number;
    fee_pct?:         number;
  };
}

/** Fetch current editable settings snapshot. */
export const fetchSettings = () =>
  api.get<SettingsSnapshot>("/config/settings").then((r) => r.data);

/** Update risk circuit breakers and anomaly thresholds. */
export const patchRiskConfig = (patch: RiskPatch) =>
  api.patch<{ ok: boolean; updated: string[]; risk: Record<string, unknown> }>(
    "/config/risk",
    patch,
  ).then((r) => r.data);

/** Update bot settings (active strategy, pairs, paper parameters). */
export const patchBotConfig = (patch: BotConfigPatch) =>
  api.patch<{ ok: boolean; updated: string[] }>(
    "/config/bot",
    patch,
  ).then((r) => r.data);

// ── Auth functions ─────────────────────────────────────────────────────────────

/** Validate an API key against the server. Returns `{ authenticated: true }` on success. */
export const loginWithApiKey = (api_key: string) =>
  axios
    .post<{ authenticated: boolean }>("/api/auth/login", { api_key })
    .then((r) => r.data);

// ── Strategy Engine API functions ──────────────────────────────────────────────

/** List all strategy configs. */
export const fetchStrategyConfigs = () =>
  api.get<StrategyConfigData[]>("/strategy-configs").then((r) => r.data);

/** Get a single strategy config by ID. */
export const fetchStrategyConfig = (id: number) =>
  api.get<StrategyConfigData>(`/strategy-configs/${id}`).then((r) => r.data);

/** Create a new strategy config. */
export const createStrategyConfig = (body: StrategyConfigCreate) =>
  api.post<StrategyConfigData>("/strategy-configs", body).then((r) => r.data);

/** Update an existing strategy config. */
export const updateStrategyConfig = (id: number, body: Partial<StrategyConfigCreate>) =>
  api.patch<StrategyConfigData>(`/strategy-configs/${id}`, body).then((r) => r.data);

/** Delete a strategy config. */
export const deleteStrategyConfig = (id: number) =>
  api.delete(`/strategy-configs/${id}`);

/** Activate a strategy config — writes execution_strategy to config.yaml. */
export const activateStrategyConfig = (id: number) =>
  api.post<ActivateStrategyConfigResult>(`/strategy-configs/${id}/activate`).then((r) => r.data);
