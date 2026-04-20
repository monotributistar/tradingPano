/**
 * Market Scanner page
 *
 * Shows real-time (cached) metrics for 20 major pairs:
 *  - Price, 1h / 4h / 24h / 7d change
 *  - Volume, ATR volatility, ADX trend strength, RSI
 *  - Support / Resistance range position
 *  - Top 3 strategy suggestions for current market conditions
 *
 * Data comes from GET /api/market/scanner (OHLCV-derived, no auth required).
 * Auto-refreshes every 5 minutes (cache-aligned).
 */
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchMarketScanner, fetchMarketSummary,
  type MarketSnapshot, type MarketSummary,
} from "../api/client";
import { rsiColor, adxColor, percentColor } from "../lib/colorUtils";
import { fmtPrice, fmtVolume, fmtPct } from "../lib/formatUtils";
import { TabBar, LoadingState, EmptyState, Alert, StatCard } from "../components/ui";
import styles from "./Market.module.css";

// ── Config ─────────────────────────────────────────────────────────────────────

const TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"] as const;
type TF = (typeof TIMEFRAMES)[number];

const SORT_COLS = [
  { key: "pair",           label: "Pair" },
  { key: "price",          label: "Price" },
  { key: "change_1h_pct",  label: "1h" },
  { key: "change_4h_pct",  label: "4h" },
  { key: "change_24h_pct", label: "24h" },
  { key: "change_7d_pct",  label: "7d" },
  { key: "volume_24h_usd", label: "Volume" },
  { key: "atr_pct",        label: "ATR%" },
  { key: "adx",            label: "ADX" },
  { key: "rsi",            label: "RSI" },
] as const;

type SortKey = (typeof SORT_COLS)[number]["key"];

// ── Local helpers ─────────────────────────────────────────────────────────────

function volatilityBadge(v: MarketSnapshot["volatility"]) {
  const map = {
    low:    { label: "Low",    color: "var(--green)" },
    medium: { label: "Med",    color: "var(--yellow)" },
    high:   { label: "High",   color: "var(--red)" },
  };
  const { label, color } = map[v];
  return <span style={{ color, fontWeight: 700, fontSize: 11 }}>{label}</span>;
}

function trendBadge(row: MarketSnapshot) {
  if (row.market_type === "trending") {
    const up = row.trend_direction === "up";
    return (
      <span style={{ color: up ? "var(--green)" : "var(--red)", fontWeight: 700, fontSize: 11 }}>
        {up ? "▲ Trend" : "▼ Trend"}
      </span>
    );
  }
  if (row.market_type === "ranging") {
    return <span style={{ color: "var(--blue)", fontWeight: 700, fontSize: 11 }}>↔ Range</span>;
  }
  return <span style={{ color: "var(--muted)", fontWeight: 700, fontSize: 11 }}>~ Mixed</span>;
}

function moodColor(mood: MarketSummary["market_mood"]) {
  if (mood === "bullish") return "var(--green)";
  if (mood === "bearish") return "var(--red)";
  return "var(--yellow)";
}

// Range bar showing price position between support and resistance
function RangeBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  const color = clamped < 25 ? "var(--green)"
    : clamped > 75 ? "var(--red)"
    : "var(--blue)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <div style={{ flex: 1, height: 4, background: "var(--border)", borderRadius: 2, position: "relative" }}>
        <div style={{
          position: "absolute", top: 0, left: `${clamped}%`,
          width: 6, height: 6, borderRadius: "50%",
          background: color, transform: "translate(-50%, -50%) translateY(2px)",
        }} />
      </div>
      <span style={{ fontSize: 10, color: "var(--muted)", minWidth: 28 }}>{pct.toFixed(0)}%</span>
    </div>
  );
}

// ── Summary cards ──────────────────────────────────────────────────────────────

