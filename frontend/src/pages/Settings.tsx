/**
 * Settings — Runtime configuration editor.
 *
 * Allows the operator to edit risk circuit breakers, anomaly alert thresholds,
 * and bot settings directly from the UI without touching config.yaml on disk.
 *
 * Sections:
 *   1. Risk Rules       — daily loss, drawdown, trade limits, blackout hours
 *   2. Anomaly Alerts   — slippage, balance gap, stale price thresholds
 *   3. Bot Settings     — active strategy, pairs, paper balance + fee
 *
 * Each section saves independently.  Changes take effect on the next bot start
 * (the running bot reads config on startup, not on every candle).
 */

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchSettings,
  fetchStrategies,
  patchRiskConfig,
  patchBotConfig,
} from "../api/client";
import type { SettingsSnapshot, RiskPatch, BotConfigPatch } from "../api/client";
import { useToast, ToastContainer, LoadingState, Alert } from "../components/ui";
import styles from "./Settings.module.css";

// ── Helpers ────────────────────────────────────────────────────────────────────

function toNum(v: string): number {
  const n = parseFloat(v);
  return isNaN(n) ? 0 : n;
}
function toInt(v: string): number {
  const n = parseInt(v, 10);
  return isNaN(n) ? 0 : n;
}

// ── Section card wrapper ───────────────────────────────────────────────────────

function SectionCard({
  title,
  description,
  children,
  onSave,
  saving,
  dirty,
}: {
  title:       string;
  description: string;
  children:    React.ReactNode;
  onSave:      () => void;
  saving:      boolean;
  dirty:       boolean;
}) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div>
          <h3 className={styles.cardTitle}>{title}</h3>
          <p className={styles.cardDesc}>{description}</p>
        </div>
        <button
          className={styles.saveBtn}
          onClick={onSave}
          disabled={saving || !dirty}
        >
          {saving ? "Saving…" : dirty ? "Save" : "Saved ✓"}
        </button>
      </div>
      <div className={styles.fields}>{children}</div>
    </div>
  );
}

// ── Field row ──────────────────────────────────────────────────────────────────

