/**
 * SystemMetricsWidget — compact VPS health card for the Dashboard.
 * Polls GET /api/system/metrics every 30 seconds.
 */
import { useQuery } from "@tanstack/react-query";
import { fetchSystemMetrics } from "../api/client";
import type { SystemMetrics } from "../api/client";
import { SectionHeader, ProgressBar, LoadingState } from "./ui";
import { healthColor } from "../lib/colorUtils";
import { fmtUptime } from "../lib/formatUtils";
import styles from "./SystemMetricsWidget.module.css";

function MetricRow({ label, pct, sub }: { label: string; pct: number; sub: string }) {
  return (
    <div className={styles.metricRow}>
      <div className={styles.metricMeta}>
        <span className={styles.metricLabel}>{label}</span>
        <span className={styles.metricValue} style={{ color: healthColor(pct) }}>
          {pct.toFixed(1)}%
        </span>
      </div>
      <ProgressBar value={pct} color="auto" height={5} />
      <span className={styles.metricSub}>{sub}</span>
    </div>
  );
}

interface Props {
  refetchInterval?: number;
}

export default function SystemMetricsWidget({ refetchInterval = 30_000 }: Props) {
  const { data, isError, isLoading } = useQuery<SystemMetrics>({
    queryKey:        ["systemMetrics"],
    queryFn:         fetchSystemMetrics,
    refetchInterval,
    retry:           2,
  });

  if (isLoading) {
    return (
      <div className={styles.card}>
        <SectionHeader title="System" icon="🖥" compact />
        <LoadingState size="sm" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className={styles.card}>
        <SectionHeader title="System" icon="🖥" compact />
        <p className={styles.unavailable}>
          psutil not available — install it in requirements.txt
        </p>
      </div>
    );
  }

  const ramUsedGb  = (data.ram_used_mb  / 1024).toFixed(1);
  const ramTotalGb = (data.ram_total_mb / 1024).toFixed(1);

  return (
    <div className={styles.card}>
      <SectionHeader
        title="System"
        icon="🖥"
        compact
        action={
          <span className={styles.uptime} title="Process uptime">
            ⏱ {fmtUptime(data.process_uptime_s)}
          </span>
        }
      />

      <MetricRow
        label="CPU"
        pct={data.cpu_pct}
        sub={`${data.process_cpu_pct.toFixed(1)}% this process`}
      />
      <MetricRow
        label="RAM"
        pct={data.ram_pct}
        sub={`${ramUsedGb} / ${ramTotalGb} GB · ${data.process_rss_mb.toFixed(0)} MB RSS`}
      />
      <MetricRow
        label="Disk"
        pct={data.disk.pct}
        sub={`${data.disk.used_gb.toFixed(1)} / ${data.disk.total_gb.toFixed(1)} GB`}
      />

      {data.data_dir_mb != null && (
        <div className={styles.extra}>
          📁 data dir: {data.data_dir_mb.toFixed(1)} MB
          {data.os_uptime_s != null && <> · 🖥 OS up: {fmtUptime(data.os_uptime_s)}</>}
          {" "}· 🔀 {data.process_threads} threads
        </div>
      )}
    </div>
  );
}
