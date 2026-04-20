import React from "react";
import styles from "./Input.module.css";

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "prefix"> {
  value: string | number;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  label?: string;
  error?: string;
  hint?: string;
  /** Leading adornment (icon or text) */
  prefix?: React.ReactNode;
  /** Trailing adornment (unit or icon) */
  suffix?: React.ReactNode;
}

export default function Input({
  value, onChange, label, error, hint, prefix, suffix, className, id, ...rest
}: InputProps) {
  const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className={styles.wrap}>
      {label && <label className={styles.label} htmlFor={inputId}>{label}</label>}
      <div className={[styles.inputWrap, error ? styles.hasError : ""].join(" ")}>
        {prefix && <span className={styles.prefix}>{prefix}</span>}
        <input
          {...rest}
          id={inputId}
          value={value}
          onChange={onChange}
          className={[styles.input, className].filter(Boolean).join(" ")}
        />
        {suffix && <span className={styles.suffix}>{suffix}</span>}
      </div>
      {error && <p className={styles.error}>{error}</p>}
      {hint && !error && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}
