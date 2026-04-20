/**
 * StrategyPerformancePanel — ranked per-strategy P&L table.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStrategyPerformance } from "../api/client";
import type { StrategyPerf } from "../api/client";
import { SectionHeader, TabBar, Badge, EmptyState, LoadingState, Alert } from "./ui";
import { pnlColor, winRateColor, pfColor } from "../lib/colorUtils";
import styles from "./StrategyPerformancePanel.module.css";

function fmt(v: number, decimals = 4): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}`;
}

function WinBar({ wins, losses }: { wins: number; losses: number }) {
  const total = wins + losses;
  if (total === 0) return <span style={{ color: "var(--muted)" }}>—</span>;
  const winPct = (wins / total) * 100;
  return (
    <div className={styles.winBar} title={`${wins}W / ${losses}L`}>
      <div className={styles.winBarFill} style={{ width: `${winPct}%` }} />
    </div>
  );
}

type SourceFilter = "all" | "paper" | "live";

export default function StrategyPerformancePanel() {
  const [filter, setFilter] = useState<SourceFilter>("all");

  const { data, isLoading, error } = useQuery<StrategyPerf[]>({
    queryKey:        ["strategyPerformance", filter],
    queryFn:         () => fetchStrategyPerformance(filter !== "all" ? { source: filter } : undefined),
    refetchInterval: 30_000,
  });

  const rows = data ?? [];

  return (
    <div className={styles.panel}>
      <SectionHeader
        title="Strategy Performance"
        icon="📊"
        action={
          <TabBar
            variant="pills"
            size="sm"
            tabs={[
              { value: "all",   label: "All"   },
              { value: "paper", label: "Paper" },
              { value: "live",  label: "Live"  },
            ]}
            active={filter}
            onChange={(v) => setFilter(v as SourceFilter)}
          />
        }
      />

      {isLoading ? (
        <LoadingState message="Loading strategy data…" size="sm" />
      ) : error ? (
        <Alert variant="error" compact>Failed to load strategy data.</Alert>
      ) : rows.length === 0 ? (
        <EmptyState
          icon="📊"
          message="No closed trades yet. Start a paper bot or run a backtest to see performance data."
          size="sm"
        />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.colStrategy}>Strategy</th>
                <th>Source</th>
                <th className={styles.colNum}>Trades</th>
                <th className={styles.colNum}>Win %</th>
                <th className={styles.colNum}>W/L</th>
                <th className={styles.colNum}>Total PnL</th>
                <th className={styles.colNum}>Avg PnL</th>
                <th className={styles.colNum}>P-Factor</th>
                <th className={styles.colNum}>Best</th>
                <th className={styles.colNum}>Worst</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.strategy}>
                  <td className={styles.strategyName}>{r.strategy}</td>
                  <td>
                    <Badge
                      variant={r.sources.length > 1 ? "gray" : r.sources[0] === "live" ? "green" : "blue"}
                      label={r.sources.length > 1 ? "mixed" : r.sources[0] ?? "—"}
                    />
                  </td>
                  <td className={styles.colNum}>{r.total_trades}</td>
                  <td className={styles.colNum} style={{ color: winRateColor(r.win_rate_pct) }}>
                    {r.win_rate_pct.toFixed(1)}%
                  </td>
                  <td className={styles.colNum}>
                    <WinBar wins={r.wins} losses={r.losses} />
                  </td>
                  <td className={styles.colNum} style={{ color: pnlColor(r.total_pnl), fontWeight: 700 }}>
                    {fmt(r.total_pnl)} <span className={styles.unit}>USDT</span>
                  </td>
                  <td className={styles.colNum} style={{ color: pnlColor(r.avg_pnl) }}>
                    {fmt(r.avg_pnl)}
                  </td>
                  <td className={styles.colNum} style={{ color: pfColor(r.profit_factor) }}>
                    {r.profit_factor > 0 ? r.profit_factor.toFixed(2) : "—"}
                  </td>
                  <td className={styles.colNum} style={{ color: "var(--green)" }}>
                    {fmt(r.best_trade)}
                  </td>
                  <td className={styles.colNum} style={{ color: "var(--red)" }}>
                    {fmt(r.worst_trade)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
