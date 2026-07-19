import type { CSSProperties } from "react";
import { Run, Step } from "../lib/api";
import { arDigits } from "../lib/format";

/* The five DesignMD pastel pills — their ONLY permitted use (DESIGN.md §2):
   peach=deep thinking, mint=triage, blue=frame analysis, lavender=annotation,
   gold=done. Pipeline stages map onto them for the progress display. */
const PILL_FOR_STAGE: Record<number, { color: string; label: string }> = {
  0: { color: "var(--color-pill-triage)", label: "التحقق" },
  1: { color: "var(--color-pill-triage)", label: "الإطارات" },
  2: { color: "var(--color-pill-triage)", label: "الفرز" },
  3: { color: "var(--color-pill-read)", label: "تحليل الإطارات" },
  4: { color: "var(--color-pill-thinking)", label: "توحيد الأدلة" },
  5: { color: "var(--color-pill-read)", label: "الجدول الزمني" },
  6: { color: "var(--color-pill-thinking)", label: "مقارنة المصادر" },
  7: { color: "var(--color-pill-thinking)", label: "الصياغة" },
  8: { color: "var(--color-pill-edit)", label: "التعليم" },
  9: { color: "var(--color-pill-done)", label: "التقرير" },
};

/* real progress weights ≈ measured share of wall-clock per stage */
const WEIGHT: Record<number, number> = {
  0: 3, 1: 10, 2: 15, 3: 45, 4: 8, 5: 4, 7: 10, 8: 3, 9: 2,
};

export function overallProgress(steps: Step[]): number {
  const present = steps.filter((s) => WEIGHT[s.stage] !== undefined);
  const total = present.reduce((sum, s) => sum + WEIGHT[s.stage], 0) || 1;
  let done = 0;
  for (const s of present) {
    const w = WEIGHT[s.stage];
    if (["completed", "completed_with_errors", "skipped"].includes(s.status)) {
      done += w;
    } else if (s.status === "running") {
      const frac = s.progress_total > 0
        ? s.progress_current / s.progress_total : 0.15;
      done += w * Math.min(1, frac);
    }
  }
  return Math.min(100, Math.round((done / total) * 100));
}

function pillStyle(step: Step): CSSProperties {
  const pill = PILL_FOR_STAGE[step.stage];
  if (step.status === "completed" || step.status === "completed_with_errors") {
    return { background: pill.color, color: "#26251e", opacity: 0.9 };
  }
  if (step.status === "running") {
    return { background: pill.color, color: "#26251e", outline: "2px solid #26251e22" };
  }
  if (step.status === "failed") {
    return { background: "var(--color-error-soft)", color: "var(--color-error)" };
  }
  if (step.status === "skipped") {
    return { background: "var(--color-strong)", color: "var(--color-muted-soft)" };
  }
  return { background: "var(--color-strong)", color: "var(--color-muted)" };
}

export default function PipelineProgress({ run, compact = false }: {
  run: Run; compact?: boolean;
}) {
  const steps = run.steps ?? [];
  const active = steps.find((s) => s.status === "running");
  const percent = overallProgress(steps);
  const runActive = ["queued", "running"].includes(run.status);
  const barColor = run.status === "failed" ? "var(--color-error)"
    : percent >= 100 ? "var(--color-pill-done)" : "var(--color-primary)";

  return (
    <div>
      {/* the real loading bar */}
      <div className="flex items-center gap-3">
        <div className="h-2.5 flex-1 rounded-full bg-strong overflow-hidden">
          <div className="h-full rounded-full transition-all duration-500"
               style={{ width: `${runActive || percent > 0 ? Math.max(percent, 2) : 0}%`,
                        background: barColor }} />
        </div>
        <span className="text-sm font-semibold w-12 text-end tabular-nums">
          {arDigits(percent)}٪
        </span>
      </div>
      <div className="mt-1 text-xs text-muted min-h-4">
        {active ? (
          <>
            {active.stage_name_ar}
            {active.progress_total > 0 && (
              <> — {arDigits(active.progress_current)} من {arDigits(active.progress_total)}</>
            )}
          </>
        ) : run.status === "completed" ? "اكتمل التحليل"
          : run.status === "queued" ? "في الانتظار…" : null}
      </div>

      {!compact && (
        <div className="mt-3 flex flex-wrap gap-2">
          {steps.map((s) => (
            <span key={s.stage}
                  className="rounded-full px-3 py-1 text-[11px] font-semibold transition-all"
                  style={pillStyle(s)}
                  title={s.error ?? s.stage_name_ar}>
              {PILL_FOR_STAGE[s.stage]?.label ?? s.stage_name_ar}
              {s.status === "running" && s.progress_total > 0 && (
                <span className="mx-1">
                  {arDigits(s.progress_current)}/{arDigits(s.progress_total)}
                </span>
              )}
            </span>
          ))}
        </div>
      )}
      {run.status === "failed" && run.error && (
        <div className="mt-3 text-sm text-error bg-error-soft border border-error/30 rounded-md px-3 py-2">
          {run.error}
        </div>
      )}
    </div>
  );
}
