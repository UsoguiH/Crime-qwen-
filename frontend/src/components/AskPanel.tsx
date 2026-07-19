import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircleQuestion, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { PhotoQuestion, get, post } from "../lib/api";
import { fmtPercent } from "../lib/format";
import { Badge, Button, Card, Spinner } from "./ui";

const SUGGESTIONS = [
  "كم عدد الأدلة المرقّمة الظاهرة؟",
  "هل يوجد سلاح ناري في الصورة؟ وأين؟",
  "صف موضع كل بقعة دم ظاهرة.",
  "ما النصوص أو الأرقام المرئية في الصورة؟",
];

export default function AskPanel({ mediaId, onBoxes }: {
  mediaId: string;
  onBoxes: (boxes: PhotoQuestion["grounded_boxes"], id: string | null) => void;
}) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const { data: history } = useQuery({
    queryKey: ["questions", mediaId],
    queryFn: () => get<PhotoQuestion[]>(`/media/${mediaId}/questions`),
  });
  const ask = useMutation({
    mutationFn: (question: string) =>
      post<PhotoQuestion>(`/media/${mediaId}/ask`, { question_ar: question, thinking: true }),
    onSuccess: (res) => {
      setQ("");
      setActiveId(res.id);
      onBoxes(res.grounded_boxes, res.id);
      void qc.invalidateQueries({ queryKey: ["questions", mediaId] });
    },
  });

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <MessageCircleQuestion size={17} className="text-primary" />
        <h3 className="font-semibold text-sm">اسأل عن الصورة</h3>
      </div>

      <div className="flex gap-2">
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && q.trim() && ask.mutate(q.trim())}
          placeholder="اكتب سؤالك عن محتوى الصورة…"
          className="flex-1 h-11 rounded-md border border-hairline-strong bg-card px-4 text-sm outline-none focus:border-primary" />
        <Button variant="primary" disabled={ask.isPending || !q.trim()}
                onClick={() => ask.mutate(q.trim())}>
          {ask.isPending ? <Spinner /> : <Send size={15} />}
        </Button>
      </div>

      {!history?.length && !ask.isPending && (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => ask.mutate(s)}
                    className="text-xs rounded-full border border-hairline-strong bg-card px-3 py-1.5 text-body hover:bg-canvas-soft cursor-pointer">
              {s}
            </button>
          ))}
        </div>
      )}
      {ask.isPending && (
        <div className="mt-3 text-xs text-muted flex items-center gap-2">
          <Sparkles size={14} className="text-primary" />
          تفكير عميق ومطابقة ذاتية للإجابة… قد يستغرق لحظات
        </div>
      )}

      <div className="mt-4 space-y-3">
        {(history ?? []).map((h) => (
          <button key={h.id}
                  onClick={() => { setActiveId(h.id); onBoxes(h.grounded_boxes, h.id); }}
                  className={`w-full text-start rounded-lg border p-3 transition-colors cursor-pointer ${
                    activeId === h.id ? "border-hairline-strong bg-canvas-soft" : "border-hairline"
                  }`}>
            <div className="text-sm font-semibold flex items-start gap-2">
              <span className="text-primary">س:</span>{h.question_ar}
            </div>
            <div className="text-sm text-body mt-1.5 flex items-start gap-2">
              <span className="text-success">ج:</span>
              <span className="flex-1">{h.answer_ar}</span>
            </div>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              {h.cannot_determine ? (
                <Badge tone="warning">غير محدد من الصورة</Badge>
              ) : (
                <Badge tone={h.confidence >= 0.75 ? "success" : "warning"}>
                  ثقة: {fmtPercent(h.confidence)}
                </Badge>
              )}
              {h.grounded_boxes.length > 0 && (
                <span className="text-[11px] text-muted">
                  انقر لإبراز {h.grounded_boxes.length} موضعاً على الصورة
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
      <p className="mt-3 text-[10px] text-muted">
        الإجابات مستندة إلى ما يُرى في الصورة فقط، وتتطلب تحقق خبير قبل أي استخدام قانوني.
      </p>
    </Card>
  );
}
