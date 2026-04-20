/**
 * Maps every registered strategy to the list of technical indicators it uses.
 *
 * Two purposes:
 *  1. PriceChart: overlay the relevant indicators on the chart when a strategy is known.
 *  2. StrategyCard / StrategyPicker: show indicator chips (EMA(9), RSI(14), …).
 */

export type IndicatorPanel = "price" | "osc";

export interface IndicatorDef {
  /** Unique key — used as the dataKey suffix in the chart data object */
  id:     string;
  /** Human-readable label, e.g. "EMA(9)" */
  label:  string;
  /** Indicator type — drives which computation function to call */
  type:   "ema" | "sma" | "rsi" | "macd" | "bollinger" | "supertrend" | "atr" | "vwap";
  /** Parameters forwarded to the computation function */
  params: Record<string, number>;
  /**
   * Which panel to render in.
   *  "price" — overlaid on the candlestick chart
   *  "osc"   — rendered in the oscillator sub-panel (RSI / MACD)
   */
  panel:  IndicatorPanel;
  /** Line/fill colour (CSS hex or var()) */
  color?: string;
  /** Overrides for oscillator reference lines, e.g. overbought / oversold */
  levels?: { value: number; color?: string; label?: string }[];
}

// ── Strategy → indicator definitions ─────────────────────────────────────────

