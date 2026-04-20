import React from "react";
import styles from "./Textarea.module.css";

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  rows?: number;
}

export default function Textarea({ label, error, rows = 3, id, className, ...rest }: TextareaProps) {
  const areaId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className={styles.wrap}>
      {label && <label className={styles.label} htmlFor={areaId}>{label}</label>}
      <textarea
        {...rest}
        id={areaId}
        rows={rows}
        className={[styles.textarea, error ? styles.hasError : "", className].filter(Boolean).join(" ")}
      />
      {error && <p className={styles.error}>{error}</p>}
    </div>
  );
}
