/**
 * Lightweight technical indicator library — pure functions, no external deps.
 *
 * All functions return arrays with the same length as the input.
 * Values are `null` during the warm-up period (not enough bars yet).
 */

export type IV = number | null; // IndicatorValue

// ── Moving averages ────────────────────────────────────────────────────────────

/** Exponential Moving Average */
export function ema(data: number[], period: number): IV[] {
  const out: IV[] = new Array(data.length).fill(null);
  if (data.length < period || period < 1) return out;
  const k = 2 / (period + 1);
  let prev = data.slice(0, period).reduce((a, b) => a + b) / period;
  out[period - 1] = prev;
  for (let i = period; i < data.length; i++) {
    prev = data[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Simple Moving Average */
export function sma(data: number[], period: number): IV[] {
  const out: IV[] = new Array(data.length).fill(null);
  for (let i = period - 1; i < data.length; i++) {
    out[i] = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b) / period;
  }
  return out;
}

// ── Volatility ─────────────────────────────────────────────────────────────────

/** ATR(period) — Average True Range (Wilder smoothing) */
export function atr(
  high: number[], low: number[], close: number[], period = 14,
): IV[] {
  const n = high.length;
  const out: IV[] = new Array(n).fill(null);
  if (n < period + 1) return out;

  const tr: number[] = [high[0] - low[0]];
  for (let i = 1; i < n; i++) {
    tr.push(Math.max(
      high[i] - low[i],
      Math.abs(high[i] - close[i - 1]),
      Math.abs(low[i]  - close[i - 1]),
    ));
  }

  let val = tr.slice(0, period).reduce((a, b) => a + b) / period;
  out[period - 1] = val;
  for (let i = period; i < n; i++) {
    val = (val * (period - 1) + tr[i]) / period;
    out[i] = val;
  }
  return out;
}

/** Bollinger Bands (period=20, multiplier=2) */
export function bollingerBands(
  data: number[], period = 20, mult = 2.0,
): { upper: IV; mid: IV; lower: IV }[] {
  const out = data.map(() => ({ upper: null as IV, mid: null as IV, lower: null as IV }));
  for (let i = period - 1; i < data.length; i++) {
    const slice  = data.slice(i - period + 1, i + 1);
    const mean   = slice.reduce((a, b) => a + b) / period;
    const std    = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period);
    out[i]       = { upper: mean + mult * std, mid: mean, lower: mean - mult * std };
  }
  return out;
}

// ── Momentum ───────────────────────────────────────────────────────────────────

/** RSI(period=14) — 0–100 momentum oscillator */
export function rsi(data: number[], period = 14): IV[] {
  const out: IV[] = new Array(data.length).fill(null);
  if (data.length < period + 1) return out;

  const diff = data.slice(1).map((v, i) => v - data[i]);
  let avgGain = diff.slice(0, period).reduce((a, d) => a + Math.max(0, d), 0) / period;
  let avgLoss = diff.slice(0, period).reduce((a, d) => a + Math.max(0, -d), 0) / period;

  for (let i = period; i < data.length; i++) {
    const d    = diff[i - 1];
    avgGain    = (avgGain * (period - 1) + Math.max(0,  d)) / period;
    avgLoss    = (avgLoss * (period - 1) + Math.max(0, -d)) / period;
    out[i]     = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

/** MACD — returns { macd, signal, histogram } per bar */
export function macd(
  data: number[], fast = 12, slow = 26, signal = 9,
): { macd: IV; signal: IV; histogram: IV }[] {
  const out = data.map(() => ({ macd: null as IV, signal: null as IV, histogram: null as IV }));

  const fastE  = ema(data, fast);
  const slowE  = ema(data, slow);
  const macdLine: IV[] = data.map((_, i) =>
    fastE[i] !== null && slowE[i] !== null ? (fastE[i] as number) - (slowE[i] as number) : null,
  );

  // Signal = EMA of the MACD line, computed from its first valid value
  const firstValid = macdLine.findIndex((v) => v !== null);
  const macdNums   = macdLine.filter((v): v is number => v !== null);
  const sigVals: IV[] = new Array(data.length).fill(null);
  if (macdNums.length >= signal) {
    const sigE = ema(macdNums, signal);
    sigE.forEach((v, i) => { sigVals[firstValid + i] = v; });
  }

  for (let i = 0; i < data.length; i++) {
    const m = macdLine[i], s = sigVals[i];
    out[i] = {
      macd:      m,
      signal:    s,
      histogram: m !== null && s !== null ? m - s : null,
    };
  }
  return out;
}

// ── Trend ──────────────────────────────────────────────────────────────────────

/**
 * Supertrend — returns { value, bullish } per bar.
 * bullish=true means price is above the band (uptrend support).
 * bullish=false means price is below the band (downtrend resistance).
 */
export function supertrend(
  high: number[], low: number[], close: number[],
  period = 10, mult = 3.0,
): { value: IV; bullish: boolean | null }[] {
  const n   = high.length;
  const out = high.map(() => ({ value: null as IV, bullish: null as boolean | null }));
  const atrV = atr(high, low, close, period);

  let prevSup = 0, prevRes = Infinity, dir = 1;

  for (let i = period; i < n; i++) {
    if (atrV[i] === null) continue;
    const a  = atrV[i] as number;
    const hl = (high[i] + low[i]) / 2;

    let sup = hl - mult * a;
    let res = hl + mult * a;

    // Don't let bands narrow
    sup = close[i - 1] > prevSup ? Math.max(sup, prevSup) : sup;
    res = close[i - 1] < prevRes ? Math.min(res, prevRes) : res;

    if (close[i] > prevRes) dir =  1;
    if (close[i] < prevSup) dir = -1;

    out[i]   = { value: dir === 1 ? sup : res, bullish: dir === 1 };
    prevSup  = sup;
    prevRes  = res;
  }
  return out;
}

/** Cumulative VWAP (session reset not practical for multi-day data) */
export function vwap(
  high: number[], low: number[], close: number[], volume: number[],
): IV[] {
  let cumPV = 0, cumVol = 0;
  return high.map((h, i) => {
    const tp = (h + low[i] + close[i]) / 3;
    cumPV   += tp * volume[i];
    cumVol  += volume[i];
    return cumVol > 0 ? cumPV / cumVol : null;
  });
}
