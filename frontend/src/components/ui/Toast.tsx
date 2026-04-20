import { useState, useCallback, useRef } from "react";
import styles from "./Toast.module.css";

// ── Types ──────────────────────────────────────────────────────────────────────

export type ToastKind = "success" | "error" | "warning" | "info";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  /** Duration in ms before auto-dismiss. Default 3500. Pass 0 to keep until manual dismiss. */
  duration?: number;
}

// ── Hook ───────────────────────────────────────────────────────────────────────

let _seq = 0;

/**
 * useToast — global toast notification hook.
 *
 * Usage:
 * ```tsx
 * const { toasts, toast } = useToast();
 * toast.success("Saved!");
 * toast.error("Something went wrong.");
 * // …
 * return <ToastContainer toasts={toasts} onDismiss={dismiss} />;
 * ```
 */
export function useToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  const dismiss = useCallback((id: number) => {
    clearTimeout(timers.current[id]);
    delete timers.current[id];
    setToasts((p) => p.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((kind: ToastKind, message: string, duration = 3500) => {
    const id = ++_seq;
    setToasts((p) => [...p, { id, kind, message, duration }]);
    if (duration > 0) {
      timers.current[id] = setTimeout(() => dismiss(id), duration);
    }
  }, [dismiss]);

  const toast = {
    success: (msg: string, d?: number) => push("success", msg, d),
    error:   (msg: string, d?: number) => push("error",   msg, d),
    warning: (msg: string, d?: number) => push("warning", msg, d),
    info:    (msg: string, d?: number) => push("info",    msg, d),
  };

  return { toasts, toast, dismiss };
}

// ── Container ─────────────────────────────────────────────────────────────────

const ICONS: Record<ToastKind, string> = {
  success: "✓",
  error:   "✗",
  warning: "⚠",
  info:    "ℹ",
};

interface ToastContainerProps {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}

export function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) return null;
  return (
    <div className={styles.container} aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={[styles.toast, styles[t.kind]].join(" ")}>
          <span className={styles.icon}>{ICONS[t.kind]}</span>
          <span className={styles.message}>{t.message}</span>
          <button
            className={styles.close}
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
