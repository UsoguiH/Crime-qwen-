import { useState } from "react";
import { Entity } from "../lib/api";
import { fmtSeconds } from "../lib/format";
import {
  Badge, CategoryBadge, ConfidenceMeter, Dialog, SeqBadge, StatusBadge,
} from "./ui";

function ReviewFlags({ e }: { e: Entity }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      {e.review_status !== "pending" ? (
        <StatusBadge status={e.review_status} />
      ) : e.needs_human_review ? (
        <Badge tone="warning">يتطلب مراجعة بشرية</Badge>
      ) : null}
    </span>
  );
}

export function BeforeAfterSlider({ entityId }: { entityId: string }) {
  const [pos, setPos] = useState(50);
  return (
    <div className="select-none">
      <div className="relative overflow-hidden rounded-lg border border-hairline" dir="ltr">
        <img src={`/api/files/annotated/entity/${entityId}?variant=after`}
             className="block w-full" alt="بعد" />
        <div className="absolute inset-0 overflow-hidden" style={{ width: `${pos}%` }}>
          <img src={`/api/files/annotated/entity/${entityId}?variant=before`}
               className="block w-full h-full object-cover" alt="قبل" />
        </div>
        <div className="absolute inset-y-0" style={{ left: `${pos}%` }}>
          <div className="w-0.5 h-full bg-white" />
        </div>
        <span className="absolute top-2 left-2 text-[10px] bg-white/85 text-ink rounded-full px-2 py-0.5">قبل</span>
        <span className="absolute top-2 right-2 text-[10px] bg-white/85 text-ink rounded-full px-2 py-0.5">بعد</span>
      </div>
      <input type="range" min={0} max={100} value={pos} dir="ltr"
             onChange={(e) => setPos(Number(e.target.value))}
             className="w-full mt-2 accent-[--color-primary]" />
    </div>
  );
}

export default function EvidenceCard({ e }: { e: Entity }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"annotated" | "original">("annotated");
  return (
    <>
      <button className="card p-0 overflow-hidden text-start hover:border-hairline-strong transition-colors cursor-pointer"
              onClick={() => setOpen(true)}>
        {e.has_crop ? (
          <img src={`/api/files/annotated/entity/${e.id}`} alt={e.canonical_name_ar}
               className="w-full h-40 object-cover bg-canvas-soft" loading="lazy" />
        ) : (
          <div className="w-full h-40 grid place-items-center bg-canvas-soft text-muted text-sm">
            بلا صورة
          </div>
        )}
        <div className="p-4 space-y-2">
          <div className="flex items-center gap-2">
            <SeqBadge seq={e.entity_seq} category={e.category} />
            <div className="font-semibold text-sm leading-snug">{e.canonical_name_ar}</div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <CategoryBadge category={e.category} />
            <ReviewFlags e={e} />
          </div>
          <ConfidenceMeter value={e.confidence_max} />
        </div>
      </button>

      <Dialog open={open} onClose={() => setOpen(false)} wide
              title={<span className="flex items-center gap-2">
                <SeqBadge seq={e.entity_seq} category={e.category} />
                {e.label_ar} — {e.canonical_name_ar}
              </span>}>
        <div className="grid md:grid-cols-2 gap-6">
          <div>
            {e.has_before_after ? (
              <BeforeAfterSlider entityId={e.id} />
            ) : e.best_frame_id ? (
              <>
                <div className="flex gap-2 mb-2">
                  <button
                    className={`text-xs rounded-full px-3 py-1 cursor-pointer ${view === "annotated" ? "bg-ink text-canvas" : "bg-strong text-body"}`}
                    onClick={() => setView("annotated")}>معلّمة</button>
                  <button
                    className={`text-xs rounded-full px-3 py-1 cursor-pointer ${view === "original" ? "bg-ink text-canvas" : "bg-strong text-body"}`}
                    onClick={() => setView("original")}>الأصل</button>
                </div>
                <img
                  src={view === "annotated"
                    ? `/api/files/annotated/frame/${e.best_frame_id}?run_id=${e.run_id}`
                    : `/api/files/frame/${e.best_frame_id}`}
                  onError={(ev) => {
                    (ev.target as HTMLImageElement).src =
                      `/api/files/annotated/entity/${e.id}`;
                  }}
                  className="w-full rounded-lg border border-hairline" alt="" />
                <div className="text-[11px] text-muted mt-1">
                  الأصل لا يُمس أبداً — التعليم يتم على نسخة
                </div>
              </>
            ) : null}
          </div>
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-1.5">
              <CategoryBadge category={e.category} />
              <ReviewFlags e={e} />
            </div>
            <ConfidenceMeter value={e.confidence_max} />
            <p><span className="font-semibold">الوصف: </span>{e.description_ar}</p>
            <p><span className="font-semibold">الدلالة الجنائية المحتملة: </span>
              {e.forensic_significance_ar}</p>
            <p><span className="font-semibold">توصية التعامل: </span>
              {e.handling_recommendation_ar}</p>
            {e.merge_rationale_ar && (
              <p className="text-muted text-xs">
                <span className="font-semibold">أساس التوحيد: </span>
                {e.merge_rationale_ar}</p>
            )}
            {e.review_note_ar && (
              <p className="text-xs bg-canvas-soft border border-hairline rounded-md p-2">
                <span className="font-semibold">ملاحظة المراجع: </span>
                {e.review_note_ar}</p>
            )}
            <div className="text-xs text-muted">
              المصادر: {e.sources.join("، ") || "—"} · المشاهدات: {e.observations}
            </div>
          </div>
        </div>
      </Dialog>
    </>
  );
}

export { fmtSeconds };
