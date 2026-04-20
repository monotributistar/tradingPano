import type { Trade } from "../api/client";
import styles from "./TradeTable.module.css";

const PAIR_COLORS: Record<string, string> = {
  "BTC/USDT": "#f7931a",
  "ETH/USDT": "#627eea",
  "SOL/USDT": "#9945ff",
};

interface Props {
  trades: Trade[];
  showSource?: boolean;
}

export default function TradeTable({ trades, showSource }: Props) {
  if (!trades.length) {
    return <div className={styles.empty}>No trades found.</div>;
  }

  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Date</th>
            <th>Type</th>
            <th>Pair</th>
            <th>Price</th>
            <th>Qty</th>
            <th>Fee</th>
            <th>PnL</th>
            <th>Strategy</th>
            {showSource && <th>Source</th>}
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const pnlColor = t.pnl == null ? "" : t.pnl >= 0 ? styles.pos : styles.neg;
            const pairColor = PAIR_COLORS[t.pair] || "var(--blue)";
            return (
              <tr key={t.id}>
                <td className={styles.mono}>
                  {t.timestamp ? t.timestamp.substring(0, 16).replace("T", " ") : "—"}
                </td>
                <td>
                  <span className={`${styles.badge} ${styles[t.type] ?? ""}`}>
                    {t.type.toUpperCase()}
                  </span>
                </td>
                <td style={{ color: pairColor, fontWeight: 600 }}>{t.pair}</td>
                <td className={styles.mono}>{fmtPrice(t.price)}</td>
                <td className={styles.mono}>{t.qty.toFixed(6)}</td>
                <td className={styles.mono}>{t.fee.toFixed(4)}</td>
                <td className={`${styles.mono} ${pnlColor}`}>
                  {t.pnl != null
                    ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(4)} (${t.pnl_pct?.toFixed(2)}%)`
                    : "—"}
                </td>
                <td className={styles.muted}>{t.strategy ?? "—"}</td>
                {showSource && <td className={styles.muted}>{t.source}</td>}
                <td className={styles.reason}>{t.reason ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function fmtPrice(v: number) {
  return v >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : v.toFixed(4);
}