function Field({
  label,
  help,
  wide,
  children,
}: {
  label:    string;
  help?:    string;
  wide?:    boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`${styles.field} ${wide ? styles.fieldWide : ""}`}>
      <label className={styles.fieldLabel}>
        {label}
        {help && <span className={styles.fieldHelp}>{help}</span>}
      </label>
      {children}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Settings() {
  const qc = useQueryClient();
  const { toasts, toast, dismiss } = useToast();

  const { data: snap, isLoading, error } = useQuery<SettingsSnapshot>({
    queryKey: ["settings"],
    queryFn:  fetchSettings,
  });

  const { data: strategies } = useQuery({
    queryKey: ["strategies"],
    queryFn:  fetchStrategies,
  });

  // ── Risk section state ──────────────────────────────────────────────────────

  const [risk, setRisk] = useState<RiskPatch>({});
  const [riskDirty, setRiskDirty] = useState(false);

  // Initialise from server values once loaded
  useEffect(() => {
    if (snap) {
      setRisk({
        daily_loss_stop_pct:      snap.daily_loss_stop_pct,
        max_drawdown_pct:         snap.max_drawdown_pct,
        max_daily_trades:         snap.max_daily_trades,
        max_consecutive_losses:   snap.max_consecutive_losses,
        max_concurrent_positions: snap.max_concurrent_positions,
        leverage:                 snap.leverage,
        blackout_hours:           snap.blackout_hours,
        slippage_alert_pct:       snap.slippage_alert_pct,
        balance_gap_pct:          snap.balance_gap_pct,
        stale_price_candles:      snap.stale_price_candles,
      });
      setRiskDirty(false);
    }
  }, [snap]);

  function setRiskField<K extends keyof RiskPatch>(k: K, v: RiskPatch[K]) {
    setRisk((p) => ({ ...p, [k]: v }));
    setRiskDirty(true);
  }

  const riskMut = useMutation({
    mutationFn: () => patchRiskConfig(risk),
    onSuccess:  (res) => {
      toast.success(`Saved: ${res.updated.join(", ")}`);
      setRiskDirty(false);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? "Save failed";
      toast.error(msg);
    },
  });

  // ── Bot settings state ──────────────────────────────────────────────────────

  const [botDirty, setBotDirty] = useState(false);

  // Local editable string forms for pairs (newline-separated) and paper values
  const [pairsText, setPairsText]   = useState("");
  const [paperBal,  setPaperBal]    = useState("");
  const [paperFee,  setPaperFee]    = useState("");
  const [botStrategy, setBotStrategy] = useState("");

  useEffect(() => {
    if (snap) {
      setPairsText(snap.pairs.join("\n"));
      setPaperBal(String(snap.paper_initial_balance));
      setPaperFee(String(snap.paper_fee_pct));
      setBotStrategy(snap.active_strategy);
      setBotDirty(false);
    }
  }, [snap]);

  function buildBotPatch(): BotConfigPatch {
    const pairs = pairsText
      .split(/[\n,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    return {
      active_strategy: botStrategy,
      pairs,
      paper: {
        initial_balance: toNum(paperBal),
        fee_pct:         toNum(paperFee),
      },
    };
  }

  const botMut = useMutation({
    mutationFn: () => patchBotConfig(buildBotPatch()),
    onSuccess:  (res) => {
      toast.success(`Saved: ${res.updated.join(", ")}`);
      setBotDirty(false);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? "Save failed";
      toast.error(msg);
    },
  });

  // ── Render ──────────────────────────────────────────────────────────────────

  if (isLoading) return <LoadingState message="Loading settings…" />;
  if (error)     return <Alert variant="error">Failed to load settings.</Alert>;

  const strategyNames = strategies?.map((s) => s.name).sort() ?? [];

  return (
    <div className={styles.page}>

      {/* Page heading */}
      <div className={styles.pageHeader}>
        <h2 className={styles.pageTitle}>⚙️ Settings</h2>
        <p className={styles.pageDesc}>
          Edit risk rules, alert thresholds, and bot parameters.
          Changes take effect on the next bot start.
        </p>
      </div>

      {/* ── Risk Rules ── */}
      <SectionCard
        title="Risk Rules"
        description="Circuit breakers that halt or pause trading when limits are hit. Set a value to 0 to disable that rule."
        onSave={() => riskMut.mutate()}
        saving={riskMut.isPending}
        dirty={riskDirty}
      >
        <Field label="Daily loss stop (%)" help="Halt if equity drops more than this % in a single UTC day">
          <input
            type="number" step="0.1" min="0" max="100"
            className={styles.input}
            value={risk.daily_loss_stop_pct ?? ""}
            onChange={(e) => setRiskField("daily_loss_stop_pct", toNum(e.target.value))}
          />
        </Field>

        <Field label="Max drawdown (%)" help="Permanent halt if equity falls more than this % from its all-time peak. 0 = disabled">
          <input
            type="number" step="0.1" min="0" max="100"
            className={styles.input}
            value={risk.max_drawdown_pct ?? ""}
            onChange={(e) => setRiskField("max_drawdown_pct", toNum(e.target.value))}
          />
        </Field>

        <Field label="Max daily trades" help="No new trades after this many per UTC day. 0 = unlimited">
          <input
            type="number" step="1" min="0"
            className={styles.input}
            value={risk.max_daily_trades ?? ""}
            onChange={(e) => setRiskField("max_daily_trades", toInt(e.target.value))}
          />
        </Field>

        <Field label="Max consecutive losses" help="Pause after this many losses in a row. 0 = disabled">
          <input
            type="number" step="1" min="0"
            className={styles.input}
            value={risk.max_consecutive_losses ?? ""}
            onChange={(e) => setRiskField("max_consecutive_losses", toInt(e.target.value))}
          />
        </Field>

        <Field label="Max concurrent positions" help="Maximum number of open positions at once">
          <input
            type="number" step="1" min="1" max="20"
            className={styles.input}
            value={risk.max_concurrent_positions ?? ""}
            onChange={(e) => setRiskField("max_concurrent_positions", toInt(e.target.value))}
          />
        </Field>

        <Field label="Leverage" help="Position size multiplier. Capped at 3× by the risk engine">
          <input
            type="number" step="0.1" min="1" max="3"
            className={styles.input}
            value={risk.leverage ?? ""}
            onChange={(e) => setRiskField("leverage", toNum(e.target.value))}
          />
        </Field>

        <Field
          label="Blackout hours (UTC)"
          help={'No trading during this window, e.g. "22:00-06:00". Leave empty to always trade'}
        >
          <input
            type="text"
            placeholder="22:00-06:00"
            className={styles.input}
            value={risk.blackout_hours ?? ""}
            onChange={(e) => setRiskField("blackout_hours", e.target.value)}
          />
        </Field>
      </SectionCard>

      {/* ── Anomaly Alerts ── */}
      <SectionCard
        title="Anomaly Alerts"
        description="Thresholds for Telegram notifications. Alerts are informational — they don't halt trading."
        onSave={() => riskMut.mutate()}
        saving={riskMut.isPending}
        dirty={riskDirty}
      >
        <Field label="Slippage alert (%)" help="Alert when actual fill price deviates more than this % from expected">
          <input
            type="number" step="0.1" min="0" max="100"
            className={styles.input}
            value={risk.slippage_alert_pct ?? ""}
            onChange={(e) => setRiskField("slippage_alert_pct", toNum(e.target.value))}
          />
        </Field>

        <Field label="Balance gap alert (%)" help="Alert when live exchange balance differs from internal ledger by more than this %">
          <input
            type="number" step="0.1" min="0" max="100"
            className={styles.input}
            value={risk.balance_gap_pct ?? ""}
            onChange={(e) => setRiskField("balance_gap_pct", toNum(e.target.value))}
          />
        </Field>

        <Field label="Stale price candles" help="Alert if a pair's price is unchanged for this many consecutive candles">
          <input
            type="number" step="1" min="1"
            className={styles.input}
            value={risk.stale_price_candles ?? ""}
            onChange={(e) => setRiskField("stale_price_candles", toInt(e.target.value))}
          />
        </Field>
      </SectionCard>

      {/* ── Bot Settings ── */}
      <SectionCard
        title="Bot Settings"
        description="Default strategy, trading pairs, and paper trading parameters used when starting the bot."
        onSave={() => botMut.mutate()}
        saving={botMut.isPending}
        dirty={botDirty}
      >
        <Field label="Active strategy" help="Default strategy shown in the Bot tab">
          <select
            className={styles.select}
            value={botStrategy}
            onChange={(e) => { setBotStrategy(e.target.value); setBotDirty(true); }}
          >
            {strategyNames.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </Field>

        <Field label="Trading pairs" help="One pair per line (e.g. BTC/USDT). Also accepted: comma-separated" wide>
          <textarea
            rows={4}
            className={styles.textarea}
            value={pairsText}
            onChange={(e) => { setPairsText(e.target.value); setBotDirty(true); }}
            spellCheck={false}
          />
        </Field>

        <Field label="Paper initial balance (USDT)" help="Starting balance for paper trading sessions">
          <input
            type="number" step="1" min="1"
            className={styles.input}
            value={paperBal}
            onChange={(e) => { setPaperBal(e.target.value); setBotDirty(true); }}
          />
        </Field>

        <Field label="Paper fee (%)" help="Simulated trading fee applied to paper orders">
          <input
            type="number" step="0.01" min="0" max="5"
            className={styles.input}
            value={paperFee}
            onChange={(e) => { setPaperFee(e.target.value); setBotDirty(true); }}
          />
        </Field>
      </SectionCard>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
