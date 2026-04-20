import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPresets, applyPreset, fetchActivePreset, type Preset } from "../api/client";
import { StatCard, Alert, PageHeader, LoadingState, Badge, useToast, ToastContainer } from "../components/ui";
import styles from "./Presets.module.css";

export default function Presets() {
  const qc = useQueryClient();
  const { toasts, toast, dismiss } = useToast();

  const { data: presets, isLoading } = useQuery({
    queryKey: ["presets"],
    queryFn: fetchPresets,
  });

  const { data: active } = useQuery({
    queryKey: ["activePreset"],
    queryFn: fetchActivePreset,
  });

  const applyMutation = useMutation({
    mutationFn: applyPreset,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["activePreset"] });
      qc.invalidateQueries({ queryKey: ["providerStatus"] });
      qc.invalidateQueries({ queryKey: ["config"] });
      toast.success(`Preset "${data?.preset_id}" applied. Restart bot for changes to take effect.`);
    },
    onError: (err) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? String(err);
      toast.error(msg);
    },
  });

  if (isLoading) return <LoadingState message="Loading presets…" />;

  return (
    <div className={styles.page}>
      <PageHeader
        title="Investment Profiles"
        icon="🎛️"
        subtitle={
          <>
            One-click configurations combining strategy, risk, pairs, and timeframe.
            {active?.preset_id && (
              <span className={styles.activeTag}>
                {" Active: "}<strong>{active.preset_id}</strong>
              </span>
            )}
          </>
        }
      />

      <div className={styles.grid}>
        {(presets ?? []).map((p) => (
          <PresetCard
            key={p.id}
            preset={p}
            active={active?.preset_id === p.id}
            onApply={() => applyMutation.mutate(p.id)}
            loading={applyMutation.isPending && applyMutation.variables === p.id}
          />
        ))}
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}

function PresetCard({
  preset, active, onApply, loading,
}: { preset: Preset; active: boolean; onApply: () => void; loading: boolean }) {
  const riskColor =
    preset.max_drawdown_target <= 5  ? "green"  :
    preset.max_drawdown_target <= 15 ? "blue"   :
    preset.max_drawdown_target <= 20 ? "yellow" : "red";

  return (
    <div className={[styles.card, active ? styles.cardActive : ""].filter(Boolean).join(" ")}>
      <div className={styles.cardHeader}>
        <h3 className={styles.cardTitle}>{preset.label}</h3>
        {active && <Badge variant="green" label="● ACTIVE" />}
      </div>

      <p className={styles.description}>{preset.description}</p>

      <div className={styles.statsGrid}>
        <StatCard size="sm" label="Target APY" value={preset.target_apy}      color="green"      />
        <StatCard size="sm" label="Max DD"      value={`${preset.max_drawdown_target}%`} color={riskColor} />
        <StatCard size="sm" label="Strategy"    value={preset.strategy}                          />
        <StatCard size="sm" label="Timeframe"   value={preset.timeframe}                         />
        <StatCard size="sm" label="Leverage"    value={`${preset.leverage}x`} color={preset.leverage > 1 ? "yellow" : "muted"} />
        <StatCard size="sm" label="Per trade"   value={`$${preset.amount_per_trade}`}            />
      </div>

      <div className={styles.pairs}>
        <div className={styles.pairsLabel}>Pairs:</div>
        <div className={styles.pairsList}>
          {preset.pairs.map((pair) => (
            <Badge key={pair} variant="gray" label={pair} />
          ))}
        </div>
      </div>

      <div className={styles.riskControls}>
        <div className={styles.riskItem}>🛑 Daily loss stop: <strong>{preset.daily_loss_stop_pct}%</strong></div>
        <div className={styles.riskItem}>📊 Max positions: <strong>{preset.max_concurrent_positions}</strong></div>
        <div className={styles.riskItem}>{preset.use_futures ? "📈 Futures (long/short)" : "💎 Spot only"}</div>
        {preset.risk.atr_stop_enabled && (
          <div className={styles.riskItem}>🎯 ATR stop: <strong>{preset.risk.atr_stop_mult}x</strong></div>
        )}
      </div>

      <button
        className={[styles.applyBtn, active ? styles.applyBtnActive : ""].filter(Boolean).join(" ")}
        onClick={onApply}
        disabled={loading}
      >
        {loading ? "Applying…" : active ? "✓ Applied" : "Apply Preset"}
      </button>
    </div>
  );
}
