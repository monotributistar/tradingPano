import { useQuery } from "@tanstack/react-query";
import { fetchTradeStats, fetchTrades, fetchBacktests } from "../api/client";
import EquityCurve from "../components/EquityCurve";
import SystemMetricsWidget from "../components/SystemMetricsWidget";
import StrategyPerformancePanel from "../components/StrategyPerformancePanel";
import { StatCard, SectionHeader, EmptyState, Badge } from "../components/ui";
import { pnlColor, sharpeColor } from "../lib/colorUtils";
import { fmtPnl, fmtPct, fmtDatetime } from "../lib/formatUtils";
import styles from "./Dashboard.module.css";

export default function Dashboard() {
  const { data: stats } = useQuery({ queryKey: ["tradeStats"], queryFn: () => fetchTradeStats() });
  const { data: recentTrades } = useQuery({
    queryKey: ["recentTrades"],
    queryFn: () => fetchTrades({ source: "paper", limit: 5 }),
  });
  const { data: backtests } = useQuery({
    queryKey: ["backtests"],
    queryFn: () => fetchBacktests(),
  });
  const { data: paperTrades } = useQuery({
    queryKey: ["paperTrades"],
    queryFn: () => fetchTrades({ source: "paper", limit: 500 }),
  });

  const sells = (paperTrades ?? []).filter((t) => t.type === "sell" && t.pnl !== undefined);
  let cumPnl = 0;
  const equityCurve = sells.map((t) => { cumPnl += t.pnl!; return 20 + cumPnl; });
  const equityTs = sells.map((t) => t.timestamp ?? t.logged_at);

  const doneBacktests = (backtests ?? []).filter((b) => b.status === "done");

  return (
    <div className={styles.page}>
      {/* Summary cards */}
      <div className={styles.cards}>
        <StatCard
          label="Total PnL"
          value={stats ? fmtPnl(stats.total_pnl) : "—"}
          color={stats ? (stats.total_pnl >= 0 ? "green" : "red") : undefined}
          sub="paper + live"
        />
        <StatCard
          label="Win Rate"
          value={stats ? `${(stats.win_rate_pct ?? 0).toFixed(1)}%` : "—"}
          sub={`${stats?.total_trades ?? 0} closed trades`}
        />
        <StatCard
          label="Avg PnL / trade"
          value={stats ? fmtPnl(stats.avg_pnl) : "—"}
          color={stats ? (stats.avg_pnl >= 0 ? "green" : "red") : undefined}
        />
        <StatCard
          label="Best Trade"
          value={stats?.best_trade != null ? fmtPnl(stats.best_trade) : "—"}
          color="green"
        />
        <StatCard
          label="Worst Trade"
          value={stats?.worst_trade != null ? fmtPnl(stats.worst_trade) : "—"}
          color="red"
        />
        <StatCard
          label="Backtests Run"
          value={String(doneBacktests.length)}
          sub="completed"
        />
      </div>

      {/* Equity curve */}
      <div className={styles.section}>
        <SectionHeader title="Paper Trading Equity" icon="📈" />
        {equityCurve.length ? (
          <EquityCurve curve={equityCurve} timestamps={equityTs} initialCapital={20} height={200} />
        ) : (
          <EmptyState
            icon="📭"
            message="No paper trades yet. Start a paper bot or run a backtest."
          />
        )}
      </div>

      <StrategyPerformancePanel />
      <SystemMetricsWidget />

      <div className={styles.two}>
        {/* Recent backtests */}
        <div className={styles.section}>
          <SectionHeader title="Recent Backtests" icon="🔬" />
          {doneBacktests.length === 0 ? (
            <EmptyState icon="🔬" message="No completed backtests yet." size="sm" />
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Strategy</th><th>Pair</th><th>Period</th><th>Return</th><th>Sharpe</th>
                </tr>
              </thead>
              <tbody>
                {doneBacktests.slice(0, 8).map((b) => {
                  const ret = b.metrics?.total_return_pct;
                  const sharpe = b.metrics?.sharpe_ratio;
                  return (
                    <tr key={b.id}>
                      <td>{b.strategy}</td>
                      <td>{b.pair}</td>
                      <td>{b.period}</td>
                      <td style={{ color: pnlColor(ret ?? 0) }}>
                        {ret != null ? fmtPct(ret) : "—"}
                      </td>
                      <td style={{ color: sharpeColor(sharpe ?? 0) }}>
                        {sharpe != null ? sharpe.toFixed(2) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Recent trades */}
        <div className={styles.section}>
          <SectionHeader title="Recent Trades" icon="📋" />
          {!recentTrades?.length ? (
            <EmptyState icon="📋" message="No recent trades." size="sm" />
          ) : (
            <table className={styles.table}>
              <thead><tr><th>Date</th><th>Type</th><th>Pair</th><th>PnL</th></tr></thead>
              <tbody>
                {recentTrades.map((t) => (
                  <tr key={t.id}>
                    <td style={{ color: "var(--muted)" }}>
                      {fmtDatetime(t.timestamp ?? t.logged_at)}
                    </td>
                    <td>
                      <Badge
                        variant={t.type === "buy" ? "green" : "red"}
                        label={t.type.toUpperCase()}
                      />
                    </td>
                    <td style={{ fontWeight: 600 }}>{t.pair}</td>
                    <td style={{ color: pnlColor(t.pnl ?? 0) }}>
                      {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(4)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