function SummaryCards({ summary, isLoading }: { summary?: MarketSummary; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className={styles.summaryGrid}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className={`${styles.summaryCard} ${styles.skeleton}`} />
        ))}
      </div>
    );
  }
  if (!summary || summary.error) return null;

  return (
    <div className={styles.summaryGrid}>
      {/* Market mood */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryLabel}>Market Mood</div>
        <div className={styles.summaryValue} style={{ color: moodColor(summary.market_mood) }}>
          {summary.market_mood === "bullish" ? "🟢" : summary.market_mood === "bearish" ? "🔴" : "🟡"}{" "}
          {summary.market_mood.toUpperCase()}
        </div>
        <div className={styles.summaryMeta}>
          {summary.gainers} up · {summary.losers} down
        </div>
      </div>

      {/* Trend / Range count */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryLabel}>Market Regime</div>
        <div className={styles.summaryValue}>
          <span style={{ color: "var(--green)" }}>{summary.trending_count}</span>
          <span style={{ color: "var(--muted)", fontSize: 13 }}> trending</span>
        </div>
        <div className={styles.summaryMeta}>{summary.ranging_count} ranging · {summary.scanned_pairs} scanned</div>
      </div>

      {/* Avg volatility */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryLabel}>Avg Volatility (ATR%)</div>
        <div className={styles.summaryValue} style={{
          color: summary.avg_atr_pct > 2 ? "var(--red)" : summary.avg_atr_pct > 0.8 ? "var(--yellow)" : "var(--green)",
        }}>
          {summary.avg_atr_pct.toFixed(2)}%
        </div>
        <div className={styles.summaryMeta}>
          {summary.avg_atr_pct > 2 ? "High volatility" : summary.avg_atr_pct > 0.8 ? "Medium volatility" : "Low volatility"}
        </div>
      </div>

      {/* Top gainer */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryLabel}>Top Gainer (24h)</div>
        <div className={styles.summaryValue} style={{ color: "var(--green)" }}>
          {fmtPct(summary.top_gainer.change_24h_pct)}
        </div>
        <div className={styles.summaryMeta}>
          {summary.top_gainer.pair} @ {fmtPrice(summary.top_gainer.price)}
        </div>
      </div>

      {/* Top loser */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryLabel}>Top Loser (24h)</div>
        <div className={styles.summaryValue} style={{ color: "var(--red)" }}>
          {fmtPct(summary.top_loser.change_24h_pct)}
        </div>
        <div className={styles.summaryMeta}>
          {summary.top_loser.pair} @ {fmtPrice(summary.top_loser.price)}
        </div>
      </div>

      {/* Most volatile */}
      <div className={styles.summaryCard}>
        <div className={styles.summaryLabel}>Most Volatile</div>
        <div className={styles.summaryValue} style={{ color: "var(--red)" }}>
          {summary.most_volatile.atr_pct.toFixed(2)}% ATR
        </div>
        <div className={styles.summaryMeta}>
          {summary.most_volatile.pair} · {fmtVolume(summary.highest_volume.volume_24h_usd)} vol leader
        </div>
      </div>
    </div>
  );
}

// ── Strategy suggestions popover ───────────────────────────────────────────────

