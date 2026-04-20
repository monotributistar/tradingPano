import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchBacktests, fetchBacktest, createBacktest, deleteBacktest,
  fetchStrategies, fetchStrategyConfigs,
  fetchOHLCV, fetchTrades, fetchMarketScanner,
  type BacktestJob, type MarketSnapshot, type StrategyConfigData,
} from "../api/client";
import MetricsCard from "../components/MetricsCard";
import EquityCurve from "../components/EquityCurve";
import TradeTable from "../components/TradeTable";
import PriceChart from "../components/PriceChart";
import ValidationPanel from "../components/ValidationPanel";
import { Badge, Modal, DataTable, Spinner, Alert, TabBar } from "../components/ui";
import type { ColumnDef } from "../components/ui";
import StrategyPicker from "../components/strategy-engine/StrategyPicker";
import type { Strategy, Timeframe } from "../api/client";
import styles from "./Backtests.module.css";

// ── Constants ──────────────────────────────────────────────────────────────────

const PERIODS = [
  { value: "1w",  label: "1 week" },
  { value: "2w",  label: "2 weeks" },
  { value: "1m",  label: "1 month" },
  { value: "2m",  label: "2 months" },
  { value: "3m",  label: "3 months" },
  { value: "6m",  label: "6 months" },
  { value: "9m",  label: "9 months" },
  { value: "1y",  label: "1 year" },
  { value: "18m", label: "18 months" },
  { value: "2y",  label: "2 years" },
  { value: "3y",  label: "3 years" },
  { value: "4y",  label: "4 years" },
  { value: "5y",  label: "5 years" },
];

const TIMEFRAMES = [
  { value: "15m", label: "15 min" },
  { value: "30m", label: "30 min" },
  { value: "1h",  label: "1 hour" },
  { value: "2h",  label: "2 hours" },
  { value: "4h",  label: "4 hours" },
  { value: "6h",  label: "6 hours" },
  { value: "8h",  label: "8 hours" },
  { value: "12h", label: "12 hours" },
  { value: "1d",  label: "1 day" },
  { value: "1w",  label: "1 week" },
];

const DEFAULT_PAIRS = [
  "BTC/USDT", "ETH/USDT", "BNB/USDT",
  "SOL/USDT", "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT",
  "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
  "DOGE/USDT", "SHIB/USDT", "PEPE/USDT",
  "LTC/USDT", "BCH/USDT", "ATOM/USDT", "FIL/USDT", "INJ/USDT", "TIA/USDT",
];

/** Market scanner columns for the pair picker modal */
const PAIR_COLUMNS: ColumnDef<MarketSnapshot>[] = [
  {
    key: "pair",
    header: "Pair",
    sortable: true,
    render: (r) => <strong style={{ fontSize: 12 }}>{r.pair}</strong>,
  },
  {
    key: "price",
    header: "Price",
    sortable: true,
    render: (r) => (
      <span style={{ fontSize: 12 }}>
        ${r.price < 1 ? r.price.toFixed(4) : r.price.toLocaleString()}
      </span>
    ),
  },
  {
    key: "change_24h_pct",
    header: "24h %",
    sortable: true,
    render: (r) => (
      <span style={{ color: r.change_24h_pct >= 0 ? "var(--green)" : "var(--red)", fontSize: 12 }}>
        {r.change_24h_pct >= 0 ? "+" : ""}{r.change_24h_pct.toFixed(2)}%
      </span>
    ),
  },
  {
    key: "atr_pct",
    header: "ATR%",
    sortable: true,
    render: (r) => <span style={{ fontSize: 12 }}>{r.atr_pct.toFixed(2)}%</span>,
  },
  {
    key: "adx",
    header: "ADX",
    sortable: true,
    render: (r) => (
      <span style={{ fontSize: 12, color: r.adx > 25 ? "var(--green)" : "var(--muted)" }}>
        {r.adx.toFixed(0)}
      </span>
    ),
  },
  {
    key: "rsi",
    header: "RSI",
    sortable: true,
    render: (r) => (
      <span style={{ fontSize: 12, color: r.rsi > 70 ? "var(--red)" : r.rsi < 30 ? "var(--green)" : "var(--text)" }}>
        {r.rsi.toFixed(0)}
      </span>
    ),
  },
  {
    key: "market_type",
    header: "Regime",
    render: (r) => (
      <Badge
        variant={r.market_type === "trending" ? "blue" : r.market_type === "ranging" ? "yellow" : "gray"}
        label={r.market_type}
      />
    ),
  },
  {
    key: "trend_direction",
    header: "Direction",
    render: (r) => (
      <Badge
        variant={r.trend_direction === "up" ? "green" : r.trend_direction === "down" ? "red" : "gray"}
        label={r.trend_direction === "up" ? "▲ Up" : r.trend_direction === "down" ? "▼ Down" : "→ Side"}
      />
    ),
  },
  {
    key: "volatility",
    header: "Volatility",
    render: (r) => (
      <Badge
        variant={r.volatility === "high" ? "red" : r.volatility === "medium" ? "yellow" : "green"}
        label={r.volatility}
      />
    ),
  },
];

