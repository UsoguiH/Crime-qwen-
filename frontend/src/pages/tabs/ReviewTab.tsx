import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import {
  Badge, Button, Card, CategoryBadge, ConfidenceMeter, EmptyState, SeqBadge,
  Spinner, inputCls,
} from "../../components/ui";
import { Entity, get, post } from "../../lib/api";
import { CATEGORY_AR, arDigits } from "../../lib/format";
import { useSession } from "../../lib/session";

function ReviewItem({ e, runId }: { e: Entity; runId: string }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState({
    canonical_name_ar: e.canonical_name_ar,
    category: e.category,
    description_ar: e.description_ar,
  });
  const mutation = useMutation({
    mutationFn: (body: { action: string; edits?: unknown; note_ar: string }) =>
      post(`/entities/${e.id}/review`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["review-queue", runId] });
      void qc.invalidateQueries({ queryKey: ["entities", runId] });
      void qc.invalidateQueries({ queryKey: ["review-count", runId] });
    },
  });

  return (
    <Card className="p-5">
      <div className="grid md:grid-cols-[220px_1fr] gap-5">
        <div>
          {e.has_crop ? (
            <img src={`/api/files/annotated/entity/${e.id}`} alt=""
                 className="w-full rounded-lg border border-hairline" />
          ) : (
            <div className="h-32 grid place-items-center bg-canvas-soft rounded-lg text-muted text-xs">
              بلا صورة
            </div>
          )}
          <div className="mt-2"><ConfidenceMeter value={e.confidence_max} /></div>
        </div>
        <div className="space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <SeqBadge seq={e.entity_seq} category={e.category} />
            <span className="font-semibold">{e.canonical_name_ar}</span>
            <CategoryBadge category={e.category} />
            {e.category === "human_presence" && (
              <Badge tone="warning">ملاحظات وضعية فقط — لا تحديد هوية</Badge>
            )}
          </div>
          <p className="text-sm text-body">{e.description_ar}</p>
          {editing && (
            <div className="space-y-2 border border-hairline rounded-lg p-3 bg-canvas-soft">
              <input className={inputCls} value={edits.canonical_name_ar}
                     onChange={(ev) => setEdits({ ...edits, canonical_name_ar: ev.target.value })} />
              <select className={inputCls} value={edits.category}
                      onChange={(ev) => setEdits({ ...edits, category: ev.target.value })}>
                {Object.entries(CATEGORY_AR).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
              <textarea rows={3} value={edits.description_ar}
                        onChange={(ev) => setEdits({ ...edits, description_ar: ev.target.value })}
                        className="w-full rounded-md border border-hairline-strong bg-card px-3 py-2 text-sm" />
            </div>
          )}
          <input placeholder="ملاحظة المراجع (اختياري)…" value={note}
                 onChange={(ev) => setNote(ev.target.value)} className={inputCls} />
          <div className="flex gap-2 flex-wrap">
            {editing ? (
              <Button variant="primary" disabled={mutation.isPending}
                      onClick={() => mutation.mutate({ action: "edit", edits, note_ar: note })}>
                <Check size={15} /> اعتماد التعديل
              </Button>
            ) : (
              <>
                <Button disabled={mutation.isPending}
                        onClick={() => mutation.mutate({ action: "confirm", note_ar: note })}>
                  <Check size={15} className="text-success" /> تأكيد
                </Button>
                <Button variant="danger" disabled={mutation.isPending}
                        onClick={() => mutation.mutate({ action: "reject", note_ar: note })}>
                  <X size={15} /> رفض
                </Button>
              </>
            )}
            <Button variant="text" onClick={() => setEditing((v) => !v)}>
              <Pencil size={14} /> {editing ? "إلغاء التعديل" : "تعديل"}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function ReviewTab({ runId }: { runId: string | null }) {
  const { user } = useSession();
  const canReview = user && ["reviewer", "admin"].includes(user.role);
  const { data: queue, isLoading } = useQuery({
    queryKey: ["review-queue", runId],
    queryFn: () => get<Entity[]>(`/runs/${runId}/review-queue`),
    enabled: !!runId && !!canReview,
  });

  if (!runId) return <EmptyState title="لا تحليل بعد" />;
  if (!canReview) {
    return <EmptyState title="المراجعة من صلاحية المراجع أو المشرف"
                       hint="سجّل الدخول بحساب «المراجع الفني» لاعتماد الأدلة أو رفضها" />;
  }
  if (isLoading) return <Spinner />;
  if (!queue?.length) {
    return <EmptyState title="لا عناصر بانتظار المراجعة"
                       hint="كل ما يقل عن حد الثقة أو يخص الوجود البشري يصل إلى هنا تلقائياً" />;
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {arDigits(queue.length)} عنصراً بانتظار المراجعة — الأدنى ثقةً أولاً.
        قرارك يُسجَّل باسمك في سجل التدقيق ويظهر في التقرير.
      </p>
      {queue.map((e) => <ReviewItem key={e.id} e={e} runId={runId} />)}
    </div>
  );
}
