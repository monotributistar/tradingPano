import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface Props {
  curve: number[];
  timestamps?: string[];
  initialCapital?: number;
  height?: number;
}

export default function EquityCurve({ curve, timestamps, initialCapital, height = 220 }: Props) {
  if (!curve.length) return <div style={{ color: "var(--muted)", padding: 24, textAlign: "center" }}>No equity data</div>;

  const data = curve.map((v, i) => ({
    value: +v.toFixed(4),
    label: timestamps?.[i] ? timestamps[i].substring(5, 16) : String(i),
  }));

  const isProfit = curve[curve.length - 1] >= (initialCapital ?? curve[0]);
  const color = isProfit ? "var(--green)" : "var(--red)";
  const min = Math.min(...curve);
  const max = Math.max(...curve);
  const padding = (max - min) * 0.05 || 1;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="label"
          tick={{ fill: "var(--muted)", fontSize: 11 }}
          interval="preserveStartEnd"
          tickLine={false}
        />
        <YAxis
          domain={[min - padding, max + padding]}
          tick={{ fill: "var(--muted)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => `$${v.toFixed(1)}`}
          width={55}
        />
        <Tooltip
          contentStyle={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: 6 }}
          labelStyle={{ color: "var(--muted)", fontSize: 11 }}
          formatter={(v: number) => [`$${v.toFixed(4)}`, "Equity"]}
        />
        {initialCapital && (
          <ReferenceLine y={initialCapital} stroke="var(--muted)" strokeDasharray="4 4" />
        )}
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
