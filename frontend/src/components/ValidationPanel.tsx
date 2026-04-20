import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import {
  runWalkForward, runMonteCarlo,
  type WalkForwardResult, type MonteCarloResult,
} from "../api/client";

interface Props {
  jobId: number;
}

export default function ValidationPanel({ jobId }: Props) {
  const [wfSegments, setWfSegments] = useState(5);
  const [wfPeriod, setWfPeriod] = useState("1y");
  const [mcRuns, setMcRuns] = useState(1000);

  const wfMutation = useMutation({
    mutationFn: () => runWalkForward(jobId, wfSegments, wfPeriod),
  });

  const mcMutation = useMutation({
    mutationFn: () => runMonteCarlo(jobId, mcRuns),
  });

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
      {/* Walk-forward panel */}
      <div style={panelStyle}>
        <h3 style={headerStyle}>🔄 Walk-forward validation</h3>
        <p style={descStyle}>
          Split the dataset into N chunks; test the strategy on each slice.
          Reveals whether performance is consistent across regimes.
        </p>

        <div style={controlsStyle}>
          <label style={labelStyle}>
            Segments
            <input type="number" min={2} max={20} value={wfSegments}
              onChange={(e) => setWfSegments(+e.target.value)}
              style={inputStyle} />
          </label>
          <label style={labelStyle}>
            Period
            <select value={wfPeriod} onChange={(e) => setWfPeriod(e.target.value)} style={inputStyle}>
              <option value="6m">6 months</option>
              <option value="1y">1 year</option>
              <option value="2y">2 years</option>
            </select>
          </label>
          <button
            onClick={() => wfMutation.mutate()}
            disabled={wfMutation.isPending}
            style={btnStyle}
          >
            {wfMutation.isPending ? "Running…" : "Run"}
          </button>
        </div>

        {wfMutation.data && <WFResultsView data={wfMutation.data} />}
        {wfMutation.isError && (
          <div style={errorStyle}>{String((wfMutation.error as any)?.response?.data?.detail ?? wfMutation.error)}</div>
        )}
      </div>

      {/* Monte Carlo panel */}
      <div style={panelStyle}>
        <h3 style={headerStyle}>🎲 Monte Carlo (trade-order shuffle)</h3>
        <p style={descStyle}>
          Shuffles the trade sequence N times to show the distribution of
          possible drawdowns. Real signal is in the tails, not the mean.
        </p>

        <div style={controlsStyle}>
          <label style={labelStyle}>
            Runs
            <select value={mcRuns} onChange={(e) => setMcRuns(+e.target.value)} style={inputStyle}>
              <option value={100}>100</option>
              <option value={500}>500</option>
              <option value={1000}>1,000</option>
              <option value={5000}>5,000</option>
              <option value={10000}>10,000</option>
            </select>
          </label>
          <button
            onClick={() => mcMutation.mutate()}
            disabled={mcMutation.isPending}
            style={btnStyle}
          >
            {mcMutation.isPending ? "Running…" : "Run"}
          </button>
        </div>

        {mcMutation.data && <MCResultsView data={mcMutation.data} />}
        {mcMutation.isError && (
          <div style={errorStyle}>{String((mcMutation.error as any)?.response?.data?.detail ?? mcMutation.error)}</div>
        )}
      </div>
    </div>
  );
}