const STRATEGY_INDICATORS: Record<string, IndicatorDef[]> = {
  mean_reversion: [
    { id: "sma20",  label: "SMA(20)",   type: "sma",       params: { period: 20 },         panel: "price", color: "#f59e0b" },
    { id: "bb",     label: "BB(20,2)",  type: "bollinger", params: { period: 20, mult: 2 }, panel: "price", color: "#94a3b8" },
    { id: "rsi",    label: "RSI(14)",   type: "rsi",       params: { period: 14 },          panel: "osc",   color: "#a78bfa",
      levels: [{ value: 60, color: "#ef4444", label: "OB" }, { value: 40, color: "#22c55e", label: "OS" }] },
  ],

  ema_crossover: [
    { id: "ema9",   label: "EMA(9)",    type: "ema", params: { period: 9  }, panel: "price", color: "#60a5fa" },
    { id: "ema21",  label: "EMA(21)",   type: "ema", params: { period: 21 }, panel: "price", color: "#f59e0b" },
    { id: "ema5sig",label: "EMA(5)",    type: "ema", params: { period: 5  }, panel: "price", color: "#34d399" },
  ],

  bollinger_dca: [
    { id: "bb",     label: "BB(20,2)",  type: "bollinger", params: { period: 20, mult: 2 }, panel: "price", color: "#94a3b8" },
    { id: "sma20",  label: "SMA(20)",   type: "sma",       params: { period: 20 },          panel: "price", color: "#f59e0b" },
  ],

  rsi_mean_revert: [
    { id: "sma20",  label: "SMA(20)",   type: "sma", params: { period: 20 }, panel: "price", color: "#f59e0b" },
    { id: "rsi",    label: "RSI(14)",   type: "rsi", params: { period: 14 }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 70, color: "#ef4444" }, { value: 30, color: "#22c55e" }] },
  ],

  grid_dynamic: [
    { id: "sma20",  label: "SMA(20)",   type: "sma", params: { period: 20 }, panel: "price", color: "#f59e0b" },
    { id: "sma50",  label: "SMA(50)",   type: "sma", params: { period: 50 }, panel: "price", color: "#fb923c" },
  ],

  threshold_rebalance: [
    { id: "sma50",  label: "SMA(50)",   type: "sma", params: { period: 50 }, panel: "price", color: "#f59e0b" },
    { id: "sma200", label: "SMA(200)",  type: "sma", params: { period: 200 }, panel: "price", color: "#a78bfa" },
  ],

  trend_following: [
    { id: "ema20",  label: "EMA(20)",   type: "ema", params: { period: 20  }, panel: "price", color: "#60a5fa" },
    { id: "ema50",  label: "EMA(50)",   type: "ema", params: { period: 50  }, panel: "price", color: "#f59e0b" },
  ],

  trend_following_ls: [
    { id: "ema20",  label: "EMA(20)",   type: "ema", params: { period: 20  }, panel: "price", color: "#60a5fa" },
    { id: "ema50",  label: "EMA(50)",   type: "ema", params: { period: 50  }, panel: "price", color: "#f59e0b" },
    { id: "rsi",    label: "RSI(14)",   type: "rsi", params: { period: 14  }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 55, color: "#ef4444" }, { value: 45, color: "#22c55e" }] },
  ],

  breakout: [
    { id: "sma20",  label: "SMA(20)",   type: "sma", params: { period: 20 }, panel: "price", color: "#f59e0b" },
    { id: "sma50",  label: "SMA(50)",   type: "sma", params: { period: 50 }, panel: "price", color: "#fb923c" },
  ],

  macd_rsi: [
    { id: "ema100", label: "EMA(100)",  type: "ema",  params: { period: 100 }, panel: "price", color: "#a78bfa" },
    { id: "macd",   label: "MACD(12,26,9)", type: "macd",
      params: { fast: 12, slow: 26, signal: 9 }, panel: "osc", color: "#60a5fa" },
  ],

  scalping: [
    { id: "ema9",   label: "EMA(9)",    type: "ema",  params: { period: 9  }, panel: "price", color: "#60a5fa" },
    { id: "ema21",  label: "EMA(21)",   type: "ema",  params: { period: 21 }, panel: "price", color: "#f59e0b" },
    { id: "vwap",   label: "VWAP",      type: "vwap", params: {},             panel: "price", color: "#34d399" },
    { id: "rsi",    label: "RSI(6)",    type: "rsi",  params: { period: 6  }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 75, color: "#ef4444" }, { value: 25, color: "#22c55e" }] },
  ],

  momentum_burst: [
    { id: "ema20",  label: "EMA(20)",   type: "ema", params: { period: 20 }, panel: "price", color: "#60a5fa" },
    { id: "ema50",  label: "EMA(50)",   type: "ema", params: { period: 50 }, panel: "price", color: "#f59e0b" },
    { id: "rsi",    label: "RSI(14)",   type: "rsi", params: { period: 14 }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 60, color: "#ef4444" }, { value: 40, color: "#22c55e" }] },
  ],

  bb_squeeze: [
    { id: "bb",     label: "BB(20,2)",  type: "bollinger", params: { period: 20, mult: 2 }, panel: "price", color: "#94a3b8" },
    { id: "sma20",  label: "SMA(20)",   type: "sma",       params: { period: 20 },          panel: "price", color: "#f59e0b" },
  ],

  supertrend: [
    { id: "st",     label: "Supertrend(10,3)", type: "supertrend", params: { period: 10, mult: 3 }, panel: "price", color: "#22c55e" },
  ],

  vwap_bounce: [
    { id: "vwap",   label: "VWAP",      type: "vwap", params: {},             panel: "price", color: "#34d399" },
    { id: "ema50",  label: "EMA(50)",   type: "ema",  params: { period: 50 }, panel: "price", color: "#f59e0b" },
    { id: "rsi",    label: "RSI(14)",   type: "rsi",  params: { period: 14 }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 60, color: "#ef4444" }, { value: 40, color: "#22c55e" }] },
  ],

  stoch_rsi: [
    { id: "ema50",  label: "EMA(50)",   type: "ema", params: { period: 50 }, panel: "price", color: "#f59e0b" },
    { id: "rsi",    label: "StochRSI(14)", type: "rsi", params: { period: 14 }, panel: "osc", color: "#a78bfa",
      levels: [{ value: 80, color: "#ef4444" }, { value: 20, color: "#22c55e" }] },
  ],

  ichimoku: [
    { id: "ema9",   label: "Tenkan(9)", type: "ema", params: { period: 9  }, panel: "price", color: "#60a5fa" },
    { id: "ema26",  label: "Kijun(26)", type: "ema", params: { period: 26 }, panel: "price", color: "#f59e0b" },
    { id: "ema52",  label: "Senkou B(52)", type: "ema", params: { period: 52 }, panel: "price", color: "#a78bfa" },
  ],

  supertrend_pro: [
    { id: "st",     label: "Supertrend(10,3)", type: "supertrend", params: { period: 10, mult: 3 }, panel: "price", color: "#22c55e" },
    { id: "ema200", label: "EMA(200)",  type: "ema",        params: { period: 200 }, panel: "price", color: "#a78bfa" },
  ],

  funding_rate_arb: [
    { id: "ema20",  label: "EMA(20)",   type: "ema", params: { period: 20 }, panel: "price", color: "#60a5fa" },
    { id: "sma50",  label: "SMA(50)",   type: "sma", params: { period: 50 }, panel: "price", color: "#f59e0b" },
  ],

  // ── Kraken Futures Strategies ─────────────────────────────────────────────

  pullback: [
    { id: "ema21",  label: "EMA(21)",  type: "ema", params: { period: 21 }, panel: "price", color: "#60a5fa" },
    { id: "ema50",  label: "EMA(50)",  type: "ema", params: { period: 50 }, panel: "price", color: "#f59e0b" },
    { id: "rsi",    label: "RSI(14)",  type: "rsi", params: { period: 14 }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 35, color: "#22c55e", label: "OS" }, { value: 65, color: "#ef4444", label: "OB" }] },
  ],

  dual_thrust: [
    { id: "atr14",  label: "ATR(14)",  type: "atr", params: { period: 14 }, panel: "price", color: "#94a3b8" },
    { id: "rsi",    label: "RSI(14)",  type: "rsi", params: { period: 14 }, panel: "osc",   color: "#a78bfa",
      levels: [{ value: 30, color: "#22c55e" }, { value: 70, color: "#ef4444" }] },
  ],

  keltner_breakout: [
    { id: "ema20",  label: "EMA(20)",  type: "ema",       params: { period: 20 },         panel: "price", color: "#f59e0b" },
    { id: "bb",     label: "KC(20,2)", type: "bollinger", params: { period: 20, mult: 2 }, panel: "price", color: "#94a3b8" },
    { id: "rsi",    label: "RSI(14)",  type: "rsi",       params: { period: 14 },          panel: "osc",   color: "#a78bfa",
      levels: [{ value: 20, color: "#22c55e", label: "Exit Short" }, { value: 80, color: "#ef4444", label: "Exit Long" }] },
  ],
};

export default STRATEGY_INDICATORS;

/** Returns the indicator list for a strategy, or [] if unknown. */
export function getStrategyIndicators(strategyName: string): IndicatorDef[] {
  return STRATEGY_INDICATORS[strategyName] ?? [];
}

/** Returns only the price-panel indicators for a strategy. */
export function getPriceIndicators(strategyName: string): IndicatorDef[] {
  return getStrategyIndicators(strategyName).filter((d) => d.panel === "price");
}

/** Returns only the oscillator-panel indicators for a strategy (null if none). */
export function getOscIndicator(strategyName: string): IndicatorDef | null {
  // Prefer MACD, then first osc indicator
  const osc = getStrategyIndicators(strategyName).filter((d) => d.panel === "osc");
  return osc.find((d) => d.type === "macd") ?? osc[0] ?? null;
}