function StrategyCell({ suggestions, onSelect }: {
  suggestions: MarketSnapshot["top_strategies"];
  onSelect: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!suggestions.length) return <span className={styles.muted}>—</span>;

  return (
    <div className={styles.strategyCell} onMouseLeave={() => setOpen(false)}>
      <button
        className={styles.strategyPill}
        onClick={() => setOpen(!open)}
        onMouseEnter={() => setOpen(true)}
      >
        {suggestions[0].name}
        {suggestions.length > 1 && (
          <span className={styles.strategyMore}>+{suggestions.length - 1}</span>
        )}
      </button>
      {open && (
        <div className={styles.strategyPopover}>
          {suggestions.map((s) => (
            <button key={s.name} className={styles.strategyPopoverItem} onClick={() => onSelect(s.name)}>
              <span className={styles.strategyPopoverName}>{s.name}</span>
              <span className={styles.strategyPopoverReason}>{s.reason}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Market() {
  const [timeframe, setTimeframe] = useState<TF>("1h");
  const [sortKey, setSortKey]   = useState<SortKey>("volume_24h_usd");
  const [sortAsc, setSortAsc]   = useState(false);
  const [filter, setFilter]     = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);

  const { data: scanner, isLoading: scanLoading, dataUpdatedAt } = useQuery({
    queryKey: ["market-scanner", timeframe],
    queryFn: () => fetchMarketScanner({ timeframe }),
    refetchInterval: 5 * 60 * 1000,   // refresh every 5 min (cache TTL aligned)
    staleTime: 4 * 60 * 1000,
  });

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["market-summary", timeframe],
    queryFn: () => fetchMarketSummary({ timeframe }),
    refetchInterval: 5 * 60 * 1000,
    staleTime: 4 * 60 * 1000,
  });

  // Sort + filter
  const rows = useMemo(() => {
    if (!scanner) return [];
    let filtered = scanner;
    if (filter) {
      const q = filter.toLowerCase();
      filtered = filtered.filter((r) => r.pair.toLowerCase().includes(q));
    }
    if (selectedStrategy) {
      filtered = filtered.filter((r) =>
        r.top_strategies.some((s) => s.name === selectedStrategy)
      );
    }
    return [...filtered].sort((a, b) => {
      const av = a[sortKey as keyof MarketSnapshot];
      const bv = b[sortKey as keyof MarketSnapshot];
      if (typeof av === "string" && typeof bv === "string") {
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const an = av as number;
      const bn = bv as number;
      return sortAsc ? an - bn : bn - an;
    });
  }, [scanner, sortKey, sortAsc, filter, selectedStrategy]);

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  }

  function sortIndicator(key: SortKey) {
    if (key !== sortKey) return <span className={styles.sortNeutral}>⇅</span>;
    return <span style={{ color: "var(--accent)" }}>{sortAsc ? "↑" : "↓"}</span>;
  }

  const lastUpdate = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null;

  return (
    <div className={styles.page}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>📡 Market Scanner</h2>
          <p className={styles.subtitle}>
            Volatility · Momentum · Trend · Strategy suggestions
            {lastUpdate && <span className={styles.lastUpdate}> · Updated {lastUpdate}</span>}
          </p>
        </div>
        <div className={styles.headerControls}>
          <TabBar
            variant="buttons"
            size="sm"
            tabs={TIMEFRAMES.map((tf) => ({ value: tf, label: tf }))}
            active={timeframe}
            onChange={(v) => setTimeframe(v as TF)}
          />
        </div>
      </div>

      {/* ── Summary cards ────────────────────────────────────────────────── */}
      <SummaryCards summary={summary} isLoading={summaryLoading} />

      {/* ── Filters ──────────────────────────────────────────────────────── */}
      <div className={styles.filterRow}>
        <input
          className={styles.searchInput}
          placeholder="🔍  Filter pair…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {selectedStrategy && (
          <div className={styles.activeFilter}>
            Strategy: <strong>{selectedStrategy}</strong>
            <button onClick={() => setSelectedStrategy(null)}>×</button>
          </div>
        )}
        {scanLoading && <span className={styles.loadingPill}>⏳ Scanning…</span>}
        {scanner && <span className={styles.countPill}>{rows.length} pairs</span>}
      </div>

      {/* ── Table ────────────────────────────────────────────────────────── */}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              {SORT_COLS.map((col) => (
                <th
                  key={col.key}
                  className={styles.th}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label} {sortIndicator(col.key)}
                </th>
              ))}
              <th className={styles.th}>Volatility</th>
              <th className={styles.th}>Trend</th>
              <th className={styles.th}>S/R Position</th>
              <th className={styles.th}>Strategies</th>
            </tr>
          </thead>
          <tbody>
            {scanLoading && (
              Array.from({ length: 12 }).map((_, i) => (
                <tr key={i} className={styles.skeletonRow}>
                  {Array.from({ length: 14 }).map((__, j) => (
                    <td key={j}><div className={styles.skeletonCell} /></td>
                  ))}
                </tr>
              ))
            )}
            {rows.map((row) => (
              <tr key={row.pair} className={styles.tr}>
                {/* Pair */}
                <td className={styles.pairCell}>
                  <span className={styles.pairName}>{row.pair.replace("/USDT", "")}</span>
                  <span className={styles.pairQuote}>/USDT</span>
                </td>

                {/* Price */}
                <td className={styles.numCell}>{fmtPrice(row.price)}</td>

                {/* Changes */}
                <td className={styles.numCell} style={{ color: percentColor(row.change_1h_pct) }}>
                  {fmtPct(row.change_1h_pct)}
                </td>
                <td className={styles.numCell} style={{ color: percentColor(row.change_4h_pct) }}>
                  {fmtPct(row.change_4h_pct)}
                </td>
                <td className={styles.numCell} style={{ color: percentColor(row.change_24h_pct), fontWeight: 700 }}>
                  {fmtPct(row.change_24h_pct)}
                </td>
                <td className={styles.numCell} style={{ color: percentColor(row.change_7d_pct) }}>
                  {fmtPct(row.change_7d_pct)}
                </td>

                {/* Volume */}
                <td className={styles.numCell} style={{ color: "var(--muted)" }}>
                  {fmtVolume(row.volume_24h_usd)}
                </td>

                {/* ATR% */}
                <td className={styles.numCell} style={{
                  color: row.atr_pct > 2 ? "var(--red)" : row.atr_pct > 0.8 ? "var(--yellow)" : "var(--green)",
                  fontWeight: 600,
                }}>
                  {row.atr_pct.toFixed(2)}%
                </td>

                {/* ADX */}
                <td className={styles.numCell} style={{ color: adxColor(row.adx), fontWeight: 600 }}>
                  {row.adx.toFixed(0)}
                </td>

                {/* RSI */}
                <td className={styles.numCell}>
                  <span style={{
                    color: rsiColor(row.rsi),
                    fontWeight: row.rsi >= 70 || row.rsi <= 30 ? 700 : 400,
                  }}>
                    {row.rsi.toFixed(0)}
                    {row.rsi >= 70 && <span style={{ fontSize: 10 }}> OB</span>}
                    {row.rsi <= 30 && <span style={{ fontSize: 10 }}> OS</span>}
                  </span>
                </td>

                {/* Volatility badge */}
                <td className={styles.centeredCell}>{volatilityBadge(row.volatility)}</td>

                {/* Trend badge */}
                <td className={styles.centeredCell}>{trendBadge(row)}</td>

                {/* Support/Resistance range bar */}
                <td className={styles.rangeCell}>
                  <div className={styles.srLabels}>
                    <span style={{ fontSize: 9, color: "var(--green)" }}>S {fmtPrice(row.support)}</span>
                    <span style={{ fontSize: 9, color: "var(--red)" }}>R {fmtPrice(row.resistance)}</span>
                  </div>
                  <RangeBar pct={row.price_in_range_pct} />
                </td>

                {/* Strategies */}
                <td className={styles.strategyTd}>
                  <StrategyCell
                    suggestions={row.top_strategies}
                    onSelect={setSelectedStrategy}
                  />
                </td>
              </tr>
            ))}

            {!scanLoading && rows.length === 0 && (
              <tr>
                <td colSpan={14} className={styles.emptyRow}>
                  No pairs match your filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ── Legend ───────────────────────────────────────────────────────── */}
      <div className={styles.legend}>
        <span><strong>ATR%</strong> — normalised volatility (ATR÷price). Low &lt;0.5% · Med 0.5–2% · High &gt;2%</span>
        <span><strong>ADX</strong> — trend strength. &gt;25 trending · 18–25 weak · &lt;18 ranging</span>
        <span><strong>RSI</strong> — momentum. &gt;70 overbought (OB) · &lt;30 oversold (OS)</span>
        <span><strong>S/R bar</strong> — price position within 14-day support/resistance range</span>
        <span><strong>Strategies</strong> — hover/click for suggestions tailored to current regime. Click a suggestion to filter table.</span>
      </div>
    </div>
  );
}
