import styles from "./Card.module.css";

interface CardProps {
  header?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  padding?: "none" | "sm" | "md" | "lg";
  className?: string;
}

export default function Card({ header, footer, children, padding = "md", className }: CardProps) {
  return (
    <div className={[styles.card, className].filter(Boolean).join(" ")}>
      {header && <div className={styles.header}>{header}</div>}
      <div className={[styles.body, styles[`pad_${padding}`]].join(" ")}>{children}</div>
      {footer && <div className={styles.footer}>{footer}</div>}
    </div>
  );
}
