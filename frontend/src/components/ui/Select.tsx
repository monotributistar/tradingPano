import React from "react";
import styles from "./Select.module.css";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange"> {
  options: SelectOption[];
  value: string;
  /** Called with the new string value (not a change event) */
  onChange: (value: string) => void;
  label?: string;
  error?: string;
  placeholder?: string;
}

export default function Select({
  options, value, onChange, label, error, placeholder, id, className, ...rest
}: SelectProps) {
  const selectId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className={styles.wrap}>
      {label && <label className={styles.label} htmlFor={selectId}>{label}</label>}
      <select
        {...rest}
        id={selectId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={[styles.select, error ? styles.hasError : "", className].filter(Boolean).join(" ")}
      >
        {placeholder && <option value="" disabled>{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
        ))}
      </select>
      {error && <p className={styles.error}>{error}</p>}
    </div>
  );
}
