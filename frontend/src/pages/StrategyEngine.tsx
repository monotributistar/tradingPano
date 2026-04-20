import { useEffect, useState, useCallback } from "react";
import {
  fetchStrategies,
  fetchStrategyConfigs,
  createStrategyConfig,
  updateStrategyConfig,
  deleteStrategyConfig,
  activateStrategyConfig,
  fetchSettings,
} from "../api/client";
import type { Strategy, StrategyConfigData, Timeframe } from "../api/client";
import { Badge, Button, Card, DataTable, Select, Spinner, Tooltip } from "../components/ui";
import type { ColumnDef } from "../components/ui";
import StrategyPicker from "../components/strategy-engine/StrategyPicker";
import TrendFilterPicker from "../components/strategy-engine/TrendFilterPicker";
import RiskProfileForm from "../components/strategy-engine/RiskProfileForm";
import type { RiskOverride } from "../components/strategy-engine/RiskProfileForm";
import ComposedStrategyPreview from "../components/strategy-engine/ComposedStrategyPreview";
import styles from "./StrategyEngine.module.css";

const TF_OPTIONS: { value: Timeframe; label: string }[] = [
  { value: "15m", label: "15m" },
  { value: "30m", label: "30m" },
  { value: "1h",  label: "1h"  },
  { value: "2h",  label: "2h"  },
  { value: "4h",  label: "4h"  },
  { value: "6h",  label: "6h"  },
  { value: "8h",  label: "8h"  },
  { value: "12h", label: "12h" },
  { value: "1d",  label: "1d"  },
  { value: "1w",  label: "1w"  },
];

type Tab = "compose" | "configs";

function configColumns(
  strategies: Strategy[],
  onEdit: (c: StrategyConfigData) => void,
  onActivate: (c: StrategyConfigData) => void,
  onDelete: (c: StrategyConfigData) => void,
): ColumnDef<StrategyConfigData>[] {
  return [
    {
      key: "name",
      header: "Name",
      sortable: true,
      render: (r) => <strong>{r.name}</strong>,
    },
    {
      key: "execution_strategy",
      header: "Execution",
      sortable: true,
      render: (r) => (
        <span>
          <Badge variant="blue" label={r.execution_timeframe} />{" "}
          {r.execution_strategy}
        </span>
      ),
    },
    {
      key: "trend_filter_strategy",
      header: "HTF Filter",
      render: (r) =>
        r.trend_filter_strategy ? (
          <span>
            <Badge variant="purple" label={r.trend_filter_timeframe ?? "?"} />{" "}
            {r.trend_filter_strategy}
          </span>
        ) : (
          <span style={{ color: "var(--muted)", fontSize: 11 }}>None</span>
        ),
    },
    {
      key: "created_at",
      header: "Created",
      sortable: true,
      render: (r) => new Date(r.created_at).toLocaleDateString(),
    },
    {
      key: "_actions",
      header: "",
      render: (r) => (
        <div style={{ display: "flex", gap: 6 }}>
          <Button variant="ghost" size="sm" onClick={() => onEdit(r)}>Edit</Button>
          <Button variant="secondary" size="sm" onClick={() => onActivate(r)}>▶ Activate</Button>
          <Button variant="danger" size="sm" onClick={() => onDelete(r)}>✕</Button>
        </div>
      ),
    },
  ];
}

