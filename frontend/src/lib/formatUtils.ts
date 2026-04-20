/**
 * formatUtils.ts
 * Shared number / time formatting functions used across multiple pages.
 */

/** Format a PnL value with sign and USDT suffix. */
export function fmtPnl(v: number, decimals = 4): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)} USDT`;
}

/** Format a signed percentage, e.g. +12.50% */
export function fmtPct(v: number, decimals = 2): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}%`;
}

/** Format a dollar volume: $1.23B / $456.7M / $78K */
export function fmtVolume(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

/**
 * Format a cryptocurrency price with appropriate precision.
 * High prices → integer, mid → 3dp, low → 5dp, very low → 7dp.
 */
export function fmtPrice(p: number): string {
  if (p >= 1000) return p.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (p >= 1)    return p.toFixed(3);
  if (p >= 0.01) return p.toFixed(5);
  return p.toFixed(7);
}

/** Human-readable uptime from seconds: "2d 3h" / "1h 45m" / "3m 12s" */
export function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m ${s}s`;
}

/** ISO timestamp → "Jan 5 14:32" */
export function fmtDateShort(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day:   "numeric",
    hour:  "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** ISO timestamp → "2024-01-05 14:32" */
export function fmtDatetime(iso: string): string {
  return iso.substring(0, 16).replace("T", " ");
}
