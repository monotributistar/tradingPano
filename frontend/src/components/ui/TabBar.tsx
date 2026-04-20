import styles from "./TabBar.module.css";

export interface TabItem {
  value: string;
  label: string;
  icon?: string;
  /** Small badge count */
  badge?: string | number;
  disabled?: boolean;
}

export interface TabBarProps {
  tabs: TabItem[];
  active: string;
  onChange: (value: string) => void;
  /**
   * - `pills`     — rounded filled buttons (default)
   * - `underline` — text buttons with bottom border indicator
   * - `buttons`   — bordered segmented control
   */
  variant?: "pills" | "underline" | "buttons";
  size?: "sm" | "md";
}

export default function TabBar({
  tabs, active, onChange, variant = "pills", size = "md",
}: TabBarProps) {
  return (
    <div className={[styles.bar, styles[variant], styles[size]].join(" ")}>
      {tabs.map((t) => (
        <button
          key={t.value}
          className={[styles.tab, active === t.value ? styles.active : ""].filter(Boolean).join(" ")}
          onClick={() => !t.disabled && onChange(t.value)}
          disabled={t.disabled}
          aria-pressed={active === t.value}
        >
          {t.icon && <span className={styles.tabIcon}>{t.icon}</span>}
          {t.label}
          {t.badge != null && (
            <span className={styles.badge}>{t.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}
