import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchProviderStatus, testConnection, updateProviderConfig,
  fetchTicker, type ConnectionResult,
} from "../api/client";
import styles from "./Provider.module.css";

const EXCHANGES = ["bybit", "binance", "okx", "kraken", "coinbase"];
const PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"];

export default function Provider() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ exchange: "", testnet: true, api_key: "", secret: "" });
  const [formReady, setFormReady] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionResult | null>(null);

  const { data: status, isLoading } = useQuery({
    queryKey: ["providerStatus"],
    queryFn: fetchProviderStatus,
  });

  // Sync form when status loads for the first time
  if (status && !formReady) {
    setForm({ exchange: status.exchange, testnet: status.testnet, api_key: "", secret: "" });
    setFormReady(true);
  }

  const testMutation = useMutation({
    mutationFn: testConnection,
    onSuccess: (r) => setTestResult(r),
  });

  const saveMutation = useMutation({
    mutationFn: updateProviderConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["providerStatus"] });
      setTestResult(null);
    },
  });

  const { data: btcTicker } = useQuery({
    queryKey: ["ticker", "BTC/USDT"],
    queryFn: () => fetchTicker("BTC/USDT"),
    refetchInterval: 15000,
  });

  const { data: ethTicker } = useQuery({
    queryKey: ["ticker", "ETH/USDT"],
    queryFn: () => fetchTicker("ETH/USDT"),
    refetchInterval: 15000,
  });

  const { data: solTicker } = useQuery({
    queryKey: ["ticker", "SOL/USDT"],
    queryFn: () => fetchTicker("SOL/USDT"),
    refetchInterval: 15000,
  });

  function handleSave() {
    const patch: Record<string, unknown> = { exchange: form.exchange, testnet: form.testnet };
    if (form.api_key) patch.api_key = form.api_key;
    if (form.secret) patch.secret = form.secret;
    saveMutation.mutate(patch);
  }

  if (isLoading) return <div className={styles.loading}>Loading...</div>;

  return (
    <div className={styles.page}>
      {/* Live prices */}
      <div className={styles.tickers}>
        {[btcTicker, ethTicker, solTicker].map((t) =>
          t ? (
            <div key={t.pair} className={styles.ticker}>
              <span className={styles.tickerPair}>{t.pair}</span>
              <span className={styles.tickerPrice}>${t.last?.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
              <span className={`${styles.tickerChange} ${(t.change_pct ?? 0) >= 0 ? styles.pos : styles.neg}`}>
                {(t.change_pct ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(t.change_pct ?? 0).toFixed(2)}%
              </span>
            </div>
          ) : null
        )}
      </div>

      <div className={styles.grid}>
        {/* Current status */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Current Connection</h3>
          <div className={styles.statusRows}>
            <Row label="Exchange" value={<strong>{status?.exchange}</strong>} />
            <Row label="Mode" value={
              <span className={status?.testnet ? styles.badgeYellow : styles.badgeRed}>
                {status?.testnet ? "TESTNET" : "⚠ MAINNET (REAL FUNDS)"}
              </span>
            } />
            <Row label="API Key" value={
              <span className={status?.has_api_key ? styles.pos : styles.muted}>
                {status?.has_api_key ? "✓ Configured" : "✗ Not set"}
              </span>
            } />
            <Row label="Secret" value={
              <span className={status?.has_secret ? styles.pos : styles.muted}>
                {status?.has_secret ? "✓ Configured" : "✗ Not set"}
              </span>
            } />
            <Row label="Active Strategy" value={status?.active_strategy ?? "—"} />
            <Row label="Pairs" value={(status?.pairs ?? []).join(", ")} />
          </div>

          <button
            className={styles.testBtn}
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending}
            data-testid="test-connection-btn"
          >
            {testMutation.isPending ? "Testing..." : "🔌 Test Connection"}
          </button>

          {testResult && <ConnectionResultPanel result={testResult} />}
        </div>

        {/* Edit config */}
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Update Configuration</h3>

          <label className={styles.label}>Exchange</label>
          <select
            className={styles.select}
            value={form.exchange}
            onChange={(e) => setForm({ ...form, exchange: e.target.value })}
            data-testid="exchange-select"
          >
            {EXCHANGES.map((ex) => <option key={ex}>{ex}</option>)}
          </select>

          <label className={styles.label}>Network</label>
          <div className={styles.toggleRow}>
            <button
              className={`${styles.toggleBtn} ${form.testnet ? styles.toggleActive : ""}`}
              onClick={() => setForm({ ...form, testnet: true })}
              data-testid="testnet-btn"
            >
              Testnet (safe)
            </button>
            <button
              className={`${styles.toggleBtn} ${!form.testnet ? styles.toggleActiveDanger : ""}`}
              onClick={() => setForm({ ...form, testnet: false })}
              data-testid="mainnet-btn"
            >
              Mainnet (real $$)
            </button>
          </div>
          {!form.testnet && (
            <div className={styles.danger}>⚠ Mainnet uses real funds. Only enable if you know what you're doing.</div>
          )}

          <label className={styles.label}>API Key</label>
          <input
            className={styles.input}
            type="password"
            placeholder="Leave blank to keep existing"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            autoComplete="off"
            data-testid="api-key-input"
          />

          <label className={styles.label}>Secret</label>
          <input
            className={styles.input}
            type="password"
            placeholder="Leave blank to keep existing"
            value={form.secret}
            onChange={(e) => setForm({ ...form, secret: e.target.value })}
            autoComplete="off"
            data-testid="secret-input"
          />

          <button
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={saveMutation.isPending}
            data-testid="save-config-btn"
          >
            {saveMutation.isPending ? "Saving..." : "💾 Save Configuration"}
          </button>

          {saveMutation.isSuccess && (
            <div className={styles.success}>✓ Configuration saved to config.yaml</div>
          )}
          {saveMutation.isError && (
            <div className={styles.error}>
              ✗ {String((saveMutation.error as any)?.response?.data?.detail ?? saveMutation.error)}
            </div>
          )}
        </div>
      </div>

      {/* Supported exchanges info */}
      <div className={styles.infoCard}>
        <h3 className={styles.cardTitle}>Supported Exchanges & Testnet Setup</h3>
        <div className={styles.infoGrid}>
          <InfoRow exchange="Bybit" testnet="✓ Automatic (sandbox mode)" docs="testnet.bybit.com" />
          <InfoRow exchange="Binance" testnet="✓ Automatic (testnet.binance.vision)" docs="testnet.binance.vision" />
          <InfoRow exchange="OKX" testnet="Manual — set demo trading flag" docs="okx.com/docs-v5/en/" />
          <InfoRow exchange="Kraken" testnet="Not available — use small amounts" docs="docs.kraken.com" />
        </div>
        <p className={styles.infoNote}>
          All strategies use <strong>spot trading only</strong> — no leverage, no futures.
          Initial capital of $10–20 USDT is sufficient.
        </p>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function ConnectionResultPanel({ result }: { result: ConnectionResult }) {
  const ok = result.public_ok;
  return (
    <div className={`${styles.resultPanel} ${ok ? styles.resultOk : styles.resultErr}`} data-testid="connection-result">
      <div className={styles.resultTitle}>
        {ok ? "✓ Connection Successful" : "✗ Connection Failed"}
      </div>
      {result.error && <div className={styles.resultError}>{result.error}</div>}
      {result.ticker && (
        <div className={styles.resultRow}>
          <span>BTC/USDT</span>
          <strong>${result.ticker.last?.toLocaleString()}</strong>
        </div>
      )}
      {result.auth_ok === true && result.balance && (
        <div className={styles.resultRow}>
          <span>Balance</span>
          <span>{Object.entries(result.balance).map(([k, v]) => `${v} ${k}`).join(", ") || "Empty"}</span>
        </div>
      )}
      {result.auth_ok === false && (
        <div className={styles.resultError}>Auth failed — check API key and secret</div>
      )}
      {result.auth_ok === null && (
        <div className={styles.resultMuted}>No API keys — only public data tested</div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>{value}</span>
    </div>
  );
}

function InfoRow({ exchange, testnet, docs }: { exchange: string; testnet: string; docs: string }) {
  return (
    <div className={styles.infoRow}>
      <strong>{exchange}</strong>
      <span>{testnet}</span>
      <span className={styles.muted}>{docs}</span>
    </div>
  );
}