function WFResultsView({ data }: { data: WalkForwardResult }) {
  if (data.error) {
    return <div style={errorStyle}>{data.error}</div>;
  }

  const agg = data.aggregate;
  const chartData = data.segments.map((s) => ({
    name: `Seg ${s.index + 1}`,
    return_pct: s.return_pct,
    trades: s.trades,
    range: s.start && s.end ? `${s.start} → ${s.end}` : "",
  }));

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginTop: 12, marginBottom: 12 }}>
        <MiniStat label="Avg return" value={`${agg.avg_return_pct >= 0 ? "+" : ""}${agg.avg_return_pct.toFixed(2)}%`} color={agg.avg_return_pct >= 0 ? "var(--green)" : "var(--red)"} />
        <MiniStat label="Consistency" value={`${agg.consistency_score.toFixed(0)}%`} color={agg.consistency_score >= 60 ? "var(--green)" : agg.consistency_score >= 40 ? "var(--yellow)" : "var(--red)"} />
        <MiniStat label="Avg Sharpe" value={agg.avg_sharpe.toFixed(2)} color={agg.avg_sharpe >= 1 ? "var(--green)" : agg.avg_sharpe >= 0 ? "var(--yellow)" : "var(--red)"} />
        <MiniStat label="Best segment" value={`+${agg.best_segment_return.toFixed(2)}%`} color="var(--green)" />
        <MiniStat label="Worst segment" value={`${agg.worst_segment_return.toFixed(2)}%`} color="var(--red)" />
        <MiniStat label="Std dev" value={`${agg.std_return_pct.toFixed(2)}%`} />
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--muted)" }} />
          <YAxis tick={{ fontSize: 11, fill: "var(--muted)" }} tickFormatter={(v) => `${v}%`} />
          <Tooltip
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 }}
            formatter={(v: any, k: any) => k === "return_pct" ? [`${Number(v).toFixed(2)}%`, "Return"] : [v, k]}
          />
          <ReferenceLine y={0} stroke="var(--muted)" />
          <Bar dataKey="return_pct">
            {chartData.map((d, i) => (
              <Cell key={i} fill={d.return_pct >= 0 ? "#22c55e" : "#ef4444"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function MCResultsView({ data }: { data: MonteCarloResult }) {
  const histData = data.histogram || [];
  // Backend returns probability as 0-100 already
  const profitProb = data.probability_profit.toFixed(1);
  const probDecimal = data.probability_profit / 100;

  return (
    <div>
      {data.note && <div style={{ fontSize: 11, color: "var(--muted)", fontStyle: "italic", margin: "8px 0" }}>{data.note}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginTop: 12, marginBottom: 12 }}>
        <MiniStat label="Mean return" value={`${data.mean_return_pct >= 0 ? "+" : ""}${data.mean_return_pct.toFixed(2)}%`} color={data.mean_return_pct >= 0 ? "var(--green)" : "var(--red)"} />
        <MiniStat label="Prob profit" value={`${profitProb}%`} color={probDecimal >= 0.7 ? "var(--green)" : probDecimal >= 0.5 ? "var(--yellow)" : "var(--red)"} />
        <MiniStat label="Median DD" value={`${data.max_drawdown_distribution.median.toFixed(2)}%`} color="var(--red)" />
        <MiniStat label="P5 (worst 5%)" value={`${data.percentile_5_pct.toFixed(2)}%`} color="var(--red)" />
        <MiniStat label="P95 (best 5%)" value={`${data.percentile_95_pct.toFixed(2)}%`} color="var(--green)" />
        <MiniStat label="P95 max DD" value={`${data.max_drawdown_distribution.percentile_95.toFixed(2)}%`} color="var(--red)" />
      </div>

      {histData.length > 1 && (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={histData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="bucket_pct"
              tick={{ fontSize: 10, fill: "var(--muted)" }}
              tickFormatter={(v) => `${Number(v).toFixed(0)}%`}
            />
            <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} />
            <Tooltip
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", fontSize: 12 }}
              formatter={(v: any) => [v, "Runs"]}
              labelFormatter={(v) => `Return: ${Number(v).toFixed(1)}%`}
            />
            <ReferenceLine x={0} stroke="var(--muted)" strokeDasharray="3 3" />
            <Bar dataKey="count" fill="var(--accent)" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 4,
      padding: "6px 8px",
    }}>
      <div style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: color ?? "var(--text)" }}>{value}</div>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: 16,
};

const headerStyle: React.CSSProperties = {
  margin: "0 0 6px 0",
  fontSize: 14,
  fontWeight: 600,
};

const descStyle: React.CSSProperties = {
  margin: "0 0 12px 0",
  fontSize: 11,
  color: "var(--muted)",
  lineHeight: 1.4,
};

const controlsStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "flex-end",
};

const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  fontSize: 10,
  color: "var(--muted)",
  textTransform: "uppercase",
  letterSpacing: 0.5,
  flex: 1,
};

const inputStyle: React.CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border)",
  borderRadius: 4,
  padding: "6px 8px",
  color: "var(--text)",
  fontSize: 12,
};

const btnStyle: React.CSSProperties = {
  padding: "6px 16px",
  background: "var(--accent)",
  color: "white",
  border: "none",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 600,
  height: 32,
};

const errorStyle: React.CSSProperties = {
  background: "rgba(239, 68, 68, 0.1)",
  border: "1px solid var(--red)",
  color: "var(--red)",
  padding: 8,
  borderRadius: 4,
  fontSize: 12,
  marginTop: 8,
};
