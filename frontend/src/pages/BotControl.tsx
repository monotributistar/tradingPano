/**
 * BotControl — Live / paper trading control panel.
 *
 * Left column  : Status card, live equity, trade feed, event log
 * Right column : Start form
 *   - "Quick Start" mode: raw strategy picker + pair selection
 *   - "Saved Config" mode: pick a composed StrategyConfig from the
 *     Strategy Engine; the config provides strategy, timeframe, pairs,
 *     and risk overrides automatically
 */
import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchBotStatus, fetchStrategies, fetchStrategyConfigs,
  startBot, stopBot, fetchBotEvents,
  type BotStartParams, type StrategyConfigData,
} from "../api/client";
import type { BotSocketTrade, BotSocketEquity, BotSocketEvent } from "../hooks/useBotSocket";
import { useBotSocket } from "../hooks/useBotSocket";
import {
  Badge, TabBar, Alert, DetailRow, PageHeader,
} from "../components/ui";
import StrategyPicker from "../components/strategy-engine/StrategyPicker";
import { Modal } from "../components/ui";
import { fmtUptime } from "../lib/formatUtils";
import styles from "./BotControl.module.css";

// ── Constants ─────────────────────────────────────────────────────────────────

const ALL_PAIRS = [
  "BTC/USDT", "ETH/USDT", "BNB/USDT",
  "SOL/USDT", "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT",
  "MATIC/USDT", "LINK/USDT", "NEAR/USDT", "APT/USDT", "ARB/USDT",
  "OP/USDT", "DOGE/USDT", "LTC/USDT", "ATOM/USDT", "INJ/USDT",
];

const DEFAULT_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "NEAR/USDT"];

const EVENT_EMOJI: Record<string, string> = {
  start:    "▶️",
  stop:     "⏹",
  crash:    "❌",
  halt:     "⚠️",
  resume:   "🔄",
  watchdog: "🐕",
};

interface LiveTrade extends BotSocketTrade { at: string; }

// ── Main component ────────────────────────────────────────────────────────────

