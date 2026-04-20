import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchTrades, fetchTradeStats } from "../api/client";
import TradeTable from "../components/TradeTable";
import styles from "./Trades.module.css";

const SOURCES = ["", "paper", "live", "backtest"];
const PAIRS = ["", "BTC/USDT", "ETH/USDT", "SOL/USDT"];

export default function Trades() {
  const [filters, setFilters] = useState({ source: "", pair: "", type: "" });

  const { data: trades, isLoading } = useQuery({
    queryKey: ["trades", filters],
    queryFn: () =>
      fetchTrades({
        source: filters.source || undefined,
        pair: filters.pair || undefined,
        type: filters.type || undefined,
        limit: 200,
      }),
  });

  const { data: stats } = useQuery({
    queryKey: ["stats", filters.source],
    queryFn: () => fetchTradeStats({ source: filters.source || undefined }),
  });

  function set(key: string, value: string) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  return (
    <div className={styles.page}>
      {/* Stats bar */}
      {stats && stats.total_trades > 0 && (
        <div className={styles.statsBar}>
          <Stat label="Trades" value={String(stats.total_trades)} />
          <Stat label="Win Rate" value={`${stats.win_rate_pct.toFixed(1)}%`} />
          <Stat label="Total PnL" value={`${stats.total_pnl >= 0 ? "+" : ""}${stats.total_pnl.toFixed(4)} USDT`} color={stats.total_pnl >= 0 ? "green" : "red"} />
          <Stat label="Avg PnL" value={`${stats.avg_pnl >= 0 ? "+" : ""}${stats.avg_pnl.toFixed(4)}`} color={stats.avg_pnl >= 0 ? "green" : "red"} />
          <Stat label="Best" value={`+${stats.best_trade.toFixed(4)}`} color="green" />
          <Stat label="Worst" value={`${stats.worst_trade.toFixed(4)}`} color="red" />
        </div>
      )}

      {/* Filters */}
      <div className={styles.filters}>
        <select className={styles.select} value={filters.source} onChange={(e) => set("source", e.target.value)}>
          <option value="">All sources</option>
          {SOURCES.filter(Boolean).map((s) => <option key={s}>{s}</option>)}
        </select>
        <select className={styles.select} value={filters.pair} onChange={(e) => set("pair", e.target.value)}>
          <option value="">All pairs</option>
          {PAIRS.filter(Boolean).map((p) => <option key={p}>{p}</option>)}
        </select>
        <select className={styles.select} value={filters.type} onChange={(e) => set("type", e.target.value)}>
          <option value="">All types</option>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
        </select>
        <span className={styles.count}>{isLoading ? "..." : `${trades?.length ?? 0} trades`}</span>
      </div>

      <div className={styles.tableCard}>
        {isLoading ? (
          <div className={styles.loading}>Loading trades...</div>
        ) : (
          <TradeTable trades={trades ?? []} showSource />
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: "green" | "red" }) {
  const col = color === "green" ? "var(--green)" : color === "red" ? "var(--red)" : "var(--text)";
  return (
    <div className={styles.stat}>
      <div className={styles.statLabel}>{label}</div>
      <div className={styles.statValue} style={{ color: col }}>{value}</div>
    </div>
  );
}
