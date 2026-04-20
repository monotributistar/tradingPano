import { useQuery } from "@tanstack/react-query";
import { fetchWalletSummary, fetchWalletHistory } from "../api/client";
import EquityCurve from "../components/EquityCurve";
import { StatCard, SectionHeader, EmptyState } from "../components/ui";
import styles from "./Wallet.module.css";

export default function Wallet() {
  const { data: summary } = useQuery({
    queryKey: ["walletSummary"],
    queryFn: () => fetchWalletSummary({ source: "paper" }),
    refetchInterval: 10_000,
  });
  const { data: history } = useQuery({
    queryKey: ["walletHistory"],
    queryFn: () => fetchWalletHistory({ source: "paper", limit: 500 }),
    refetchInterval: 10_000,
  });

  const equityCurve = (history ?? []).map((s) => s.total_equity);
  const equityTs    = (history ?? []).map((s) => s.timestamp);

  const hasData      = summary && summary.total_equity !== null;
  const openPositions = hasData ? Object.entries(summary.positions) : [];

  return (
    <div className={styles.page}>
      {/* Summary cards */}
      <div className={styles.cards}>
        <StatCard
          label="Total Equity"
          value={hasData ? `${summary.total_equity!.toFixed(4)} USDT` : "—"}
          sub="paper wallet"
        />
        <StatCard
          label="Free USDT"
          value={hasData ? `${summary.balance_usdt!.toFixed(4)} USDT` : "—"}
          sub="available to trade"
        />
        <StatCard
          label="Positions Value"
          value={hasData ? `${summary.positions_value!.toFixed(4)} USDT` : "—"}
          sub="mark-to-market"
        />
        <StatCard
          label="Total P&L"
          value={
            hasData && summary.pnl !== null
              ? `${summary.pnl >= 0 ? "+" : ""}${summary.pnl.toFixed(4)} USDT`
              : "—"
          }
          color={hasData && summary.pnl !== null ? (summary.pnl >= 0 ? "green" : "red") : undefined}
          sub={
            hasData && summary.pnl_pct !== null
              ? `${summary.pnl_pct >= 0 ? "+" : ""}${summary.pnl_pct.toFixed(2)}%`
              : undefined
          }
        />
      </div>

      {/* Equity curve */}
      <div className={styles.section}>
        <SectionHeader title="Equity Over Time" icon="📈" />
        {equityCurve.length >= 2 ? (
          <EquityCurve
            curve={equityCurve}
            timestamps={equityTs}
            initialCapital={equityCurve[0]}
            height={220}
          />
        ) : (
          <EmptyState
            icon="📊"
            message="No wallet history yet. Start the paper bot to begin tracking equity."
          />
        )}
      </div>

      {/* Open positions */}
      <div className={styles.section}>
        <SectionHeader title="Open Positions" icon="📂" />
        {openPositions.length === 0 ? (
          <EmptyState icon="📂" message="No open positions." size="sm" />
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Pair</th><th>Qty</th><th>Avg Cost</th><th>Cost Basis</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map(([pair, pos]) => (
                <tr key={pair}>
                  <td style={{ fontWeight: 600 }}>{pair}</td>
                  <td>{pos.qty.toFixed(6)}</td>
                  <td>{pos.avg_cost.toFixed(2)} USDT</td>
                  <td>{(pos.qty * pos.avg_cost).toFixed(4)} USDT</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {summary && (
        <div className={styles.meta}>{summary.snapshots_count} snapshots recorded</div>
      )}
    </div>
  );
}
