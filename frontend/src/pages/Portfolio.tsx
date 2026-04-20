/**
 * Portfolio — Multi-strategy portfolio control page.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchPortfolioStatus, startPortfolio, stopPortfolio } from "../api/client";
import type { PortfolioStatus, PortfolioSlot } from "../api/client";
import {
  StatCard, DetailRow, EmptyState, Alert, PageHeader,
  ProgressBar, Badge, TabBar, LoadingState,
} from "../components/ui";
import { fmtUptime } from "../lib/formatUtils";
import styles from "./Portfolio.module.css";

export default function Portfolio() {
  const qc   = useQueryClient();
  const [mode, setMode] = useState<"paper" | "live">("paper");

  const { data: status, isLoading } = useQuery<PortfolioStatus>({
    queryKey:        ["portfolioStatus"],
    queryFn:         fetchPortfolioStatus,
    refetchInterval: 5_000,
  });

  const startMut = useMutation({
    mutationFn: () => startPortfolio({ mode }),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["portfolioStatus"] }),
  });
  const stopMut = useMutation({
    mutationFn: stopPortfolio,
    onSuccess:  () => qc.invalidateQueries({ queryKey: ["portfolioStatus"] }),
  });

  const running = status?.running ?? false;

  return (
    <div className={styles.page}>
      <PageHeader
        title="Multi-Strategy Portfolio"
        icon="🗂"
        subtitle="Run multiple strategies simultaneously with isolated capital allocations."
        action={
          <div className={styles.controls}>
            {!running && (
              <TabBar
                variant="buttons"
                size="sm"
                tabs={[
                  { value: "paper", label: "📋 Paper" },
                  { value: "live",  label: "⚡ Live" },
                ]}
                active={mode}
                onChange={(v) => setMode(v as "paper" | "live")}
              />
            )}
            {running ? (
              <button className={styles.stopBtn} onClick={() => stopMut.mutate()} disabled={stopMut.isPending}>
                {stopMut.isPending ? "Stopping…" : "⏹ Stop All"}
              </button>
            ) : (
              <button className={styles.startBtn} onClick={() => startMut.mutate()} disabled={startMut.isPending || isLoading}>
                {startMut.isPending ? "Starting…" : "▶ Start Portfolio"}
              </button>
            )}
          </div>
        }
      />

      {startMut.isError && (
        <Alert variant="error" compact>
          {String((startMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? startMut.error)}
        </Alert>
      )}

      {mode === "live" && !running && (
        <Alert variant="warning">
          Live mode will execute real trades on the exchange. Ensure{" "}
          <code>EXCHANGE_API_KEY</code> and <code>EXCHANGE_API_SECRET</code> are set.
        </Alert>
      )}

      {/* Summary bar */}
      {status && (
        <div className={styles.summaryBar}>
          <StatCard label="Slots"   value={`${status.alive_slots} / ${status.total_slots}`} size="sm" />
          <StatCard label="Trades"  value={String(status.total_trades)} size="sm" />
          {status.crashed_slots > 0 && (
            <StatCard label="Crashed" value={String(status.crashed_slots)} color="red" size="sm" />
          )}
          {status.uptime_s != null && (
            <StatCard label="Uptime" value={fmtUptime(status.uptime_s)} size="sm" />
          )}
          <StatCard
            label="Status"
            value={running ? "RUNNING" : "IDLE"}
            color={running ? "green" : "muted"}
            size="sm"
          />
        </div>
      )}

      {/* Slot grid */}
      {isLoading ? (
        <LoadingState message="Loading portfolio status…" />
      ) : !status?.slots?.length ? (
        <EmptyState
          icon="🗂"
          message="No slots configured. Add strategies under portfolio.strategies in config.yaml."
        />
      ) : (
        <div className={styles.slotGrid}>
          {status.slots.map((slot) => <SlotCard key={slot.index} slot={slot} />)}
        </div>
      )}
    </div>
  );
}

function SlotCard({ slot }: { slot: PortfolioSlot }) {
  const statusColor = slot.crashed ? "red" : slot.running ? "green" : "gray";
  const statusLabel = slot.crashed ? "CRASHED" : slot.running ? "RUNNING" : "IDLE";

  return (
    <div className={[styles.slotCard, slot.crashed ? styles.slotCrashed : ""].filter(Boolean).join(" ")}>
      <div className={styles.slotHeader}>
        <Badge variant={statusColor} label={`● ${statusLabel}`} />
        <span className={styles.slotName}>{slot.name}</span>
        <span className={styles.slotMode}>{slot.mode.toUpperCase()}</span>
      </div>

      <div className={styles.slotBody}>
        <DetailRow label="Capital"  value={`${slot.capital_pct}%`} />
        <DetailRow label="Pairs"    value={slot.pairs.join(", ")} />
        <DetailRow label="Trades"   value={String(slot.trade_count)} />
        {slot.uptime_s != null && (
          <DetailRow label="Uptime" value={fmtUptime(slot.uptime_s)} />
        )}
        {slot.started_at && (
          <DetailRow label="Started" value={slot.started_at.substring(0, 19).replace("T", " ")} />
        )}
      </div>

      <ProgressBar
        value={slot.capital_pct}
        color="blue"
        height={4}
      />

      {slot.crashed && slot.error && (
        <Alert variant="error" compact>{slot.error}</Alert>
      )}
    </div>
  );
}
