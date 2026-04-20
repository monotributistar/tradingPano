import { useState, useMemo } from "react";
import type { Strategy, Timeframe } from "../../api/client";
import { Input, Select } from "../ui";
import StrategyCard from "./StrategyCard";
import styles from "./StrategyPicker.module.css";

interface StrategyPickerProps {
  strategies: Strategy[];
  /** Currently selected strategy name */
  value?: string;
  onChange: (name: string) => void;
  /** If set, only show strategies suitable for this timeframe */
  filterTimeframe?: Timeframe;
  /** Role badge shown on the selected card */
  role?: "execution" | "filter";
  /** Exclude certain strategy names (e.g. already picked as execution) */
  exclude?: string[];
  /** Label shown above the picker */
  label?: string;
}

const MARKET_OPTIONS = [
  { value: "", label: "All market types" },
  { value: "trending", label: "Trending" },
  { value: "ranging", label: "Ranging" },
  { value: "both", label: "Both" },
];

const FREQ_OPTIONS = [
  { value: "", label: "All frequencies" },
  { value: "high", label: "High frequency" },
  { value: "medium", label: "Medium frequency" },
  { value: "low", label: "Low frequency" },
];

export default function StrategyPicker({
  strategies,
  value,
  onChange,
  filterTimeframe,
  role,
  exclude = [],
  label,
}: StrategyPickerProps) {
  const [query, setQuery] = useState("");
  const [marketFilter, setMarketFilter] = useState("");
  const [freqFilter, setFreqFilter] = useState("");

  const filtered = useMemo(() => {
    return strategies.filter((s) => {
      if (exclude.includes(s.name)) return false;
      if (filterTimeframe && s.suitable_timeframes.length > 0) {
        if (!s.suitable_timeframes.includes(filterTimeframe)) return false;
      }
      if (marketFilter && s.market_type !== marketFilter && marketFilter !== "both") {
        if (s.market_type !== marketFilter) return false;
      }
      if (freqFilter && s.trade_frequency !== freqFilter) return false;
      if (query) {
        const q = query.toLowerCase();
        return s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q);
      }
      return true;
    });
  }, [strategies, filterTimeframe, marketFilter, freqFilter, query, exclude]);

  return (
    <div className={styles.wrap}>
      {label && <div className={styles.label}>{label}</div>}

      <div className={styles.filters}>
        <Input
          placeholder="Search strategies…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Select
          options={MARKET_OPTIONS}
          value={marketFilter}
          onChange={setMarketFilter}
          placeholder="Market type"
        />
        <Select
          options={FREQ_OPTIONS}
          value={freqFilter}
          onChange={setFreqFilter}
          placeholder="Frequency"
        />
      </div>

      {filtered.length === 0 ? (
        <div className={styles.empty}>No strategies match the current filters.</div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((s) => (
            <StrategyCard
              key={s.name}
              strategy={s}
              selected={s.name === value}
              role={s.name === value ? role : undefined}
              onClick={() => onChange(s.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
