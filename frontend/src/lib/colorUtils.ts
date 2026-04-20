/**
 * colorUtils.ts
 * Centralised color-mapping functions for metric values.
 * All functions return CSS variable strings usable in inline `style` props.
 */

/** Green for profit, red for loss, muted for zero. */
export function pnlColor(v: number): string {
  if (v > 0) return "var(--green)";
  if (v < 0) return "var(--red)";
  return "var(--muted)";
}

/** Green ≥ good, red ≤ bad, muted in between. Defaults: good=1, bad=-1. */
export function percentColor(
  v: number,
  thresholds: { good?: number; bad?: number } = { good: 1, bad: -1 },
): string {
  if (v > (thresholds.good ?? 1)) return "var(--green)";
  if (v < (thresholds.bad ?? -1)) return "var(--red)";
  return "var(--muted)";
}

/** Win rate: ≥55% green, ≥45% normal, below red. */
export function winRateColor(pct: number): string {
  if (pct >= 55) return "var(--green)";
  if (pct >= 45) return "var(--text)";
  return "var(--red)";
}

/** Profit factor: ≥1.5 green, ≥1.0 normal, below red. */
export function pfColor(pf: number): string {
  if (pf >= 1.5) return "var(--green)";
  if (pf >= 1.0) return "var(--text)";
  return "var(--red)";
}

/** Sharpe ratio: ≥1 green, ≥0 normal, below red. */
export function sharpeColor(s: number): string {
  if (s >= 1) return "var(--green)";
  if (s >= 0) return "var(--text)";
  return "var(--red)";
}

/**
 * Resource health (CPU/RAM/Disk):
 * > 85% → red, > 60% → yellow, else green.
 */
export function healthColor(pct: number): string {
  if (pct > 85) return "var(--red)";
  if (pct > 60) return "var(--yellow)";
  return "var(--green)";
}

/** RSI: ≥70 overbought (red), ≤30 oversold (green), else normal. */
export function rsiColor(rsi: number): string {
  if (rsi >= 70) return "var(--red)";
  if (rsi <= 30) return "var(--green)";
  return "var(--text)";
}

/** ADX trend strength: ≥25 strong trend (green), ≥18 moderate (yellow), else weak. */
export function adxColor(adx: number): string {
  if (adx >= 25) return "var(--green)";
  if (adx >= 18) return "var(--yellow)";
  return "var(--muted)";
}

/**
 * Returns the CSS variable for a semantic status string.
 * Handles: running/active/live/done/up → green
 *          pending/loading → yellow
 *          error/crash/down → red
 *          everything else → muted
 */
export function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (["running", "active", "live", "done", "up", "connected"].includes(s)) return "var(--green)";
  if (["pending", "loading", "starting", "warning"].includes(s)) return "var(--yellow)";
  if (["error", "crash", "crashed", "failed", "down", "disconnected"].includes(s)) return "var(--red)";
  return "var(--muted)";
}
