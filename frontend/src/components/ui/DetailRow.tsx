import styles from "./DetailRow.module.css";

export interface DetailRowProps {
  label: string;
  value: React.ReactNode;
  /** Mute the value text (use for secondary info) */
  muted?: boolean;
  /** Show a horizontal divider below the row */
  divider?: boolean;
  /** Align value text to the right (default: right) */
  align?: "left" | "right";
}

export default function DetailRow({ label, value, muted, divider, align = "right" }: DetailRowProps) {
  return (
    <div className={[styles.row, divider ? styles.divider : ""].filter(Boolean).join(" ")}>
      <span className={styles.label}>{label}</span>
      <span
        className={[styles.value, muted ? styles.muted : ""].filter(Boolean).join(" ")}
        style={{ textAlign: align }}
      >
        {value}
      </span>
    </div>
  );
}