export default function StrategyEngine() {
  const [tab, setTab] = useState<Tab>("configs");

  // Data
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [configs, setConfigs] = useState<StrategyConfigData[]>([]);
  const [globalSettings, setGlobalSettings] = useState<{ leverage: number; max_drawdown_pct: number; daily_loss_stop_pct: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Compose form state
  const [execStrategy, setExecStrategy] = useState<string>("");
  const [execTF, setExecTF] = useState<Timeframe>("1h");
  const [filterStrategy, setFilterStrategy] = useState<string | undefined>();
  const [filterTF, setFilterTF] = useState<Timeframe>("4h");
  const [risk, setRisk] = useState<RiskOverride>({});
  const [editingConfig, setEditingConfig] = useState<StrategyConfigData | undefined>();

  // Action states
  const [saving, setSaving] = useState(false);
  const [activating, setActivating] = useState<number | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [toast, setToast] = useState("");

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [strats, cfgs, settings] = await Promise.all([
        fetchStrategies(),
        fetchStrategyConfigs(),
        fetchSettings(),
      ]);
      setStrategies(strats);
      setConfigs(cfgs);
      setGlobalSettings({
        leverage: settings.leverage,
        max_drawdown_pct: settings.max_drawdown_pct,
        daily_loss_stop_pct: settings.daily_loss_stop_pct,
      });
    } catch (e) {
      setError("Failed to load data. Check API connection.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Pre-fill risk from selected execution strategy
  useEffect(() => {
    const s = strategies.find((s) => s.name === execStrategy);
    if (!s) return;
    setRisk({
      stop_loss_pct: s.risk_profile.stop_loss_pct,
      take_profit_pct: s.risk_profile.take_profit_pct,
      position_size_pct: s.risk_profile.position_size_pct,
      leverage: s.recommended_leverage,
      max_drawdown_pct: globalSettings?.max_drawdown_pct,
      daily_loss_stop_pct: globalSettings?.daily_loss_stop_pct,
    });
  }, [execStrategy, strategies, globalSettings]);

  function startEditingConfig(cfg: StrategyConfigData) {
    setEditingConfig(cfg);
    setExecStrategy(cfg.execution_strategy);
    setExecTF(cfg.execution_timeframe);
    setFilterStrategy(cfg.trend_filter_strategy ?? undefined);
    setFilterTF((cfg.trend_filter_timeframe as Timeframe) ?? "4h");
    setRisk(cfg.risk_profile ?? {});
    setTab("compose");
  }

  function resetCompose() {
    setEditingConfig(undefined);
    setExecStrategy("");
    setExecTF("1h");
    setFilterStrategy(undefined);
    setFilterTF("4h");
    setRisk({});
  }

  async function handleSave(name: string, notes: string) {
    setSaving(true);
    try {
      const body = {
        name,
        notes,
        execution_strategy: execStrategy,
        execution_timeframe: execTF,
        trend_filter_strategy: filterStrategy ?? null,
        trend_filter_timeframe: filterStrategy ? filterTF : null,
        risk_profile: risk,
        pairs: [],
      };
      if (editingConfig) {
        await updateStrategyConfig(editingConfig.id, body);
        showToast("Config updated ✓");
      } else {
        await createStrategyConfig(body);
        showToast("Config saved ✓");
      }
      resetCompose();
      setTab("configs");
      await load();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Save failed";
      showToast(`Error: ${msg}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleActivate(id: number) {
    setActivating(id);
    try {
      await activateStrategyConfig(id);
      showToast("Strategy activated ✓");
      await load();
    } catch {
      showToast("Activation failed");
    } finally {
      setActivating(null);
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteStrategyConfig(id);
      showToast("Config deleted");
      await load();
    } catch {
      showToast("Delete failed");
    } finally {
      setDeleteConfirm(null);
    }
  }

  const execStrategyObj = strategies.find((s) => s.name === execStrategy);
  const filterStrategyObj = strategies.find((s) => s.name === filterStrategy);

  const columns = configColumns(
    strategies,
    startEditingConfig,
    (c) => handleActivate(c.id),
    (c) => setDeleteConfirm(c.id),
  );

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>⚡ Strategy Engine</h2>
          <p className={styles.subtitle}>
            Compose multi-timeframe strategies with tailored risk profiles.
          </p>
        </div>
        <div className={styles.headerActions}>
          <Button variant="primary" size="sm" onClick={() => { resetCompose(); setTab("compose"); }}>
            + New config
          </Button>
          <Button variant="ghost" size="sm" onClick={load}>↺ Refresh</Button>
        </div>
      </div>

      {/* Toast */}
      {toast && <div className={styles.toast}>{toast}</div>}

      {/* Tabs */}
      <div className={styles.tabs}>
        <button className={[styles.tab, tab === "configs" ? styles.tabActive : ""].join(" ")} onClick={() => setTab("configs")}>
          Saved Configs {configs.length > 0 && <Badge variant="gray" label={String(configs.length)} />}
        </button>
        <button className={[styles.tab, tab === "compose" ? styles.tabActive : ""].join(" ")} onClick={() => setTab("compose")}>
          {editingConfig ? `Edit: ${editingConfig.name}` : "Compose"}
        </button>
      </div>

      {loading ? (
        <div className={styles.center}><Spinner size="lg" /></div>
      ) : error ? (
        <div className={styles.errorBox}>{error}</div>
      ) : tab === "configs" ? (
        /* ── Saved configs table ── */
        <div className={styles.tableSection}>
          <DataTable
            columns={columns as unknown as ColumnDef<Record<string, unknown>>[]}
            data={configs as unknown as Record<string, unknown>[]}
            emptyLabel="No strategy configs yet. Click 'New config' to compose one."
            pageSize={10}
          />
        </div>
      ) : (
        /* ── Compose view ── */
        <div className={styles.compose}>
          {/* Step 1: Execution */}
          <Card padding="md">
            <div className={styles.stepHeader}>
              <span className={styles.stepNum}>1</span>
              <span className={styles.stepTitle}>Execution Strategy</span>
              <div className={styles.tfSelect}>
                <span className={styles.tfLabel}>Timeframe:</span>
                <Select
                  options={TF_OPTIONS}
                  value={execTF}
                  onChange={(v) => setExecTF(v as Timeframe)}
                />
              </div>
            </div>
            <StrategyPicker
              strategies={strategies}
              value={execStrategy}
              onChange={setExecStrategy}
              filterTimeframe={execTF}
              role="execution"
            />
          </Card>

          {/* Step 2: Trend filter */}
          <Card padding="md">
            <div className={styles.stepHeader}>
              <span className={styles.stepNum}>2</span>
              <span className={styles.stepTitle}>HTF Trend Filter</span>
              <Tooltip content="Optional. Pick a strategy running on a higher timeframe to confirm trend direction before entry.">
                <span className={styles.infoIcon}>ℹ</span>
              </Tooltip>
            </div>
            <TrendFilterPicker
              strategies={strategies}
              executionTimeframe={execTF}
              value={filterStrategy}
              tfValue={filterTF}
              onStrategyChange={setFilterStrategy}
              onTfChange={setFilterTF}
              excludeStrategy={execStrategy}
            />
          </Card>

          {/* Step 3: Risk */}
          <Card padding="md">
            <div className={styles.stepHeader}>
              <span className={styles.stepNum}>3</span>
              <span className={styles.stepTitle}>Risk Profile</span>
            </div>
            <RiskProfileForm
              strategy={execStrategyObj}
              value={risk}
              onChange={setRisk}
              globalLeverage={globalSettings?.leverage}
              globalMaxDrawdown={globalSettings?.max_drawdown_pct}
              globalDailyStop={globalSettings?.daily_loss_stop_pct}
            />
          </Card>

          {/* Step 4: Preview & Save */}
          <Card padding="md">
            <ComposedStrategyPreview
              executionStrategy={execStrategyObj}
              executionTimeframe={execTF}
              trendFilterStrategy={filterStrategyObj}
              trendFilterTimeframe={filterStrategy ? filterTF : undefined}
              risk={risk}
              pairs={[]}
              existing={editingConfig}
              onSave={handleSave}
              onActivate={editingConfig ? () => handleActivate(editingConfig.id) : undefined}
              isSaving={saving}
              isActivating={activating === editingConfig?.id}
            />
          </Card>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteConfirm !== null && (
        <div className={styles.modalOverlay}>
          <div className={styles.confirmModal}>
            <p>Delete this strategy config?</p>
            <div className={styles.confirmActions}>
              <Button variant="danger" size="sm" onClick={() => handleDelete(deleteConfirm)}>Delete</Button>
              <Button variant="ghost" size="sm" onClick={() => setDeleteConfirm(null)}>Cancel</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
