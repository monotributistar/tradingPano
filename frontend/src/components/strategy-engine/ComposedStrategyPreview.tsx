import { useState } from "react";
import type { Strategy, StrategyConfigData } from "../../api/client";
import { Badge, Button, Card, Input, Textarea, Tooltip } from "../ui";
import type { RiskOverride } from "./RiskProfileForm";
import styles from "./ComposedStrategyPreview.module.css";

interface ComposedStrategyPreviewProps {
  executionStrategy?: Strategy;
  executionTimeframe?: string;
  trendFilterStrategy?: Strategy;
  trendFilterTimeframe?: string;
  risk: RiskOverride;
  pairs: string[];
  /** Existing config being edited (undefined = creating new) */
  existing?: StrategyConfigData;
  onSave: (name: string, notes: string) => Promise<void>;
  onActivate?: () => Promise<void>;
  isSaving?: boolean;
  isActivating?: boolean;
}

export default function ComposedStrategyPreview({
  executionStrategy,
  executionTimeframe,
  trendFilterStrategy,
  trendFilterTimeframe,
  risk,
  pairs,
  existing,
  onSave,
  onActivate,
  isSaving,
  isActivating,
}: ComposedStrategyPreviewProps) {
  const [name, setName] = useState(existing?.name ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [nameError, setNameError] = useState("");

  function handleSave() {
    if (!name.trim()) { setNameError("Name is required"); return; }
    setNameError("");
    onSave(name.trim(), notes.trim());
  }

  const ready = !!executionStrategy && !!executionTimeframe;

  return (
    <div className={styles.wrap}>
      <div className={styles.sectionTitle}>Preview &amp; Save</div>

      {/* Composition summary */}
      <Card padding="sm">
        <div className={styles.composition}>
          {/* Execution block */}
          <div className={styles.block}>
            <span className={styles.blockLabel}>⚡ Execution</span>
            {executionStrategy ? (
              <>
                <span className={styles.stratName}>{executionStrategy.name}</span>
                <Badge variant="blue" label={executionTimeframe ?? "–"} />
              </>
            ) : (
              <span className={styles.empty}>Not selected</span>
            )}
          </div>

          {/* Arrow */}
          {trendFilterStrategy && <span className={styles.arrow}>+</span>}

          {/* Trend filter block */}
          {trendFilterStrategy && (
            <div className={styles.block}>
              <span className={styles.blockLabel}>🔭 HTF Filter</span>
              <span className={styles.stratName}>{trendFilterStrategy.name}</span>
              <Badge variant="purple" label={trendFilterTimeframe ?? "–"} />
            </div>
          )}
        </div>

        {/* Risk summary */}
        <div className={styles.riskSummary}>
          {[
            ["SL", risk.stop_loss_pct, "%"],
            ["TP", risk.take_profit_pct, "%"],
            ["Pos", risk.position_size_pct, "%"],
            ["Lev", risk.leverage, "×"],
            ["Max DD", risk.max_drawdown_pct, "%"],
            ["Daily Stop", risk.daily_loss_stop_pct, "%"],
          ].map(([lbl, val, unit]) =>
            val != null ? (
              <Tooltip key={String(lbl)} content={String(lbl)}>
                <span className={styles.riskChip}>
                  {lbl} {val}{unit}
                </span>
              </Tooltip>
            ) : null,
          )}
        </div>

        {/* Pairs */}
        {pairs.length > 0 && (
          <div className={styles.pairs}>
            <span className={styles.pairsLabel}>Pairs:</span>
            {pairs.map((p) => <Badge key={p} variant="gray" label={p} />)}
          </div>
        )}
      </Card>

      {/* Save form */}
      <div className={styles.form}>
        <Input
          label="Config name"
          placeholder="e.g. BTC scalp + EMA trend filter"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={nameError}
        />
        <Textarea
          label="Notes (optional)"
          placeholder="Describe when to use this configuration…"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
        />
      </div>

      <div className={styles.actions}>
        <Button
          variant="primary"
          onClick={handleSave}
          loading={isSaving}
          disabled={!ready || isSaving}
        >
          {existing ? "Update config" : "Save config"}
        </Button>
        {onActivate && existing && (
          <Button
            variant="secondary"
            onClick={onActivate}
            loading={isActivating}
            disabled={isActivating}
          >
            ▶ Activate now
          </Button>
        )}
      </div>

      {!ready && (
        <p className={styles.notReady}>Select an execution strategy and timeframe to continue.</p>
      )}
    </div>
  );
}
