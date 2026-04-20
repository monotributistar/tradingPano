import styles from "./Alert.module.css";

export type AlertVariant = "error" | "warning" | "info" | "success";

export interface AlertProps {
  variant?: AlertVariant;
  title?: string;
  children: React.ReactNode;
  /** Show an ✕ dismiss button */
  onDismiss?: () => void;
  /** Compact single-line style */
  compact?: boolean;
}

const ICONS: Record<AlertVariant, string> = {
  error:   "✗",
  warning: "⚠",
  info:    "ℹ",
  success: "✓",
};

export default function Alert({
  variant = "error", title, children, onDismiss, compact,
}: AlertProps) {
  return (
    <div className={[styles.alert, styles[variant], compact ? styles.compact : ""].filter(Boolean).join(" ")}>
      <span className={styles.icon}>{ICONS[variant]}</span>
      <div className={styles.body}>
        {title && <strong className={styles.title}>{title}</strong>}
        <span className={styles.message}>{children}</span>
      </div>
      {onDismiss && (
        <button className={styles.dismiss} onClick={onDismiss} aria-label="Dismiss">✕</button>
      )}
    </div>
  );
}
