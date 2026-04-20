/**
 * useBotSocket — WebSocket hook for real-time bot events.
 *
 * Connects to ``ws[s]://host/api/ws/bot?api_key=<key>`` and pushes
 * typed messages to the ``onMessage`` callback.
 *
 * Features
 * --------
 * - Automatic reconnection with exponential back-off (1 s → 30 s)
 * - Server-side keepalive ping every 25 s (no client-side interval needed)
 * - Closes cleanly on component unmount
 * - API key read from localStorage via ``getApiKey()``
 *
 * Message types
 * -------------
 *   status   BotStatus snapshot (sent on connect + after every candle cycle)
 *   trade    A trade just executed {type, pair, price, qty, pnl?, pnl_pct?, ...}
 *   equity   Wallet snapshot {total_equity, balance_usdt, positions_value, positions}
 *   event    Lifecycle event {event_type, mode, strategy, detail, ...}
 *   ping     Server keepalive — no action needed
 *
 * Usage
 * -----
 *   const { connected } = useBotSocket((msg) => {
 *     if (msg.type === "trade") console.log("New trade:", msg.payload);
 *   });
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiKey } from "../api/client";

// ── Message types ──────────────────────────────────────────────────────────────

export type BotSocketMessage =
  | { type: "status";  payload: BotSocketStatus }
  | { type: "trade";   payload: BotSocketTrade }
  | { type: "equity";  payload: BotSocketEquity }
  | { type: "event";   payload: BotSocketEvent }
  | { type: "ping";    payload: null };

export interface BotSocketStatus {
  running: boolean;
  crashed: boolean;
  mode?: string;
  strategy?: string;
  pairs: string[];
  started_at?: string;
  uptime_seconds?: number;
  error?: string;
}

export interface BotSocketTrade {
  type: "buy" | "sell" | "short" | "cover";
  pair: string;
  price: number;
  qty: number;
  pnl?: number;
  pnl_pct?: number;
  strategy: string;
  mode: string;
  reason?: string;
}

export interface BotSocketEquity {
  total_equity: number;
  balance_usdt: number;
  positions_value: number;
  positions: Record<string, { qty: number; avg_cost: number }>;
}

export interface BotSocketEvent {
  event_type: string;
  mode?: string;
  strategy?: string;
  detail?: string;
  positions?: Record<string, unknown>;
}

// ── Hook ───────────────────────────────────────────────────────────────────────

const MIN_BACKOFF = 1_000;
const MAX_BACKOFF = 30_000;

interface UseBotSocketOptions {
  enabled?: boolean;
}

interface UseBotSocketResult {
  /** True when the WebSocket is open and connected. */
  connected: boolean;
}

export function useBotSocket(
  onMessage: (msg: BotSocketMessage) => void,
  { enabled = true }: UseBotSocketOptions = {},
): UseBotSocketResult {
  const [connected, setConnected] = useState(false);

  const wsRef           = useRef<WebSocket | null>(null);
  const backoffRef      = useRef(MIN_BACKOFF);
  const reconnectTimer  = useRef<ReturnType<typeof setTimeout>>();
  const onMessageRef    = useRef(onMessage);

  // Keep callback ref up to date without re-running the effect
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  const connect = useCallback(() => {
    if (!enabled) return;

    const key = getApiKey();
    if (!key) return; // wait for key modal

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/api/ws/bot?api_key=${encodeURIComponent(key)}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      backoffRef.current = MIN_BACKOFF; // reset back-off on success
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as BotSocketMessage;
        if (msg.type !== "ping") {
          onMessageRef.current(msg);
        }
      } catch {
        // malformed JSON — ignore
      }
    };

    ws.onclose = (ev) => {
      setConnected(false);
      wsRef.current = null;

      // 4003 = forbidden (wrong API key) — don't retry
      if (ev.code === 4003) return;

      const delay = backoffRef.current;
      backoffRef.current = Math.min(delay * 2, MAX_BACKOFF);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [enabled]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected };
}