export default function BotControl() {
  const qc = useQueryClient();

  // ── Form state ──────────────────────────────────────────────────────────────
  const [configSource, setConfigSource] = useState<"quick" | "saved">("quick");
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null);
  const [stratPickerOpen, setStratPickerOpen]   = useState(false);

  const [form, setForm] = useState<BotStartParams>({
    mode:     "paper",
    strategy: "mean_reversion",
    pairs:    [...DEFAULT_PAIRS],
    restore:  false,
  });

  // ── WebSocket live state ────────────────────────────────────────────────────
  const [wsEquity,    setWsEquity]    = useState<BotSocketEquity | null>(null);
  const [liveTrades,  setLiveTrades]  = useState<LiveTrade[]>([]);
  const [liveEvents,  setLiveEvents]  = useState<BotSocketEvent[]>([]);
  const [wsStatus,    setWsStatus]    = useState<Record<string, unknown> | null>(null);

  const handleWsMessage = useCallback(
    (msg: import("../hooks/useBotSocket").BotSocketMessage) => {
      if (msg.type === "status")  { setWsStatus(msg.payload as unknown as Record<string, unknown>); qc.invalidateQueries({ queryKey: ["botStatus"] }); }
      if (msg.type === "equity")  setWsEquity(msg.payload);
      if (msg.type === "trade")   setLiveTrades((prev) => [{ ...msg.payload, at: new Date().toISOString() }, ...prev].slice(0, 30));
      if (msg.type === "event")   setLiveEvents((prev) => [msg.payload, ...prev].slice(0, 50));
    },
    [qc],
  );

  const { connected } = useBotSocket(handleWsMessage);

  // ── Queries ─────────────────────────────────────────────────────────────────
  const { data: polledStatus } = useQuery({
    queryKey:        ["botStatus"],
    queryFn:         fetchBotStatus,
    refetchInterval: connected ? false : 5000,
  });

  const status  = (wsStatus as unknown as typeof polledStatus) ?? polledStatus;
  const running = status?.running  ?? false;
  const crashed = status?.crashed  ?? false;

  const { data: strategies } = useQuery({ queryKey: ["strategies"],      queryFn: fetchStrategies });
  const { data: savedConfigs } = useQuery({ queryKey: ["strategyConfigs"], queryFn: fetchStrategyConfigs });

  const { data: dbEvents } = useQuery({
    queryKey:        ["botEvents"],
    queryFn:         () => fetchBotEvents(20),
    refetchInterval: connected ? false : 10_000,
  });

  const allEvents = [
    ...liveEvents.map((e) => ({ ...e, occurred_at: new Date().toISOString() })),
    ...(dbEvents ?? []),
  ].slice(0, 20);

  // ── Mutations ───────────────────────────────────────────────────────────────
  const startMut = useMutation({
    mutationFn: startBot,
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["botStatus"] }),
  });
  const stopMut = useMutation({
    mutationFn: stopBot,
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["botStatus"] }),
  });

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function togglePair(p: string) {
    setForm((f) => ({
      ...f,
      pairs: f.pairs.includes(p) ? f.pairs.filter((x) => x !== p) : [...f.pairs, p],
    }));
  }

  function selectConfig(cfg: StrategyConfigData) {
    setSelectedConfigId(cfg.id);
    setForm((f) => ({
      ...f,
      strategy: cfg.execution_strategy,
      pairs:    cfg.pairs?.length ? cfg.pairs : f.pairs,
    }));
  }

  function handleStart() {
    startMut.mutate({
      ...form,
      strategy_config_id: configSource === "saved" ? selectedConfigId : null,
    });
  }

  const selectedConfig = savedConfigs?.find((c) => c.id === selectedConfigId);
  const uptime = status?.uptime_seconds ? fmtUptime(status.uptime_seconds) : null;

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>

      {/* ── Left: status + feeds ──────────────────────────────────────────── */}
      <div className={styles.left}>

        {/* Status card */}
        <div className={`${styles.statusCard} ${crashed ? styles.statusCrashed : ""}`}>
          <div className={styles.statusRow}>
            <div className={`${styles.dot} ${running ? styles.dotGreen : crashed ? styles.dotRed : styles.dotGray}`} />
            <span className={styles.statusText}>
              {running ? "RUNNING" : crashed ? "CRASHED" : "IDLE"}
            </span>
            <span className={styles.wsBadge} title={connected ? "WebSocket live" : "Polling"}>
              {connected ? "⚡ live" : "🔄 poll"}
            </span>
          </div>

          {running && (
            <div className={styles.statusDetails}>
              <DetailRow label="Mode"     value={(status?.mode as string)?.toUpperCase() ?? "—"} />
              <DetailRow label="Strategy" value={(status?.strategy as string) ?? "—"} />
              {status?.strategy_config_name && (
                <DetailRow label="Config" value={status.strategy_config_name as string} />
              )}
              <DetailRow label="Pairs" value={((status?.pairs as string[]) ?? []).join(", ")} />
              {uptime && <DetailRow label="Uptime" value={uptime} />}
            </div>
          )}

          {wsEquity && running && (
            <div className={styles.equityBar}>
              <span className={styles.equityLabel}>Equity</span>
              <span className={styles.equityValue}>{wsEquity.total_equity.toFixed(2)} USDT</span>
              <span className={styles.equityMeta}>
                free {wsEquity.balance_usdt.toFixed(2)} · pos {wsEquity.positions_value.toFixed(2)}
              </span>
            </div>
          )}

          {status?.error && (
            <Alert variant="error" compact>{status.error as string}</Alert>
          )}

          {running && (
            <button
              className={styles.stopBtn}
              onClick={() => stopMut.mutate()}
              disabled={stopMut.isPending}
            >
              {stopMut.isPending ? "Stopping…" : "⏹ Stop Bot"}
            </button>
          )}
        </div>

        {/* Live trade feed */}
        {liveTrades.length > 0 && (
          <div className={styles.feedCard}>
            <div className={styles.feedTitle}>⚡ Live trades</div>
            {liveTrades.slice(0, 8).map((t, i) => (
              <div key={i} className={styles.tradePill}>
                <span className={t.type === "buy" || t.type === "short" ? styles.open : styles.close}>
                  {t.type.toUpperCase()}
                </span>
                <span className={styles.tradePair}>{t.pair}</span>
                <span className={styles.tradePrice}>{t.price.toFixed(2)}</span>
                {t.pnl != null && (
                  <span className={t.pnl >= 0 ? styles.pnlPos : styles.pnlNeg}>
                    {t.pnl >= 0 ? "+" : ""}{t.pnl.toFixed(2)}$
                  </span>
                )}
                <span className={styles.tradeTime}>{t.at.substring(11, 19)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Event log */}
        {allEvents.length > 0 && (
          <div className={styles.feedCard}>
            <div className={styles.feedTitle}>📋 Event log</div>
            {allEvents.slice(0, 8).map((e, i) => (
              <div key={i} className={styles.eventRow}>
                <span className={`${styles.eventBadge} ${styles[`evt_${e.event_type}`] ?? ""}`}>
                  {EVENT_EMOJI[e.event_type] ?? "•"} {e.event_type}
                </span>
                {e.detail && <span className={styles.eventDetail}>{e.detail}</span>}
                {"occurred_at" in e && (
                  <span className={styles.tradeTime}>
                    {String((e as { occurred_at: string }).occurred_at).substring(11, 19)}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {form.mode === "live" && !running && (
          <Alert variant="warning">
            Live mode executes real trades. Make sure exchange API keys are set
            in your <code>.env</code> file.
          </Alert>
        )}
      </div>

      {/* ── Right: config form ────────────────────────────────────────────── */}
      {!running && (
        <div className={styles.configCard}>
          <PageHeader title="Start Bot" icon="🤖" />

          {/* Mode toggle */}
          <div className={styles.section}>
            <span className={styles.label}>Mode</span>
            <TabBar
              variant="buttons"
              size="sm"
              tabs={[
                { value: "paper", label: "📋 Paper" },
                { value: "live",  label: "⚡ Live"  },
              ]}
              active={form.mode}
              onChange={(v) => setForm((f) => ({ ...f, mode: v as "paper" | "live" }))}
            />
          </div>

          {/* Config source toggle */}
          <div className={styles.section}>
            <span className={styles.label}>Strategy source</span>
            <TabBar
              variant="pills"
              size="sm"
              tabs={[
                { value: "quick", label: "⚡ Quick Start" },
                { value: "saved", label: "📦 Saved Config", badge: savedConfigs?.length },
              ]}
              active={configSource}
              onChange={(v) => { setConfigSource(v as "quick" | "saved"); setSelectedConfigId(null); }}
            />
          </div>

          {/* ── Quick start ── */}
          {configSource === "quick" && (
            <>
              <div className={styles.section}>
                <span className={styles.label}>Strategy</span>
                <StrategyPreviewWidget
                  strategy={(strategies ?? []).find((s) => s.name === form.strategy)}
                  onBrowse={() => setStratPickerOpen(true)}
                />
              </div>

              <div className={styles.section}>
                <div className={styles.labelRow}>
                  <span className={styles.label}>Pairs</span>
                  <button
                    className={styles.allBtn}
                    onClick={() => setForm((f) => ({ ...f, pairs: [...ALL_PAIRS] }))}
                  >
                    All
                  </button>
                  <button
                    className={styles.allBtn}
                    onClick={() => setForm((f) => ({ ...f, pairs: [] }))}
                  >
                    None
                  </button>
                </div>
                <div className={styles.pairGrid}>
                  {ALL_PAIRS.map((p) => (
                    <button
                      key={p}
                      className={`${styles.pairBtn} ${form.pairs.includes(p) ? styles.pairBtnActive : ""}`}
                      onClick={() => togglePair(p)}
                    >
                      {p.replace("/USDT", "")}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* ── Saved config ── */}
          {configSource === "saved" && (
            <div className={styles.section}>
              <span className={styles.label}>Select a saved configuration</span>
              {!savedConfigs?.length ? (
                <div className={styles.emptyConfigs}>
                  No saved configs yet. Build one in the <strong>⚡ Strategy</strong> tab.
                </div>
              ) : (
                <div className={styles.configList}>
                  {savedConfigs.map((cfg) => (
                    <ConfigCard
                      key={cfg.id}
                      config={cfg}
                      selected={selectedConfigId === cfg.id}
                      onSelect={() => selectConfig(cfg)}
                    />
                  ))}
                </div>
              )}

              {/* Pair override when using a config without specific pairs */}
              {selectedConfig && !selectedConfig.pairs?.length && (
                <div className={styles.section}>
                  <div className={styles.labelRow}>
                    <span className={styles.label}>Pairs (config has none — select manually)</span>
                    <button className={styles.allBtn} onClick={() => setForm((f) => ({ ...f, pairs: [...DEFAULT_PAIRS] }))}>
                      Reset
                    </button>
                  </div>
                  <div className={styles.pairGrid}>
                    {ALL_PAIRS.map((p) => (
                      <button
                        key={p}
                        className={`${styles.pairBtn} ${form.pairs.includes(p) ? styles.pairBtnActive : ""}`}
                        onClick={() => togglePair(p)}
                      >
                        {p.replace("/USDT", "")}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Restore checkbox */}
          <label className={styles.restoreRow}>
            <input
              type="checkbox"
              checked={form.restore}
              onChange={(e) => setForm((f) => ({ ...f, restore: e.target.checked }))}
            />
            <span>Resume open positions from last saved state</span>
          </label>
          {form.restore && (
            <div className={styles.restoreHint}>
              The bot will restore positions from the last saved BotState.
              Use after a VPS reboot or manual stop with live positions open.
            </div>
          )}

          {form.pairs.length === 0 && (
            <Alert variant="error" compact>Select at least one pair.</Alert>
          )}
          {configSource === "saved" && !selectedConfigId && (
            <Alert variant="warning" compact>Select a saved configuration to continue.</Alert>
          )}

          <button
            className={styles.startBtn}
            onClick={handleStart}
            disabled={
              startMut.isPending ||
              form.pairs.length === 0 ||
              (configSource === "saved" && !selectedConfigId)
            }
          >
            {startMut.isPending ? "Starting…" : `▶ Start ${form.mode} bot`}
          </button>

          {startMut.isError && (
            <Alert variant="error" compact>
              {String((startMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? startMut.error)}
            </Alert>
          )}
        </div>
      )}

      {/* Strategy picker modal (quick-start only) */}
      <Modal
        open={stratPickerOpen}
        onClose={() => setStratPickerOpen(false)}
        title="⚡ Pick a Strategy"
        width="860px"
      >
        <StrategyPicker
          strategies={strategies ?? []}
          value={form.strategy}
          role="execution"
          onChange={(name) => {
            setForm((f) => ({ ...f, strategy: name }));
            setStratPickerOpen(false);
          }}
        />
      </Modal>
    </div>
  );
}

// ── StrategyPreviewWidget ─────────────────────────────────────────────────────
// Compact card showing the currently selected strategy with a "Change" button.

import type { Strategy } from "../api/client";

function StrategyPreviewWidget({
  strategy,
  onBrowse,
}: {
  strategy?: Strategy;
  onBrowse: () => void;
}) {
  if (!strategy) {
    return (
      <button className={styles.stratPickBtn} onClick={onBrowse}>
        Choose a strategy…
      </button>
    );
  }

  const marketColor =
    strategy.market_type === "trending" ? "blue"
    : strategy.market_type === "ranging" ? "yellow"
    : "gray";

  return (
    <div className={styles.stratPreview}>
      <div className={styles.stratInfo}>
        <span className={styles.stratName}>{strategy.name}</span>
        <div className={styles.stratBadges}>
          <Badge variant={marketColor as "blue" | "yellow" | "gray"} label={strategy.market_type} size="sm" />
          <Badge variant="gray" label={`${strategy.trade_frequency} freq`} size="sm" />
          {(strategy.suitable_timeframes ?? []).slice(0, 3).map((tf) => (
            <Badge key={tf} variant="gray" label={tf} size="sm" />
          ))}
        </div>
        {strategy.description && (
          <p className={styles.stratDesc}>{strategy.description}</p>
        )}
      </div>
      <button className={styles.stratChangeBtn} onClick={onBrowse}>Change ⚡</button>
    </div>
  );
}

// ── ConfigCard ────────────────────────────────────────────────────────────────
// Shows a saved StrategyConfig with execution + filter + risk summary.

function ConfigCard({
  config,
  selected,
  onSelect,
}: {
  config: StrategyConfigData;
  selected: boolean;
  onSelect: () => void;
}) {
  const rp = config.risk_profile ?? {};
  const hasPairs = config.pairs?.length ? config.pairs.length > 0 : false;

  return (
    <div
      className={`${styles.cfgCard} ${selected ? styles.cfgCardSelected : ""}`}
      onClick={onSelect}
    >
      <div className={styles.cfgHeader}>
        <span className={styles.cfgName}>{config.name}</span>
        {selected && <span className={styles.cfgCheck}>✓</span>}
      </div>

      <div className={styles.cfgBody}>
        {/* Execution */}
        <div className={styles.cfgRow}>
          <span className={styles.cfgRowLabel}>Execution</span>
          <span className={styles.cfgRowValue}>
            {config.execution_strategy}
            <Badge variant="blue" label={config.execution_timeframe} size="sm" />
          </span>
        </div>

        {/* HTF filter */}
        {config.trend_filter_strategy && (
          <div className={styles.cfgRow}>
            <span className={styles.cfgRowLabel}>HTF filter</span>
            <span className={styles.cfgRowValue}>
              {config.trend_filter_strategy}
              <Badge variant="purple" label={config.trend_filter_timeframe ?? ""} size="sm" />
            </span>
          </div>
        )}

        {/* Risk chips */}
        <div className={styles.cfgChips}>
          {rp.stop_loss_pct      != null && <span className={styles.cfgChip}>SL {rp.stop_loss_pct}%</span>}
          {rp.take_profit_pct    != null && <span className={styles.cfgChip}>TP {rp.take_profit_pct}%</span>}
          {rp.leverage           != null && <span className={styles.cfgChip}>{rp.leverage}×</span>}
          {rp.position_size_pct  != null && <span className={styles.cfgChip}>Pos {rp.position_size_pct}%</span>}
        </div>

        {/* Pairs */}
        {hasPairs && (
          <div className={styles.cfgRow}>
            <span className={styles.cfgRowLabel}>Pairs</span>
            <span className={styles.cfgRowValue}>{config.pairs!.join(", ")}</span>
          </div>
        )}

        {config.notes && (
          <p className={styles.cfgNotes}>{config.notes}</p>
        )}
      </div>
    </div>
  );
}
