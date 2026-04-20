// ── Primitives ──────────────────────────────────────────────────────────────
export { default as Spinner }       from "./Spinner";
export { default as Badge }         from "./Badge";
export type { BadgeProps, BadgeColor } from "./Badge";
export { default as Button }        from "./Button";
export { default as ProgressBar }   from "./ProgressBar";
export type { ProgressBarProps, ProgressColor } from "./ProgressBar";

// ── Layout ───────────────────────────────────────────────────────────────────
export { default as Card }          from "./Card";
export { default as PageHeader }    from "./PageHeader";
export type { PageHeaderProps }     from "./PageHeader";
export { default as SectionHeader } from "./SectionHeader";
export type { SectionHeaderProps }  from "./SectionHeader";

// ── Data display ─────────────────────────────────────────────────────────────
export { default as StatCard }      from "./StatCard";
export type { StatCardProps, StatColor } from "./StatCard";
export { default as DetailRow }     from "./DetailRow";
export type { DetailRowProps }      from "./DetailRow";
export { default as DataTable }     from "./DataTable";
export type { ColumnDef }           from "./DataTable";

// ── Feedback ─────────────────────────────────────────────────────────────────
export { default as Alert }         from "./Alert";
export type { AlertProps, AlertVariant } from "./Alert";
export { default as EmptyState }    from "./EmptyState";
export type { EmptyStateProps }     from "./EmptyState";
export { default as LoadingState }  from "./LoadingState";
export type { LoadingStateProps }   from "./LoadingState";
export { ToastContainer, useToast } from "./Toast";
export type { ToastItem, ToastKind } from "./Toast";

// ── Navigation ───────────────────────────────────────────────────────────────
export { default as TabBar }        from "./TabBar";
export type { TabBarProps, TabItem } from "./TabBar";

// ── Overlays ─────────────────────────────────────────────────────────────────
export { default as Modal }         from "./Modal";
export { default as Tooltip }       from "./Tooltip";

// ── Form controls ────────────────────────────────────────────────────────────
export { default as Input }         from "./Input";
export type { InputProps }          from "./Input";
export { default as Select }        from "./Select";
export type { SelectProps, SelectOption } from "./Select";
export { default as Textarea }      from "./Textarea";
