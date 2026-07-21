import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Play, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AskPanel from "../components/AskPanel";
import PhotoCanvas, { CanvasBox } from "../components/PhotoCanvas";
import PipelineProgress from "../components/PipelineProgress";
import {
  Badge, Button, Card, CategoryBadge, ConfidenceMeter, EmptyState, SeqBadge,
  Spinner,
} from "../components/ui";
import { Media, PhotoQuestion, Run, get, post } from "../lib/api";
import { CATEGORY_COLOR, arDigits, fmtDateTime } from "../lib/format";
import { useRunEvents } from "../lib/sse";

interface PhotoRun extends Run { detections_count?: number }
interface Det {
  id: string; name_ar: string; category: string;
  bbox: [number, number, number, number]; confidence: number;
  needs_human_review: boolean; description_ar: string;
  location_description_ar: string; visible_text_ar: string;
}

export default function PhotoAnalysis() {
  const { caseId = "", mediaId = "" } = useParams();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(true);
  const [tab, setTab] = useState<"evidence" | "ask">("evidence");
  const [answerBoxes, setAnswerBoxes] = useState<PhotoQuestion["grounded_boxes"]>([]);

  const { data: media } = useQuery({
    queryKey: ["media-one", mediaId],
    queryFn: () => get<Media>(`/media/${mediaId}`),
  });
  const { data: analyses, isLoading } = useQuery({
    queryKey: ["photo-analyses", mediaId],
    queryFn: () => get<PhotoRun[]>(`/media/${mediaId}/analyses`),
  });
  const current: PhotoRun | undefined =
    analyses?.find((a) => a.id === runId) ?? analyses?.[0];
  const active = !!current && ["queued", "running"].includes(current.status);
  useRunEvents(current?.id ?? null, active, (ev) => {
    if (ev.type === "run_status" || ev.type === "snapshot") {
      void qc.invalidateQueries({ queryKey: ["photo-analyses", mediaId] });
      void qc.invalidateQueries({ queryKey: ["detections", current?.id] });
      return;
    }
    if (ev.type === "step") {
      qc.setQueryData(["photo-analyses", mediaId], (old: PhotoRun[] | undefined) =>
        old?.map((a) => {
          if (a.id !== (ev.run_id as string)) return a;
          const steps = (a.steps ?? []).map((s) =>
            s.stage === ev.stage ? { ...s, ...(ev as any) } : s);
          return { ...a, steps };
        }));
    }
  });
  const { data: detections } = useQuery({
    queryKey: ["detections", current?.id],
    queryFn: () => get<Det[]>(`/runs/${current!.id}/detections?media_id=${mediaId}`),
    enabled: !!current && current.status.startsWith("completed"),
  });

  const start = async () => {
    setBusy(true);
    try {
      const run = await post<PhotoRun>(`/media/${mediaId}/analyze`, { thinking });
      setRunId(run.id);
      await qc.invalidateQueries({ queryKey: ["photo-analyses", mediaId] });
    } finally {
      setBusy(false);
    }
  };

  const dets = useMemo(() => detections ?? [], [detections]);
  const src = `/api/files/original/${mediaId}`;

  const boxes: CanvasBox[] = useMemo(() => {
    if (tab === "ask") {
      return answerBoxes.map((b, i) => ({
        id: `ans-${i}`, bbox: b.bbox, color: "#f54e00",
        label: b.label_ar, dashed: true, alwaysLabel: true,
      }));
    }
    return dets.map((d, i) => ({
      id: d.id, bbox: d.bbox, index: i + 1,
      color: CATEGORY_COLOR[d.category] ?? "#26251e", label: d.name_ar,
    }));
  }, [tab, dets, answerBoxes]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <Link to={`/cases/${caseId}?tab=media`}
                className="text-sm text-body hover:text-ink inline-flex items-center gap-1">
            <ArrowRight size={14} /> عودة إلى الوسائط
          </Link>
          <h1 data-anim="title" className="text-2xl font-normal mt-1">تحليل الصورة الفردي</h1>
          <div className="text-xs text-muted latin" dir="ltr">
            {media?.original_filename}
          </div>
        </div>
        <div data-anim="rise" className="flex items-center gap-3 flex-wrap">
          <label className="text-sm text-body flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={thinking}
                   onChange={(e) => setThinking(e.target.checked)} />
            تفكير عميق (أدق — موصى به)
          </label>
          <Button variant="primary" disabled={busy || active}
                  onClick={() => void start()}>
            {analyses?.length ? <><RotateCcw size={15} /> إعادة التحليل</>
              : <><Play size={15} /> تحليل هذه الصورة</>}
          </Button>
        </div>
      </div>

      {active && current && (
        <Card className="p-5">
          <PipelineProgress run={current} compact />
          <div className="mt-2 text-[11px] text-muted">
            يشمل: الكشف عن العناصر ثم تحديد مواضعها بدقة (تأطير مستقل لكل عنصر).
          </div>
        </Card>
      )}

      {isLoading ? <Spinner /> : !current ? (
        <EmptyState title="لم تُحلَّل هذه الصورة بعد"
                    hint="ابدأ التحليل الفردي، أو اسأل سؤالاً مباشراً عن الصورة أدناه" />
      ) : (
        <div className="grid lg:grid-cols-[1.6fr_1fr] gap-5 items-start">
          <Card data-anim="hero" className="p-3 lg:sticky lg:top-4">
            <div className="grid place-items-center">
              <PhotoCanvas src={src} boxes={boxes}
                           focus={selected ?? hovered}
                           onHover={setHovered}
                           onSelect={setSelected} />
            </div>
            <div className="mt-2 text-[11px] text-muted text-center">
              مرّر أو انقر على دليل — في الصورة أو في البطاقات — لإبرازه وحده.
              {tab === "ask" && answerBoxes.length > 0 &&
                " الصناديق المتقطّعة تُبرز مواضع إجابة السؤال."}
              {current.status.startsWith("completed") &&
                ` اكتمل: ${fmtDateTime(current.finished_at)}`}
            </div>
          </Card>

          <div className="space-y-3">
            <div className="flex gap-1 border-b border-hairline items-center">
              <button onClick={() => setTab("evidence")}
                      className={`px-4 py-2 text-sm border-b-2 -mb-px cursor-pointer ${
                        tab === "evidence" ? "border-primary font-semibold" : "border-transparent text-body"}`}>
                الأدلة ({arDigits(dets.length)})
              </button>
              <button onClick={() => setTab("ask")}
                      className={`px-4 py-2 text-sm border-b-2 -mb-px cursor-pointer ${
                        tab === "ask" ? "border-primary font-semibold" : "border-transparent text-body"}`}>
                اسأل عن الصورة
              </button>
              {tab === "evidence" && (analyses?.length ?? 0) > 1 && (
                <select
                  className="ms-auto mb-1 h-8 rounded-md border border-hairline-strong bg-card px-2 text-xs"
                  value={current.id} onChange={(e) => setRunId(e.target.value)}>
                  {analyses!.map((a) => (
                    <option key={a.id} value={a.id}>
                      تحليل رقم {arDigits(a.run_number)} — {fmtDateTime(a.started_at)}
                      {" "}({arDigits(a.detections_count ?? 0)} أدلة)
                    </option>
                  ))}
                </select>
              )}
            </div>

            {tab === "ask" ? (
              <AskPanel mediaId={mediaId}
                        onBoxes={(b) => { setAnswerBoxes(b); setSelected(null); }} />
            ) : (
              <>
                {current.status.startsWith("completed") && dets.length === 0 && (
                  <EmptyState title="لم يُرصد دليل ظاهر"
                              hint="جرّب إعادة التحليل مع التفكير العميق، أو اسأل سؤالاً مباشراً" />
                )}
                <div className="anim-list grid gap-3 sm:grid-cols-2">
                  {dets.map((d, i) => (
                  <Card key={d.id}
                        onClick={() => { setSelected(selected === d.id ? null : d.id);
                                         setTab("evidence"); }}
                        onMouseEnter={() => setHovered(d.id)}
                        onMouseLeave={() => setHovered(null)}
                        className={`p-3 cursor-pointer transition-colors h-full flex flex-col ${
                          (selected ?? hovered) === d.id
                            ? "border-hairline-strong bg-canvas-soft" : ""}`}>
                    <div className="flex items-start gap-2">
                      <SeqBadge seq={i + 1} category={d.category} />
                      <span className="font-semibold text-[13px] leading-snug line-clamp-2 flex-1">
                        {d.name_ar}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 flex-wrap mt-2">
                      <CategoryBadge category={d.category} />
                      {d.needs_human_review && (
                        <Badge tone="warning">مراجعة بشرية</Badge>
                      )}
                    </div>
                    <div className="mt-2"><ConfidenceMeter value={d.confidence} /></div>
                    <p className="text-xs text-body mt-2 line-clamp-3">{d.description_ar}</p>
                    <div className="mt-auto pt-2 space-y-0.5">
                      {d.visible_text_ar && (
                        <p className="text-[11px] text-muted line-clamp-1">
                          نص ظاهر: {d.visible_text_ar}
                        </p>
                      )}
                      {d.location_description_ar && (
                        <p className="text-[11px] text-muted line-clamp-2">
                          الموقع: {d.location_description_ar}
                        </p>
                      )}
                    </div>
                  </Card>
                ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
