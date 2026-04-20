import styles from "./SectionHeader.module.css";

export interface SectionHeaderProps {
  title: string;
  /** Optional leading emoji or icon character */
  icon?: string;
  /** Optional right-aligned action (button, badge, etc.) */
  action?: React.ReactNode;
  /** Short subtitle / description below the title */
  subtitle?: string;
  /** Strip extra bottom margin (when content follows immediately) */
  compact?: boolean;
}

export default function SectionHeader({ title, icon, action, subtitle, compact }: SectionHeaderProps) {
  return (
    <div className={[styles.wrap, compact ? styles.compact : ""].filter(Boolean).join(" ")}>
      <div className={styles.left}>
        <h3 className={styles.title}>
          {icon && <span className={styles.icon}>{icon}</span>}
          {title}
        </h3>
        {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
