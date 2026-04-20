import { useMemo, useState } from "react";
import {
  ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Customized,
} from "recharts";
import type { OHLCVCandle, Trade } from "../api/client";
import {
  ema as calcEma, sma as calcSma, bollingerBands,
  rsi as calcRsi, macd as calcMacd,
  supertrend as calcSupertrend, vwap as calcVwap,
} from "../lib/indicators";
import {
  getPriceIndicators, getOscIndicator,
  type IndicatorDef,
} from "../lib/strategyIndicators";

interface Props {
  candles:   OHLCVCandle[];
  trades?:   Trade[];
  height?:   number;
  strategy?: string;
}

// ── Candlestick SVG layer (rendered via <Customized>) ─────────────────────────

function CandlestickLayer({ xAxisMap, yAxisMap, data }: any) {
  const xAxis = xAxisMap?.["0"];
  const yAxis = yAxisMap?.["0"];
  if (!xAxis?.scale || !yAxis?.scale) return null;

  const bw = typeof xAxis.scale.bandwidth === "function" ? xAxis.scale.bandwidth() : 8;
  const cw = Math.max(1, Math.min(bw * 0.65, 14));

  return (
    <g>
      {(data as any[]).map((d) => {
        const x = xAxis.scale(d.label);
        if (x === undefined || d.open == null) return null;
        const cx     = x + bw / 2;
        const openY  = yAxis.scale(d.open);
        const closeY = yAxis.scale(d.close);
        const highY  = yAxis.scale(d.high);
        const lowY   = yAxis.scale(d.low);
        const bull   = d.close >= d.open;
        const color  = bull ? "#22c55e" : "#ef4444";
        const bodyTop = Math.min(openY, closeY);
        const bodyH   = Math.max(1, Math.abs(closeY - openY));
        return (
          <g key={`c-${d.label}`}>
            <line x1={cx} x2={cx} y1={highY} y2={lowY} stroke={color} strokeWidth={1} />
            <rect
              x={cx - cw / 2} y={bodyTop} width={cw} height={bodyH}
              fill={color} stroke={color} strokeWidth={0.5}
              fillOpacity={bull ? 0.75 : 0.9}
            />
          </g>
        );
      })}
    </g>
  );
}

// ── Trade signal triangles ─────────────────────────────────────────────────────

function TradeMarker(props: any) {
  const { cx, cy, payload } = props;
  if (!payload?.tradeType) return <g />;
  const type    = payload.tradeType as string;
  const isBuy   = type === "buy" || type === "cover" || type === "cover_eod";
  const isShort = type === "short";
  const color   = isBuy ? "#22c55e" : isShort ? "#f59e0b" : "#ef4444";
  const size    = 9;
  const d = isBuy
    ? `M ${cx} ${cy - size} L ${cx + size} ${cy + size * 0.6} L ${cx - size} ${cy + size * 0.6} Z`
    : `M ${cx} ${cy + size} L ${cx + size} ${cy - size * 0.6} L ${cx - size} ${cy - size * 0.6} Z`;
  return <path d={d} fill={color} stroke="rgba(0,0,0,0.5)" strokeWidth={1} />;
}

// ── Tooltip ────────────────────────────────────────────────────────────────────

function PriceTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div style={{
      background: "var(--bg3)", border: "1px solid var(--border)",
      borderRadius: 6, padding: "8px 12px", fontSize: 12, lineHeight: 1.7,
      pointerEvents: "none",
    }}>
      <div style={{ color: "var(--muted)", fontSize: 11, marginBottom: 4 }}>{d.label}</div>
      {d.open != null && (
        <div style={{ display: "grid", gridTemplateColumns: "auto auto", gap: "0 12px", fontSize: 11 }}>
          <span style={{ color: "var(--muted)" }}>O</span>
          <b>{d.open?.toFixed(2)}</b>
          <span style={{ color: "var(--muted)" }}>H</span>
          <b style={{ color: "#22c55e" }}>{d.high?.toFixed(2)}</b>
          <span style={{ color: "var(--muted)" }}>L</span>
          <b style={{ color: "#ef4444" }}>{d.low?.toFixed(2)}</b>
          <span style={{ color: "var(--muted)" }}>C</span>
          <b>{d.close?.toFixed(2)}</b>
        </div>
      )}
      {d.tradeType && (
        <div style={{
          marginTop: 4, fontWeight: 700, textTransform: "uppercase" as const,
          color: d.tradeType === "buy" || d.tradeType === "cover" || d.tradeType === "cover_eod"
            ? "var(--green)" : d.tradeType === "short" ? "#f59e0b" : "var(--red)",
        }}>
          {d.tradeType.replace("_eod", " (eod)")}
          {d.pnl != null && (
            <span style={{ color: d.pnl >= 0 ? "var(--green)" : "var(--red)", fontWeight: 400, marginLeft: 6 }}>
              PnL: {d.pnl >= 0 ? "+" : ""}{d.pnl.toFixed(4)}
              {d.pnl_pct != null ? ` (${d.pnl_pct.toFixed(2)}%)` : ""}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Indicator legend chips ─────────────────────────────────────────────────────

function IndicatorLegend({ indicators }: { indicators: IndicatorDef[] }) {
  if (!indicators.length) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
      {indicators.map((ind) => (
        <span
          key={ind.id}
          style={{
            padding: "2px 7px",
            background: `${ind.color ?? "#888"}22`,
            border: `1px solid ${ind.color ?? "#888"}55`,
            borderRadius: 10,
            fontSize: 11,
            fontWeight: 600,
            color: ind.color ?? "var(--muted)",
          }}
        >
          {ind.label}
        </span>
      ))}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function PriceChart({
  candles,
  trades = [],
  height = 320,
  strategy,
}: Props) {
  const [viewMode, setViewMode] = useState<"candle" | "line">("candle");

  const priceIndicators = useMemo(
    () => (strategy ? getPriceIndicators(strategy) : []),
    [strategy],
  );
  const oscIndicator = useMemo(
    () => (strategy ? getOscIndicator(strategy) : null),
    [strategy],
  );

  // Build merged chart data (OHLCV + indicator series + trade overlays)
  const data = useMemo(() => {
    if (!candles.length) return [];

    // Minute-precision trade lookup
    const tradeMap = new Map<string, Trade>();
    for (const t of trades) {
      if (t.timestamp) {
        const key = t.timestamp.replace(" ", "T").substring(0, 16);
        tradeMap.set(key, t);
      }
    }

    const closes  = candles.map((c) => c.c);
    const highs   = candles.map((c) => c.h);
    const lows    = candles.map((c) => c.l);
    const volumes = candles.map((c) => c.v);

    // Compute all price indicator series
    const series: Record<string, (number | null)[]> = {};

    for (const ind of priceIndicators) {
      const p = ind.params;
      switch (ind.type) {
        case "ema":
          series[ind.id] = calcEma(closes, p.period);
          break;
        case "sma":
          series[ind.id] = calcSma(closes, p.period);
          break;
        case "bollinger": {
          const bb = bollingerBands(closes, p.period, p.mult);
          series[`${ind.id}_upper`] = bb.map((x) => x.upper);
          series[`${ind.id}_mid`]   = bb.map((x) => x.mid);
          series[`${ind.id}_lower`] = bb.map((x) => x.lower);
          break;
        }
        case "supertrend": {
          const st = calcSupertrend(highs, lows, closes, p.period, p.mult);
          series[`${ind.id}_bull`] = st.map((x) => (x.bullish === true  ? x.value : null));
          series[`${ind.id}_bear`] = st.map((x) => (x.bullish === false ? x.value : null));
          break;
        }
        case "vwap":
          series[ind.id] = calcVwap(highs, lows, closes, volumes);
          break;
      }
    }

    // Compute oscillator series
    if (oscIndicator) {
      const p = oscIndicator.params;
      if (oscIndicator.type === "rsi") {
        series["osc_rsi"] = calcRsi(closes, p.period ?? 14);
      } else if (oscIndicator.type === "macd") {
        const m = calcMacd(closes, p.fast ?? 12, p.slow ?? 26, p.signal ?? 9);
        series["osc_macd"] = m.map((x) => x.macd);
        series["osc_sig"]  = m.map((x) => x.signal);
        series["osc_hist"] = m.map((x) => x.histogram);
      }
    }

    return candles.map((c, i) => {
      const date   = new Date(c.t);
      const isoKey = date.toISOString().substring(0, 16);
      const trade  = tradeMap.get(isoKey);

      const row: Record<string, any> = {
        label: date.toLocaleDateString("en-US", {
          month: "short", day: "numeric",
          hour: "2-digit", minute: "2-digit",
        }),
        open:  c.o,
        high:  c.h,
        low:   c.l,
        close: c.c,
        volume: c.v,
        tradeType: trade?.type    ?? null,
        pnl:       trade?.pnl     ?? null,
        pnl_pct:   trade?.pnl_pct ?? null,
        reason:    trade?.reason  ?? null,
      };

      for (const key of Object.keys(series)) {
        row[key] = series[key][i] ?? null;
      }

      return row;
    });
  }, [candles, trades, priceIndicators, oscIndicator]);

  if (!candles.length) {
    return (
      <div style={{ color: "var(--muted)", padding: 24, textAlign: "center" }}>
        No price data
      </div>
    );
  }

  // Price axis domain (use full OHLC range)
  const minP = Math.min(...candles.map((c) => c.l));
  const maxP = Math.max(...candles.map((c) => c.h));
  const pad  = (maxP - minP) * 0.06 || 1;

  const step  = Math.max(1, Math.floor(data.length / 6));
  const ticks = data.filter((_, i) => i % step === 0).map((d) => d.label);

  const volMax = Math.max(...candles.map((c) => c.v));

  const allIndicators = [
    ...priceIndicators,
    ...(oscIndicator ? [oscIndicator] : []),
  ];

  return (
    <div>
      {/* ── Toolbar ── */}
      <div style={{
        display: "flex", alignItems: "center", flexWrap: "wrap",
        gap: 8, marginBottom: 8,
      }}>
        <IndicatorLegend indicators={allIndicators} />
        <div style={{ display: "flex", gap: 4, marginLeft: "auto", flexShrink: 0 }}>
          {(["candle", "line"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              style={{
                padding: "3px 9px", fontSize: 11, fontWeight: 600,
                background: viewMode === m ? "rgba(99,102,241,0.15)" : "var(--bg3)",
                border: `1px solid ${viewMode === m ? "var(--accent)" : "var(--border)"}`,
                borderRadius: 5,
                color: viewMode === m ? "var(--accent)" : "var(--muted)",
                cursor: "pointer",
              }}
            >
              {m === "candle" ? "Candles" : "Line"}
            </button>
          ))}
        </div>
      </div>

      {/* ── Price chart ── */}
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart
          data={data}
          syncId="price-chart"
          margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />

          <XAxis
            dataKey="label"
            ticks={ticks}
            tick={{ fontSize: 10, fill: "var(--muted)" }}
            tickLine={false}
            hide
          />
          <YAxis
            domain={[minP - pad, maxP + pad]}
            tickFormatter={(v) =>
              v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(2)}`
            }
            tick={{ fontSize: 10, fill: "var(--muted)" }}
            tickLine={false}
            width={62}
          />
          <Tooltip content={<PriceTooltip />} />

          {/* Candle view — custom SVG layer */}
          {viewMode === "candle" && (
            <Customized component={CandlestickLayer} />
          )}

          {/* Line view — close price with trade markers */}
          {viewMode === "line" && (
            <Line
              type="monotone"
              dataKey="close"
              stroke="var(--accent)"
              strokeWidth={1.5}
              dot={<TradeMarker />}
              activeDot={{ r: 3, fill: "var(--accent)" }}
              isAnimationActive={false}
            />
          )}

          {/* ── Price-panel indicator overlays ── */}
          {priceIndicators.flatMap((ind) => {
            if (ind.type === "bollinger") {
              return [
                <Line key={`${ind.id}_upper`} type="monotone" dataKey={`${ind.id}_upper`}
                  stroke={ind.color ?? "#94a3b8"} strokeWidth={1} strokeDasharray="4 4"
                  dot={false} isAnimationActive={false} />,
                <Line key={`${ind.id}_mid`} type="monotone" dataKey={`${ind.id}_mid`}
                  stroke={ind.color ?? "#94a3b8"} strokeWidth={1}
                  dot={false} isAnimationActive={false} />,
                <Line key={`${ind.id}_lower`} type="monotone" dataKey={`${ind.id}_lower`}
                  stroke={ind.color ?? "#94a3b8"} strokeWidth={1} strokeDasharray="4 4"
                  dot={false} isAnimationActive={false} />,
              ];
            }
            if (ind.type === "supertrend") {
              return [
                <Line key={`${ind.id}_bull`} type="monotone" dataKey={`${ind.id}_bull`}
                  stroke="#22c55e" strokeWidth={2.5} dot={false}
                  connectNulls={false} isAnimationActive={false} />,
                <Line key={`${ind.id}_bear`} type="monotone" dataKey={`${ind.id}_bear`}
                  stroke="#ef4444" strokeWidth={2.5} dot={false}
                  connectNulls={false} isAnimationActive={false} />,
              ];
            }
            // EMA, SMA, VWAP — single line
            return [
              <Line
                key={ind.id}
                type="monotone"
                dataKey={ind.id}
                stroke={ind.color ?? "var(--accent)"}
                strokeWidth={1.5}
                strokeDasharray={ind.type === "sma" ? "5 3" : undefined}
                dot={false}
                isAnimationActive={false}
              />,
            ];
          })}
        </ComposedChart>
      </ResponsiveContainer>

      {/* ── Volume sub-chart ── */}
      <ResponsiveContainer width="100%" height={50}>
        <ComposedChart
          data={data}
          syncId="price-chart"
          margin={{ top: 2, right: 16, bottom: 0, left: 0 }}
        >
          <XAxis dataKey="label" hide />
          <YAxis hide domain={[0, volMax * 1.1]} width={62} />
          <Bar
            dataKey="volume"
            fill="var(--accent)"
            fillOpacity={0.22}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* ── Oscillator sub-chart (RSI or MACD) ── */}
      {oscIndicator && (
        <ResponsiveContainer width="100%" height={90}>
          <ComposedChart
            data={data}
            syncId="price-chart"
            margin={{ top: 2, right: 16, bottom: 4, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="label"
              ticks={ticks}
              tick={{ fontSize: 10, fill: "var(--muted)" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "var(--muted)" }}
              tickLine={false}
              width={62}
              domain={oscIndicator.type === "rsi" ? [0, 100] : ["auto", "auto"]}
              tickFormatter={(v) => String(Math.round(v))}
            />
            <Tooltip content={<PriceTooltip />} />

            {/* RSI */}
            {oscIndicator.type === "rsi" && (
              <>
                <Line
                  type="monotone"
                  dataKey="osc_rsi"
                  stroke={oscIndicator.color ?? "#a78bfa"}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
                {(oscIndicator.levels ?? []).map((lv) => (
                  <ReferenceLine
                    key={lv.value}
                    y={lv.value}
                    stroke={lv.color ?? "var(--border)"}
                    strokeDasharray="3 3"
                    label={{
                      value: lv.label ?? String(lv.value),
                      position: "insideTopRight",
                      fontSize: 9,
                      fill: lv.color ?? "var(--muted)",
                    }}
                  />
                ))}
              </>
            )}

            {/* MACD */}
            {oscIndicator.type === "macd" && (
              <>
                <ReferenceLine y={0} stroke="var(--border)" />
                <Bar
                  dataKey="osc_hist"
                  fill={oscIndicator.color ?? "#60a5fa"}
                  fillOpacity={0.45}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="osc_macd"
                  stroke={oscIndicator.color ?? "#60a5fa"}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="osc_sig"
                  stroke="#f59e0b"
                  strokeWidth={1.2}
                  strokeDasharray="4 3"
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
