import React from "react";
import Spinner from "./Spinner";
import styles from "./Button.module.css";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  iconLeft?: React.ReactNode;
  iconRight?: React.ReactNode;
}

export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  iconLeft,
  iconRight,
  children,
  disabled,
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={[styles.btn, styles[variant], styles[size], className].filter(Boolean).join(" ")}
    >
      {loading ? (
        <Spinner size="sm" color="currentColor" />
      ) : (
        iconLeft && <span className={styles.iconLeft}>{iconLeft}</span>
      )}
      {children && <span className={styles.label}>{children}</span>}
      {!loading && iconRight && <span className={styles.iconRight}>{iconRight}</span>}
    </button>
  );
}
