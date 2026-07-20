import { X } from "lucide-react";
import {
  useEffect,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { arDigits, CATEGORY_AR, CATEGORY_COLOR, fmtPercent, STATUS_AR } from "../lib/format";

export function Button({
  variant = "secondary", className = "", ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "text" | "danger";
}) {
  const base =
    "inline-flex items-center gap-2 rounded-md px-4 h-10 text-sm font-medium " +
    "transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer";
  const styles = {
    primary: "bg-primary text-on-primary hover:bg-primary-active",
    secondary: "bg-card text-ink border border-hairline-strong hover:bg-canvas-soft",
    text: "text-ink hover:text-primary px-2",
    danger: "bg-card text-error border border-error/40 hover:bg-error-soft",
  }[variant];
  return <button className={`${base} ${styles} ${className}`} {...props} />;
}

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`} {...props} />;
}

export function Badge({ tone = "neutral", children }: {
  tone?: "neutral" | "success" | "error" | "warning" | "primary";
  children: ReactNode;
}) {
  const styles = {
    neutral: "bg-strong text-ink",
    success: "bg-success-soft text-success border border-success/40",
    error: "bg-error-soft text-error border border-error/40",
    warning: "bg-warning-soft text-warning border border-warning/40",
    primary: "bg-primary text-on-primary",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${styles}`}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "complete" || status === "completed" || status === "confirmed" ||
    status === "ready" || status === "done"
      ? "success"
      : status === "failed" || status === "rejected" || status === "cancelled"
        ? "error"
        : status === "analyzing" || status === "running" || status === "paused" ||
            status === "pending" || status === "completed_with_errors" ||
            status === "uncertain" || status === "building" ||
            status === "translating" || status === "retrieving" ||
            status === "verifying"
          ? "warning"
          : "neutral";
  return <Badge tone={tone as any}>{STATUS_AR[status] ?? status}</Badge>;
}

export function CategoryBadge({ category }: { category: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold text-white"
      style={{ background: CATEGORY_COLOR[category] ?? "var(--color-ink)" }}
    >
      {CATEGORY_AR[category] ?? category}
    </span>
  );
}

export function HashChip({ value, short = 16 }: { value: string; short?: number }) {
  return (
    <button
      title="نسخ البصمة"
      onClick={() => navigator.clipboard?.writeText(value)}
      className="font-mono text-[11px] bg-strong text-body rounded-full px-2.5 py-0.5 hover:text-ink cursor-copy"
    >
      {value.slice(0, short)}…
    </button>
  );
}

export function ConfidenceMeter({ value }: { value: number }) {
  const low = value < 0.75;
  return (
    <div className="flex items-center gap-2" title="درجة ثقة النموذج — ليست احتمالاً إحصائياً">
      <div className="h-1.5 w-24 rounded-full bg-strong overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.round(value * 100)}%`,
            background: low ? "var(--color-warning)" : "var(--color-success)",
          }}
        />
      </div>
      <span className={`text-xs ${low ? "text-warning" : "text-body"}`}>
        {fmtPercent(value)}
      </span>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="text-center py-16 text-muted">
      <div className="text-lg text-body">{title}</div>
      {hint && <div className="text-sm mt-1">{hint}</div>}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-hairline-strong border-t-primary" />
  );
}

export function Dialog({ open, onClose, title, children, wide = false }: {
  open: boolean; onClose: () => void; title: ReactNode;
  children: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: "#26251e66" }} onClick={onClose}>
      <div
        className={`card w-full ${wide ? "max-w-5xl" : "max-w-2xl"} max-h-[88vh] overflow-y-auto p-6`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button onClick={onClose} className="text-muted hover:text-ink cursor-pointer">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="text-sm text-body mb-1">{label}</div>
      {children}
    </label>
  );
}

export const inputCls =
  "w-full h-11 rounded-md border border-hairline-strong bg-card px-4 text-sm " +
  "focus:border-primary outline-none";

export function SeqBadge({ seq, category }: { seq: number; category: string }) {
  return (
    <span
      className="inline-flex h-7 w-7 items-center justify-center rounded-full text-white text-sm font-semibold border-2 border-white"
      style={{ background: CATEGORY_COLOR[category] ?? "var(--color-ink)" }}
    >
      {arDigits(seq)}
    </span>
  );
}
