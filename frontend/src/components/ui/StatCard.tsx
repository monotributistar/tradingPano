import styles from "./StatCard.module.css";

export type StatColor = "green" | "red" | "yellow" | "blue" | "muted";

export interface StatCardProps {
  label: string;
  value: string | number;
  /** Semantic color for the value */
  color?: StatColor;
  /** Secondary line below the value */
  sub?: string;
  /** Optional leading emoji / icon */
  icon?: string;
  /** 'sm' = compact (used in summary bars), 'md' = default, 'lg' = hero card */
  size?: "sm" | "md" | "lg";
  /** Full-width click area */
  onClick?: () => void;
}

const COLOR_VAR: Record<StatColor, string> = {
  green:  "var(--green)",
  red:    "var(--red)",
  yellow: "var(--yellow)",
  blue:   "var(--accent)",
  muted:  "var(--muted)",
};

export default function StatCard({
  label, value, color, sub, icon, size = "md", onClick,
}: StatCardProps) {
  const valueStyle = color ? { color: COLOR_VAR[color] } : undefined;
  return (
    <div
      className={[styles.card, styles[size], onClick ? styles.clickable : ""].filter(Boolean).join(" ")}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className={styles.label}>
        {icon && <span className={styles.icon}>{icon}</span>}
        {label}
      </div>
      <div className={styles.value} style={valueStyle}>{value}</div>
      {sub && <div className={styles.sub}>{sub}</div>}
    </div>
  );
}