// ── Main component ─────────────────────────────────────────────────────────────

export default function Backtests() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Strategy source toggle
  const [configSource,     setConfigSource]     = useState<"quick" | "saved">("quick");
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null);
  const [stratPickerOpen,  setStratPickerOpen]  = useState(false);
  const [pairPickerOpen,   setPairPickerOpen]   = useState(false);

  const [form, setForm] = useState({
    strategy:  "mean_reversion",
    pair:      "BTC/USDT",
    period:    "6m",
    timeframe: "1h",
  });

  // ── Queries ────────────────────────────────────────────────────────────────
  const { data: strategies }   = useQuery({ queryKey: ["strategies"],      queryFn: fetchStrategies });
  const { data: savedConfigs } = useQuery({ queryKey: ["strategyConfigs"], queryFn: fetchStrategyConfigs });

  const { data: marketData, isLoading: marketLoading } = useQuery({
    queryKey: ["market-scanner-backtest", form.timeframe],
    queryFn:  () => fetchMarketScanner({ pairs: DEFAULT_PAIRS.join(","), timeframe: form.timeframe }),
    enabled:  pairPickerOpen,
    staleTime: 5 * 60 * 1000,
  });

  const { data: jobs, isLoading } = useQuery({
    queryKey:        ["backtests"],
    queryFn:         () => fetchBacktests(),
    refetchInterval: 3000,
  });

  const { data: selected } = useQuery({
    queryKey: ["backtest", selectedId],
    queryFn:  () => fetchBacktest(selectedId!),
    enabled:  selectedId !== null,
    refetchInterval: (query) => {
      const d = query.state.data;
      return d?.status === "done" || d?.status === "error" ? false : 2000;
    },
  });

  const { data: selectedTrades } = useQuery({
    queryKey: ["trades", "backtest", selectedId],
    queryFn:  () => fetchTrades({ backtest_job_id: selectedId!, limit: 500 }),
    enabled:  selected?.status === "done",
  });

  const { data: ohlcv } = useQuery({
    queryKey: ["ohlcv", selected?.pair, selected?.timeframe, selected?.period],
    queryFn:  () => fetchOHLCV(selected!.pair, { timeframe: selected!.timeframe, period: selected!.period }),
    enabled:  selected?.status === "done" && !!selected?.pair,
    staleTime: 5 * 60 * 1000,
  });

  // ── Mutations ──────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: createBacktest,
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ["backtests"] });
      setSelectedId(job.id);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBacktest,
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ["backtests"] }); setSelectedId(null); },
  });

  // ── Helpers ────────────────────────────────────────────────────────────────
  function selectConfig(cfg: StrategyConfigData) {
    setSelectedConfigId(cfg.id);
    // Auto-apply strategy + timeframe from the config
    const tfs = cfg.execution_timeframe;
    // If config has exactly one pair, pre-select it
    const autoPair = cfg.pairs?.length === 1 ? cfg.pairs[0] : form.pair;
    setForm((f) => ({
      ...f,
      strategy:  cfg.execution_strategy,
      timeframe: tfs ?? f.timeframe,
      pair:      autoPair,
    }));
  }

  const selectedConfig = savedConfigs?.find((c) => c.id === selectedConfigId);

  function statusColor(s: BacktestJob["status"]) {
    return { pending: "var(--muted)", running: "var(--yellow)", done: "var(--green)", error: "var(--red)" }[s];
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className={styles.page}>
      <div className={styles.sidebar}>

        {/* ── Submit form ── */}
        <div className={styles.form}>
          <h3 className={styles.formTitle}>New Backtest</h3>

          {/* Strategy source tabs */}
          <label className={styles.label}>Strategy</label>
          <TabBar
            variant="pills"
            size="sm"
            tabs={[
              { value: "quick", label: "⚡ Quick" },
              { value: "saved", label: "📦 Saved Config", badge: savedConfigs?.length },
            ]}
            active={configSource}
            onChange={(v) => {
              setConfigSource(v as "quick" | "saved");
              setSelectedConfigId(null);
            }}
          />

          {/* Quick start: StrategyPreview card */}
          {configSource === "quick" && (
            <StrategyPreview
              strategy={(strategies ?? []).find((s) => s.name === form.strategy)}
              onBrowse={() => setStratPickerOpen(true)}
            />
          )}

          {/* Saved config: scrollable card list */}
          {configSource === "saved" && (
            <>
              {!savedConfigs?.length ? (
                <div className={styles.emptyConfigs}>
                  No saved configs yet — build one in the <strong>⚡ Strategy</strong> tab.
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

              {/* Show what was applied */}
              {selectedConfig && (
                <div className={styles.appliedBanner}>
                  <span className={styles.appliedIcon}>✓</span>
                  <span>
                    <strong>{selectedConfig.execution_strategy}</strong> ·{" "}
                    <Badge variant="blue" label={selectedConfig.execution_timeframe} size="sm" />
                    {selectedConfig.trend_filter_strategy && (
                      <> · HTF: <strong>{selectedConfig.trend_filter_strategy}</strong></>
                    )}
                  </span>
                </div>
              )}
            </>
          )}

          {/* Pair */}
          <label className={styles.label}>Pair</label>
          <div className={styles.pairRow}>
            <select
              className={styles.select}
              value={form.pair}
              onChange={(e) => setForm({ ...form, pair: e.target.value })}
              style={{ flex: 1 }}
            >
              {DEFAULT_PAIRS.map((p) => <option key={p}>{p}</option>)}
            </select>
            <button
              className={styles.browseBtn}
              onClick={() => setPairPickerOpen(true)}
              title="Browse pairs with live market data"
            >
              📡
            </button>
          </div>

          {/* Config pair hints */}
          {selectedConfig?.pairs && selectedConfig.pairs.length > 1 && (
            <div className={styles.pairHints}>
              <span className={styles.pairHintsLabel}>Config pairs:</span>
              {selectedConfig.pairs.map((p) => (
                <button
                  key={p}
                  className={`${styles.pairHintBtn} ${form.pair === p ? styles.pairHintActive : ""}`}
                  onClick={() => setForm((f) => ({ ...f, pair: p }))}
                >
                  {p.replace("/USDT", "")}
                </button>
              ))}
            </div>
          )}

          {/* Timeframe */}
          <label className={styles.label}>
            Timeframe
            {configSource === "saved" && selectedConfig && (
              <span className={styles.labelHint}> · locked to config</span>
            )}
          </label>
          <select
            className={styles.select}
            value={form.timeframe}
            onChange={(e) => setForm({ ...form, timeframe: e.target.value })}
            disabled={configSource === "saved" && !!selectedConfig}
          >
            {TIMEFRAMES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>

          {/* Period */}
          <label className={styles.label}>Period</label>
          <select
            className={styles.select}
            value={form.period}
            onChange={(e) => setForm({ ...form, period: e.target.value })}
          >
            {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>

          {configSource === "saved" && !selectedConfigId && (
            <Alert variant="warning" compact>Select a saved configuration above.</Alert>
          )}

          <button
            className={styles.submitBtn}
            onClick={() => createMutation.mutate(form)}
            disabled={createMutation.isPending || (configSource === "saved" && !selectedConfigId)}
          >
            {createMutation.isPending ? "Submitting…" : "▶ Run Backtest"}
          </button>

          {createMutation.isError && (
            <Alert variant="error" compact>
              {String((createMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? createMutation.error)}
            </Alert>
          )}
        </div>

        {/* ── Job list ── */}
        <div className={styles.jobList}>
          {isLoading && <div className={styles.muted}>Loading…</div>}
          {(jobs ?? []).map((job) => {
            const m   = job.metrics;
            const ret = m?.total_return_pct;
            return (
              <div
                key={job.id}
                className={`${styles.jobItem} ${selectedId === job.id ? styles.jobSelected : ""}`}
                onClick={() => setSelectedId(job.id)}
              >
                <div className={styles.jobHeader}>
                  <span className={styles.jobName}>{job.strategy}</span>
                  <button
                    className={styles.jobDeleteBtn}
                    title="Delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteMutation.mutate(job.id);
                      if (selectedId === job.id) setSelectedId(null);
                    }}
                  >×</button>
                </div>

                <div className={styles.jobMeta}>
                  {job.pair} · {job.period}
                  {job.timeframe && <><span style={{ color: "var(--border)", margin: "0 4px" }}>|</span>{job.timeframe}</>}
                </div>

                <div className={styles.jobStatus} style={{ color: statusColor(job.status) }}>
                  ● {job.status.toUpperCase()}
                  {job.created_at && (
                    <span className={styles.jobDate}>
                      {" · "}{new Date(job.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                    </span>
                  )}
                </div>

                {job.status === "done" && m && (
                  <div className={styles.jobMetrics}>
                    <div className={styles.jobMetricBig} style={{ color: ret != null ? (ret >= 0 ? "var(--green)" : "var(--red)") : "var(--muted)" }}>
                      {ret != null ? `${ret >= 0 ? "+" : ""}${ret.toFixed(1)}%` : "—"}
                    </div>
                    <div className={styles.jobMetricRow}>
                      <MetricCell label="Sharpe" value={m.sharpe_ratio?.toFixed(2)} color={m.sharpe_ratio != null ? (m.sharpe_ratio >= 1 ? "var(--green)" : m.sharpe_ratio >= 0 ? "var(--text)" : "var(--red)") : undefined} />
                      <MetricCell label="DD"      value={m.max_drawdown_pct != null ? `-${m.max_drawdown_pct.toFixed(1)}%` : undefined} color="var(--red)" />
                      <MetricCell label="Win"     value={m.win_rate_pct != null ? `${m.win_rate_pct.toFixed(0)}%` : undefined}    color={m.win_rate_pct != null ? (m.win_rate_pct >= 50 ? "var(--green)" : "var(--red)") : undefined} />
                    </div>
                    <div className={styles.jobMetricRow}>
                      <MetricCell label="PF"      value={m.profit_factor?.toFixed(2)}   color={m.profit_factor != null ? (m.profit_factor >= 1 ? "var(--green)" : "var(--red)") : undefined} />
                      <MetricCell label="Trades"  value={String(m.total_trades ?? "—")} />
                      <MetricCell label="Expect." value={m.expectancy_usd != null ? `$${m.expectancy_usd.toFixed(3)}` : undefined} color={m.expectancy_usd != null ? (m.expectancy_usd >= 0 ? "var(--green)" : "var(--red)") : undefined} />
                    </div>
                  </div>
                )}

                {job.status === "error" && job.error_msg && (
                  <div className={styles.jobError}>
                    {job.error_msg.substring(0, 60)}{job.error_msg.length > 60 ? "…" : ""}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Strategy picker modal (quick mode) ── */}
      <Modal
        open={stratPickerOpen}
        onClose={() => setStratPickerOpen(false)}
        title="⚡ Pick a Strategy"
        width="860px"
      >
        <StrategyPicker
          strategies={strategies ?? []}
          value={form.strategy}
          filterTimeframe={form.timeframe as Timeframe}
          role="execution"
          onChange={(name) => {
            const strat = (strategies ?? []).find((s) => s.name === name);
            const tfs = strat?.suitable_timeframes ?? [];
            const currentOk = tfs.length === 0 || tfs.includes(form.timeframe);
            setForm((f) => ({
              ...f,
              strategy:  name,
              timeframe: currentOk ? f.timeframe : (tfs[0] ?? f.timeframe),
            }));
            setStratPickerOpen(false);
          }}
        />
      </Modal>

      {/* ── Pair picker modal ── */}
      <Modal
        open={pairPickerOpen}
        onClose={() => setPairPickerOpen(false)}
        title={`📡 Market Data — ${form.timeframe} · Click a row to select`}
        width="900px"
      >
        {marketLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
            <Spinner size="lg" />
            <span style={{ marginLeft: 12, color: "var(--muted)", fontSize: 13 }}>Loading market data…</span>
          </div>
        ) : (
          <DataTable
            columns={PAIR_COLUMNS as unknown as ColumnDef<Record<string, unknown>>[]}
            data={(marketData ?? []) as unknown as Record<string, unknown>[]}
            emptyLabel="No market data available. Try scanning from the Market tab first."
            onRowClick={(row) => {
              setForm((f) => ({ ...f, pair: (row as unknown as MarketSnapshot).pair }));
              setPairPickerOpen(false);
            }}
            pageSize={15}
          />
        )}
      </Modal>

      {/* ── Detail panel ── */}
      <div className={styles.detail}>
        {!selected && (
          <div className={styles.placeholder}>Select or submit a backtest to see results.</div>
        )}
        {selected && (
          <>
            <div className={styles.detailHeader}>
              <div>
                <h2 className={styles.detailTitle}>
                  {selected.strategy} · {selected.pair} · {selected.period}
                </h2>
                <div className={styles.muted}>
                  Created {selected.created_at.substring(0, 16).replace("T", " ")}
                  {selected.finished_at && ` · Finished ${selected.finished_at.substring(0, 16).replace("T", " ")}`}
                </div>
              </div>
              <button className={styles.deleteBtn} onClick={() => deleteMutation.mutate(selected.id)}>
                Delete
              </button>
            </div>

            {selected.status === "pending" && (
              <div className={styles.status}>⏳ Waiting to start…</div>
            )}
            {selected.status === "running" && (
              <div className={styles.status} style={{ color: "var(--yellow)" }}>⚙️ Running backtest…</div>
            )}
            {selected.status === "error" && (
              <Alert variant="error">❌ {selected.error_msg}</Alert>
            )}

            {selected.status === "done" && selected.metrics && (
              <>
                <MetricsCard metrics={selected.metrics} />
                <ValidationPanel jobId={selected.id} />

                <div className={styles.chartCard}>
                  <div className={styles.chartTitle}>
                    Price Chart · {selected.pair}
                    <span style={{ marginLeft: 16, fontSize: 11, color: "var(--muted)" }}>
                      <span style={{ color: "#22c55e", marginRight: 8 }}>▲ Buy / Cover</span>
                      <span style={{ color: "#f59e0b", marginRight: 8 }}>▼ Short</span>
                      <span style={{ color: "#ef4444" }}>▼ Sell</span>
                    </span>
                  </div>
                  {ohlcv && ohlcv.length > 0 ? (
                    <PriceChart candles={ohlcv} trades={selectedTrades ?? []} height={320} strategy={selected.strategy} />
                  ) : (
                    <div style={{ color: "var(--muted)", padding: "24px", textAlign: "center", fontSize: 13 }}>
                      Loading price data…
                    </div>
                  )}
                </div>

                {selected.equity_curve && (
                  <div className={styles.chartCard}>
                    <div className={styles.chartTitle}>Equity Curve</div>
                    <EquityCurve
                      curve={selected.equity_curve}
                      timestamps={selected.equity_timestamps}
                      initialCapital={selected.metrics.initial_capital}
                      height={220}
                    />
                  </div>
                )}

                {selectedTrades && selectedTrades.length > 0 && (
                  <div className={styles.chartCard}>
                    <div className={styles.chartTitle}>Trades ({selectedTrades.length})</div>
                    <TradeTable trades={selectedTrades} />
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── StrategyPreview ────────────────────────────────────────────────────────────
// Compact card showing the selected strategy with market-type + timeframe badges.

function StrategyPreview({
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
      <div className={styles.stratPreviewInfo}>
        <span className={styles.stratPreviewName}>{strategy.name}</span>
        <div className={styles.stratPreviewBadges}>
          <Badge variant={marketColor as "blue" | "yellow" | "gray"} label={strategy.market_type} />
          {(strategy.suitable_timeframes ?? []).slice(0, 3).map((tf) => (
            <Badge key={tf} variant="gray" label={tf} size="sm" />
          ))}
        </div>
        {strategy.description && (
          <p className={styles.stratPreviewDesc}>{strategy.description}</p>
        )}
      </div>
      <button className={styles.stratChangeBtn} onClick={onBrowse} title="Browse strategies">
        Change ⚡
      </button>
    </div>
  );
}

// ── ConfigCard ─────────────────────────────────────────────────────────────────
// Compact saved-config card with execution + filter + risk chips.

function ConfigCard({
  config,
  selected,
  onSelect,
}: {
  config:   StrategyConfigData;
  selected: boolean;
  onSelect: () => void;
}) {
  const rp = config.risk_profile ?? {};

  return (
    <div
      className={`${styles.cfgCard} ${selected ? styles.cfgCardSelected : ""}`}
      onClick={onSelect}
    >
      <div className={styles.cfgHeader}>
        <span className={styles.cfgName}>{config.name}</span>
        <div className={styles.cfgHeaderRight}>
          <Badge variant="blue"   label={config.execution_timeframe} size="sm" />
          {selected && <span className={styles.cfgCheck}>✓</span>}
        </div>
      </div>

      <div className={styles.cfgMeta}>
        <span className={styles.cfgStrategy}>{config.execution_strategy}</span>
        {config.trend_filter_strategy && (
          <span className={styles.cfgFilter}>
            + HTF: {config.trend_filter_strategy}
            <Badge variant="purple" label={config.trend_filter_timeframe ?? ""} size="sm" />
          </span>
        )}
      </div>

      {/* Risk chips */}
      {(rp.stop_loss_pct != null || rp.take_profit_pct != null || rp.leverage != null || rp.position_size_pct != null) && (
        <div className={styles.cfgChips}>
          {rp.stop_loss_pct     != null && <span className={styles.cfgChip}>SL {rp.stop_loss_pct}%</span>}
          {rp.take_profit_pct   != null && <span className={styles.cfgChip}>TP {rp.take_profit_pct}%</span>}
          {rp.leverage          != null && <span className={styles.cfgChip}>{rp.leverage}×</span>}
          {rp.position_size_pct != null && <span className={styles.cfgChip}>Pos {rp.position_size_pct}%</span>}
        </div>
      )}

      {/* Pairs hint */}
      {config.pairs && config.pairs.length > 0 && (
        <div className={styles.cfgPairs}>
          {config.pairs.slice(0, 5).map((p) => (
            <span key={p} className={styles.cfgPairChip}>{p.replace("/USDT", "")}</span>
          ))}
          {config.pairs.length > 5 && (
            <span className={styles.cfgPairChip}>+{config.pairs.length - 5}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── MetricCell ─────────────────────────────────────────────────────────────────
// Tiny metric label+value in the job list card.

function MetricCell({ label, value, color }: { label: string; value?: string; color?: string }) {
  return (
    <span className={styles.jobMetricItem}>
      <span className={styles.jobMetricLabel}>{label}</span>
      <span style={color ? { color } : undefined}>{value ?? "—"}</span>
    </span>
  );
}
