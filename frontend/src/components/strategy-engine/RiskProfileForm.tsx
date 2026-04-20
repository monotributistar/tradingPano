import type { RiskProfileData, Strategy, Timeframe } from "../../api/client";
import { Input, Tooltip } from "../ui";
import styles from "./RiskProfileForm.module.css";

/** Full risk override state for the form */
export interface RiskOverride extends Partial<RiskProfileData> {
  leverage?: number;
  max_drawdown_pct?: number;
  daily_loss_stop_pct?: number;
}

interface RiskProfileFormProps {
  /** Strategy defaults (pre-filled values) */
  strategy?: Strategy;
  /** Current form values */
  value: RiskOverride;
  onChange: (v: RiskOverride) => void;
  /** Global config values — shown as "global" hints */
  globalLeverage?: number;
  globalMaxDrawdown?: number;
  globalDailyStop?: number;
}

const MAX_LEVERAGE = 15;

function numField(
  label: string,
  hint: string,
  fieldKey: keyof RiskOverride,
  value: RiskOverride,
  onChange: (v: RiskOverride) => void,
  min: number,
  max: number,
  step = 0.5,
  suffix = "%",
) {
  const raw = value[fieldKey] as number | undefined;
  return (
    <div className={styles.field}>
      <Tooltip content={hint} placement="right">
        <label className={styles.label}>{label}</label>
      </Tooltip>
      <div className={styles.inputRow}>
        <Input
          type="number"
          value={raw ?? ""}
          onChange={(e) => {
            const n = e.target.value === "" ? undefined : Number(e.target.value);
            onChange({ ...value, [fieldKey]: n });
          }}
          suffix={suffix}
          hint={`${min}–${max}`}
        />
        <input
          type="range"
          className={styles.range}
          min={min}
          max={max}
          step={step}
          value={raw ?? min}
          onChange={(e) => onChange({ ...value, [fieldKey]: Number(e.target.value) })}
        />
      </div>
    </div>
  );
}

export default function RiskProfileForm({
  strategy,
  value,
  onChange,
  globalLeverage,
  globalMaxDrawdown,
  globalDailyStop,
}: RiskProfileFormProps) {
  const def = strategy?.risk_profile;
  const maxLev = Math.min(MAX_LEVERAGE, strategy?.max_leverage ?? MAX_LEVERAGE);

  return (
    <div className={styles.wrap}>
      <div className={styles.sectionTitle}>Risk Parameters</div>

      {def && (
        <div className={styles.defaults}>
          <span>Strategy defaults →</span>
          <span>SL {def.stop_loss_pct}%</span>
          <span>TP {def.take_profit_pct}%</span>
          <span>Pos {def.position_size_pct}%</span>
          {strategy && <span>Lev {strategy.recommended_leverage}×</span>}
        </div>
      )}

      <div className={styles.grid}>
        {numField(
          "Stop Loss %",
          "Close trade when loss exceeds this % from entry",
          "stop_loss_pct",
          value,
          onChange,
          0.1,
          20,
          0.1,
          "%",
        )}
        {numField(
          "Take Profit %",
          "Close trade when profit reaches this % from entry",
          "take_profit_pct",
          value,
          onChange,
          0.1,
          50,
          0.1,
          "%",
        )}
        {numField(
          "Position Size %",
          "% of capital allocated per trade",
          "position_size_pct",
          value,
          onChange,
          0.5,
          50,
          0.5,
          "%",
        )}
        {numField(
          "Leverage",
          `Multiplier applied to position size. Max for this strategy: ${maxLev}×`,
          "leverage",
          value,
          onChange,
          1,
          maxLev,
          0.5,
          "×",
        )}
        {numField(
          "Max Drawdown %",
          `Stop trading if portfolio drops this % from peak. Global: ${globalMaxDrawdown ?? "–"}%`,
          "max_drawdown_pct",
          value,
          onChange,
          1,
          50,
          0.5,
          "%",
        )}
        {numField(
          "Daily Loss Stop %",
          `Halt trading if daily P&L drops below this %. Global: ${globalDailyStop ?? "–"}%`,
          "daily_loss_stop_pct",
          value,
          onChange,
          0.5,
          30,
          0.5,
          "%",
        )}
      </div>

      {globalLeverage !== undefined && (value.leverage ?? 0) > globalLeverage && (
        <div className={styles.warning}>
          ⚠ Strategy leverage ({value.leverage}×) is higher than global setting ({globalLeverage}×).
          The lower value is always enforced.
        </div>
      )}

      <button
        className={styles.resetBtn}
        onClick={() => {
          if (!def) return;
          onChange({
            stop_loss_pct: def.stop_loss_pct,
            take_profit_pct: def.take_profit_pct,
            position_size_pct: def.position_size_pct,
            leverage: strategy?.recommended_leverage,
            max_drawdown_pct: globalMaxDrawdown,
            daily_loss_stop_pct: globalDailyStop,
          });
        }}
        disabled={!def}
      >
        ↺ Reset to strategy defaults
      </button>
    </div>
  );
}
