import styles from "./Spinner.module.css";

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  color?: string;
  label?: string;
}

export default function Spinner({ size = "md", color, label = "Loading…" }: SpinnerProps) {
  return (
    <span
      className={`${styles.spinner} ${styles[size]}`}
      style={color ? { borderTopColor: color } : undefined}
      role="status"
      aria-label={label}
    />
  );
}
