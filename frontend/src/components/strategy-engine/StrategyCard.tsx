import type { Strategy } from "../../api/client";
import { Badge, Tooltip } from "../ui";
import { getStrategyIndicators } from "../../lib/strategyIndicators";
import styles from "./StrategyCard.module.css";

interface StrategyCardProps {
  strategy: Strategy;
  selected?: boolean;
  role?: "execution" | "filter";
  onClick?: () => void;
}

/** Converts market_type / suitable_market_conditions to a badge variant. */
function marketBadge(market_type: string) {
  if (market_type === "trending") return { variant: "blue" as const, label: "Trending" };
  if (market_type === "ranging")  return { variant: "yellow" as const, label: "Ranging" };
  return { variant: "gray" as const, label: "Both" };
}

function freqBadge(freq: string) {
  if (freq === "high")   return { variant: "green" as const, label: "High freq" };
  if (freq === "medium") return { variant: "blue" as const, label: "Med freq" };
  return { variant: "gray" as const, label: "Low freq" };
}

export default function StrategyCard({ strategy, selected, role, onClick }: StrategyCardProps) {
  const mb         = marketBadge(strategy.market_type);
  const fb         = freqBadge(strategy.trade_frequency);
  const indicators = getStrategyIndicators(strategy.name);
  const leverageColor = strategy.recommended_leverage >= 5 ? "red" : strategy.recommended_leverage >= 3 ? "yellow" : "green";

  return (
    <div
      className={[styles.card, selected ? styles.selected : "", onClick ? styles.clickable : ""].filter(Boolean).join(" ")}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") onClick(); } : undefined}
    >
      {role && (
        <span className={styles.rolePill}>
          {role === "execution" ? "⚡ Execution" : "🔭 HTF Filter"}
        </span>
      )}

      <div className={styles.name}>{strategy.name}</div>
      <p className={styles.desc}>{strategy.description}</p>

      <div className={styles.badges}>
        <Badge variant={mb.variant} label={mb.label} dot />
        <Badge variant={fb.variant} label={fb.label} />
        <Badge variant="gray" label={`Liq: ${strategy.min_liquidity}`} />
      </div>

      <div className={styles.meta}>
        <Tooltip content={`Suitable TFs: ${strategy.suitable_timeframes.join(", ") || "any"}`}>
          <span className={styles.metaItem}>
            🕐 {strategy.suitable_timeframes.slice(0, 3).join(" · ") || "any"}
          </span>
        </Tooltip>
        <Tooltip content={`Recommended leverage: ${strategy.recommended_leverage}× · Max: ${strategy.max_leverage}×`}>
          <span className={[styles.metaItem, styles[`lev${leverageColor}`]].join(" ")}>
            ⚡ {strategy.recommended_leverage}× rec · {strategy.max_leverage}× max
          </span>
        </Tooltip>
      </div>

      {indicators.length > 0 && (
        <div className={styles.indicatorChips}>
          {indicators.map((ind) => (
            <span
              key={ind.id}
              className={styles.indicatorChip}
              style={{
                background: `${ind.color ?? "#888"}1a`,
                border: `1px solid ${ind.color ?? "#888"}44`,
                color: ind.color ?? "var(--muted)",
              }}
            >
              {ind.label}
            </span>
          ))}
        </div>
      )}

      <div className={styles.riskRow}>
        <span title="Stop loss">SL {strategy.risk_profile.stop_loss_pct}%</span>
        <span title="Take profit">TP {strategy.risk_profile.take_profit_pct}%</span>
        <span title="Position size">Pos {strategy.risk_profile.position_size_pct}%</span>
      </div>
    </div>
  );
}
