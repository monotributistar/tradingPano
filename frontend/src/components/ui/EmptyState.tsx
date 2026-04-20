import styles from "./EmptyState.module.css";

export interface EmptyStateProps {
  message: string;
  /** Optional leading emoji */
  icon?: string;
  /** Optional CTA button */
  action?: { label: string; onClick: () => void };
  /** 'sm' = 24px padding, 'md' = 40px (default) */
  size?: "sm" | "md";
}

export default function EmptyState({ message, icon, action, size = "md" }: EmptyStateProps) {
  return (
    <div className={[styles.wrap, styles[size]].join(" ")}>
      {icon && <span className={styles.icon}>{icon}</span>}
      <p className={styles.message}>{message}</p>
      {action && (
        <button className={styles.action} onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}
