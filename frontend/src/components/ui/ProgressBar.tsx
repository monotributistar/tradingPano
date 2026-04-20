import styles from "./ProgressBar.module.css";

export type ProgressColor = "green" | "yellow" | "red" | "blue" | "auto";

export interface ProgressBarProps {
  /** Current value */
  value: number;
  /** Maximum value (default 100) */
  max?: number;
  /**
   * Bar fill color.
   * `"auto"` picks green → yellow → red based on threshold (60% / 85%).
   */
  color?: ProgressColor;
  /** Text label shown above the bar */
  label?: string;
  /** Show the percentage number inside or beside the bar */
  showPercent?: boolean;
  /** Bar height in px (default 6) */
  height?: number;
  /** Animated shimmer while in loading/indeterminate state */
  indeterminate?: boolean;
}

function autoColor(pct: number): ProgressColor {
  if (pct > 85) return "red";
  if (pct > 60) return "yellow";
  return "green";
}

export default function ProgressBar({
  value,
  max = 100,
  color = "blue",
  label,
  showPercent,
  height = 6,
  indeterminate,
}: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const resolvedColor = color === "auto" ? autoColor(pct) : color;

  return (
    <div className={styles.wrap}>
      {(label || showPercent) && (
        <div className={styles.header}>
          {label && <span className={styles.label}>{label}</span>}
          {showPercent && <span className={styles.pct}>{pct.toFixed(0)}%</span>}
        </div>
      )}
      <div className={styles.track} style={{ height }}>
        <div
          className={[
            styles.fill,
            styles[resolvedColor],
            indeterminate ? styles.indeterminate : "",
          ].filter(Boolean).join(" ")}
          style={indeterminate ? undefined : { width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
