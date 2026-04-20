import { useState, useRef } from "react";
import styles from "./Tooltip.module.css";

interface TooltipProps {
  content: React.ReactNode;
  placement?: "top" | "bottom" | "left" | "right";
  delay?: number;
  children: React.ReactElement;
}

export default function Tooltip({ content, placement = "top", delay = 200, children }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  function show() {
    timer.current = setTimeout(() => setVisible(true), delay);
  }
  function hide() {
    clearTimeout(timer.current);
    setVisible(false);
  }

  return (
    <span className={styles.wrap} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {visible && content && (
        <span className={[styles.tooltip, styles[placement]].join(" ")} role="tooltip">
          {content}
        </span>
      )}
    </span>
  );
}
