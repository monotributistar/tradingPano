import { useState, useMemo } from "react";
import styles from "./DataTable.module.css";

export interface ColumnDef<T> {
  key: string;
  header: string;
  /** Custom cell renderer. Receives the row object. */
  render?: (row: T) => React.ReactNode;
  /** If true, column is sortable. data[key] must be string | number. */
  sortable?: boolean;
  /** Optional min-width passed as inline style */
  minWidth?: number;
}

interface DataTableProps<T extends Record<string, unknown>> {
  columns: ColumnDef<T>[];
  data: T[];
  /** Show skeleton rows while loading */
  loading?: boolean;
  /** Rows to show in skeleton loading state */
  skeletonRows?: number;
  /** Message shown when data is empty */
  emptyLabel?: string;
  /** Called when a row is clicked */
  onRowClick?: (row: T) => void;
  /** Rows per page; omit to disable pagination */
  pageSize?: number;
  /** Optional additional className for the outer wrapper */
  className?: string;
}

type SortDir = "asc" | "desc";

export default function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  loading = false,
  skeletonRows = 6,
  emptyLabel = "No data",
  onRowClick,
  pageSize,
  className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(0);

  function handleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(0);
  }

  const sorted = useMemo(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const av = a[sortKey] as string | number;
      const bv = b[sortKey] as string | number;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  const totalPages = pageSize ? Math.ceil(sorted.length / pageSize) : 1;
  const visible = pageSize ? sorted.slice(page * pageSize, (page + 1) * pageSize) : sorted;

  return (
    <div className={[styles.wrap, className].filter(Boolean).join(" ")}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={[
                  col.sortable ? styles.sortable : "",
                  sortKey === col.key ? styles.sortActive : "",
                ].filter(Boolean).join(" ")}
                style={col.minWidth ? { minWidth: col.minWidth } : undefined}
                onClick={col.sortable ? () => handleSort(col.key) : undefined}
              >
                {col.header}
                {col.sortable && (
                  <span className={styles.sortIcon}>
                    {sortKey === col.key ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: skeletonRows }).map((_, i) => (
              <tr key={i} className={styles.skeletonRow}>
                {columns.map((col) => (
                  <td key={col.key}>
                    <div
                      className={styles.skeletonCell}
                      style={{ width: `${55 + ((i * 17 + col.key.length * 7) % 35)}%` }}
                    />
                  </td>
                ))}
              </tr>
            ))
          ) : visible.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className={styles.empty}>
                {emptyLabel}
              </td>
            </tr>
          ) : (
            visible.map((row, i) => (
              <tr
                key={i}
                className={onRowClick ? styles.clickable : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key}>
                    {col.render ? col.render(row) : (row[col.key] as React.ReactNode)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {pageSize && !loading && sorted.length > 0 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            ‹
          </button>
          <span className={styles.pageInfo}>
            {page + 1} / {totalPages}
          </span>
          <button
            className={styles.pageBtn}
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
          >
            ›
          </button>
        </div>
      )}
    </div>
  );
}
