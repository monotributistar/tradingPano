import type { BacktestMetrics } from "../api/client";
import styles from "./MetricsCard.module.css";

interface Props {
  metrics: BacktestMetrics;
  strategy?: string;
  pair?: string;
  period?: string;
}

function fmt(v: number | null | undefined, decimals = 2) {
  return v != null ? v.toFixed(decimals) : "—";
}

function colorClass(v: number | null | undefined) {
  if (v != null && v > 0) return styles.pos;
  if (v != null && v < 0) return styles.neg;
  return "";
}

export default function MetricsCard({ metrics, strategy, pair, period }: Props) {
  return (
    <div className={styles.card}>
      {(strategy || pair) && (
        <div className={styles.title}>
          {strategy} {pair && `· ${pair}`} {period && `(${period})`}
        </div>
      )}
      <div className={styles.grid}>
        <Stat label="Total Return" value={metrics.total_return_pct != null ? `${metrics.total_return_pct >= 0 ? "+" : ""}${fmt(metrics.total_return_pct)}%` : "—"} colorVal={metrics.total_return_pct} />
        <Stat label="Sharpe" value={fmt(metrics.sharpe_ratio)} colorVal={metrics.sharpe_ratio != null ? metrics.sharpe_ratio - 1 : undefined} />
        <Stat label="Sortino" value={fmt(metrics.sortino_ratio)} colorVal={metrics.sortino_ratio != null ? metrics.sortino_ratio - 1 : undefined} />
        <Stat label="Max Drawdown" value={metrics.max_drawdown_pct != null ? `-${fmt(metrics.max_drawdown_pct)}%` : "—"} colorVal={metrics.max_drawdown_pct != null ? -metrics.max_drawdown_pct : undefined} />
        <Stat label="Win Rate" value={metrics.win_rate_pct != null ? `${fmt(metrics.win_rate_pct)}%` : "—"} colorVal={metrics.win_rate_pct != null ? metrics.win_rate_pct - 50 : undefined} />
        <Stat label="Profit Factor" value={fmt(metrics.profit_factor)} colorVal={metrics.profit_factor != null ? metrics.profit_factor - 1 : undefined} />
        <Stat label="Trades" value={metrics.total_trades != null ? String(metrics.total_trades) : "—"} />
        <Stat label="Expectancy" value={metrics.expectancy_usd != null ? `$${fmt(metrics.expectancy_usd, 4)}` : "—"} colorVal={metrics.expectancy_usd} />
        <Stat label="Capital Used" value={metrics.capital_utilization_pct != null ? `${fmt(metrics.capital_utilization_pct)}%` : "—"} />
        <Stat label="Final Capital" value={`$${fmt(metrics.final_capital, 2)}`} colorVal={metrics.final_capital != null ? metrics.final_capital - metrics.initial_capital : undefined} />
      </div>
    </div>
  );
}

function Stat({ label, value, colorVal }: { label: string; value: string; colorVal?: number }) {
  return (
    <div className={styles.stat}>
      <div className={styles.label}>{label}</div>
      <div className={`${styles.value} ${colorVal !== undefined ? colorClass(colorVal) : ""}`}>{value}</div>
    </div>
  );
}
