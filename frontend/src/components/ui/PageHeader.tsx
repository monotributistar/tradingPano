import styles from "./PageHeader.module.css";

export interface PageHeaderProps {
  title: string;
  subtitle?: React.ReactNode;
  icon?: string;
  /** Right-aligned actions (buttons, badges, etc.) */
  action?: React.ReactNode;
}

export default function PageHeader({ title, subtitle, icon, action }: PageHeaderProps) {
  return (
    <div className={styles.wrap}>
      <div className={styles.left}>
        <h2 className={styles.title}>
          {icon && <span className={styles.icon}>{icon}</span>}
          {title}
        </h2>
        {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
