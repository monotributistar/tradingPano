import Spinner from "./Spinner";
import styles from "./LoadingState.module.css";

export interface LoadingStateProps {
  message?: string;
  size?: "sm" | "md" | "lg";
  /** Fill the nearest positioned parent */
  fullPage?: boolean;
}

export default function LoadingState({
  message, size = "md", fullPage,
}: LoadingStateProps) {
  return (
    <div className={[styles.wrap, fullPage ? styles.fullPage : ""].filter(Boolean).join(" ")}>
      <Spinner size={size} />
      {message && <span className={styles.message}>{message}</span>}
    </div>
  );
}
