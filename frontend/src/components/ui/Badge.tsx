import styles from "./Badge.module.css";

export type BadgeColor = "green" | "red" | "yellow" | "blue" | "gray" | "purple";

export interface BadgeProps {
  /** Color / semantic variant of the badge */
  color?: BadgeColor;
  /** Alias for `color` — use whichever reads more naturally in context */
  variant?: BadgeColor;
  size?: "sm" | "md";
  dot?: boolean;
  /** Short-hand text label; overridden by `children` if both provided */
  label?: string;
  children?: React.ReactNode;
}

export default function Badge({ color, variant, size = "md", dot, label, children }: BadgeProps) {
  const resolvedColor = color ?? variant ?? "gray";
  return (
    <span className={[styles.badge, styles[resolvedColor], styles[size]].join(" ")}>
      {dot && <span className={styles.dot} />}
      {children ?? label}
    </span>
  );
}
