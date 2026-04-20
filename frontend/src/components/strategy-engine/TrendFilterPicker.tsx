/**
 * TrendFilterPicker — like StrategyPicker but:
 * - Only shows strategies compatible with a timeframe HIGHER than `executionTimeframe`
 * - Has a "No filter" option (trend filter is optional)
 */
import { useState, useMemo } from "react";
import type { Strategy, Timeframe } from "../../api/client";
import { Select } from "../ui";
import StrategyCard from "./StrategyCard";
import styles from "./StrategyPicker.module.css";
import tfStyles from "./TrendFilterPicker.module.css";

const TF_ORDER: Timeframe[] = ["15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"];

/** Returns timeframes strictly above the given one. */
function higherTFs(tf: Timeframe): Timeframe[] {
  const idx = TF_ORDER.indexOf(tf);
  if (idx === -1) return TF_ORDER;
  return TF_ORDER.slice(idx + 1);
}

interface TrendFilterPickerProps {
  strategies: Strategy[];
  executionTimeframe: Timeframe;
  /** Currently selected trend filter strategy (undefined = no filter) */
  value?: string;
  /** Currently selected trend filter timeframe */
  tfValue?: Timeframe;
  onStrategyChange: (name: string | undefined) => void;
  onTfChange: (tf: Timeframe) => void;
  /** Exclude the execution strategy itself */
  excludeStrategy?: string;
}

export default function TrendFilterPicker({
  strategies,
  executionTimeframe,
  value,
  tfValue,
  onStrategyChange,
  onTfChange,
  excludeStrategy,
}: TrendFilterPickerProps) {
  const [query, setQuery] = useState("");

  const availableHTFs = higherTFs(executionTimeframe);
  const selectedHTF = tfValue ?? availableHTFs[Math.min(1, availableHTFs.length - 1)];

  const tfOptions = availableHTFs.map((tf) => ({ value: tf, label: tf }));

  const compatible = useMemo(() => {
    return strategies.filter((s) => {
      if (excludeStrategy && s.name === excludeStrategy) return false;
      // Show if strategy has no TF restriction OR explicitly includes the selected HTF
      if (s.suitable_timeframes.length > 0 && !s.suitable_timeframes.includes(selectedHTF)) {
        return false;
      }
      if (query) {
        const q = query.toLowerCase();
        return s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q);
      }
      return true;
    });
  }, [strategies, selectedHTF, excludeStrategy, query]);

  return (
    <div className={styles.wrap}>
      <div className={tfStyles.header}>
        <div>
          <div className={styles.label}>HTF Trend Filter <span className={tfStyles.optional}>(optional)</span></div>
          <p className={tfStyles.hint}>
            Pick a strategy running on a higher timeframe to confirm the trend direction before entry.
          </p>
        </div>
        <button
          className={tfStyles.clearBtn}
          onClick={() => onStrategyChange(undefined)}
          disabled={!value}
        >
          ✕ Clear filter
        </button>
      </div>

      <div className={tfStyles.tfRow}>
        <span className={tfStyles.tfLabel}>Filter timeframe:</span>
        <Select
          options={tfOptions}
          value={selectedHTF}
          onChange={(v) => onTfChange(v as Timeframe)}
        />
      </div>

      <div className={tfStyles.searchRow}>
        <input
          className={tfStyles.search}
          placeholder="Search strategies…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {compatible.length === 0 ? (
        <div className={styles.empty}>No strategies support {selectedHTF} timeframe.</div>
      ) : (
        <div className={styles.grid}>
          {compatible.map((s) => (
            <StrategyCard
              key={s.name}
              strategy={s}
              selected={s.name === value}
              role={s.name === value ? "filter" : undefined}
              onClick={() => onStrategyChange(s.name === value ? undefined : s.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
