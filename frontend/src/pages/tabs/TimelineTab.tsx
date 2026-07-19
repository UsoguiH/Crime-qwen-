import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import TimelineTrack from "../../components/TimelineTrack";
import { Badge, Button, Card, EmptyState, Spinner, inputCls } from "../../components/ui";
import {
  EntityDetail, Media, Observation, OffsetRow, TimelineEventItem, get, post, put,
} from "../../lib/api";
import { CATEGORY_COLOR } from "../../lib/format";

const METHOD_AR: Record<string, string> = {
  auto_metadata: "آلي من البيانات الوصفية",
  manual: "ضبط يدوي",
  unanchored: "غير مرسوّى",
};

function OffsetsPanel({ runId }: { runId: string }) {
  const qc = useQueryClient();
  const { data: offsets } = useQuery({
    queryKey: ["offsets", runId],
    queryFn: () => get<OffsetRow[]>(`/runs/${runId}/offsets`),
  });
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  if (!offsets || offsets.length < 2) return null;

  const save = async (o: OffsetRow) => {
    setBusy(true);
    try {
      await put(`/runs/${runId}/offsets/${o.media_file_id}`, {
        offset_seconds: Number(edit[o.media_file_id] ?? o.offset_seconds) || 0,
        note_ar: "",
      });
      await post(`/runs/${runId}/timeline/rebuild`);
      await qc.invalidateQueries({ queryKey: ["offsets", runId] });
      await qc.invalidateQueries({ queryKey: ["timeline", runId] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="overflow-x-auto">
      <div className="px-4 py-2.5 border-b border-hairline text-sm font-semibold">
        إزاحات الساعات بين المصادر
      </div>
      <table className="w-full text-xs">
        <tbody>
          {offsets.map((o) => (
            <tr key={o.media_file_id} className="border-b border-hairline-soft">
              <td className="p-2.5">{o.media_label}</td>
              <td className="p-2.5">
                <input dir="ltr" className={inputCls + " h-8 w-28 text-xs latin"}
                       value={edit[o.media_file_id] ?? String(o.offset_seconds)}
                       onChange={(e) => setEdit((s) => ({
                         ...s, [o.media_file_id]: e.target.value }))} />
              </td>
              <td className="p-2.5">
                <Badge tone={o.method === "unanchored" ? "warning" : "neutral"}>
                  {METHOD_AR[o.method] ?? o.method}
                </Badge>
              </td>
              <td className="p-2.5">
                <Button className="h-8 text-xs" disabled={busy}
                        onClick={() => void save(o)}>
                  {busy ? "…" : "حفظ وإعادة البناء"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {offsets.some((o) => o.method === "unanchored") && (
        <div className="px-4 py-2.5 text-xs text-warning bg-warning-soft border-t border-hairline">
          مصادر غير مرسوّة الساعة — أزمنتها نسبية داخل المصدر ولا تصلح للمقارنة
          الدقيقة بين المصادر حتى تُضبط يدوياً.
        </div>
      )}
    </Card>
  );
}

export default function TimelineTab({ runId, media }: {
  runId: string | null; media: Media[];
}) {
  const { data: events, isLoading } = useQuery({
    queryKey: ["timeline", runId],
    queryFn: () => get<TimelineEventItem[]>(`/runs/${runId}/timeline`),
    enabled: !!runId,
  });
  const [selected, setSelected] = useState<TimelineEventItem | null>(null);

  if (!runId) return <EmptyState title="لا تحليل بعد" hint="ابدأ تحليلاً من تبويب النظرة العامة" />;
  if (isLoading) return <Spinner />;
  if (!events?.length) {
    return <EmptyState title="لا أحداث زمنية"
                       hint="تُبنى الأحداث من مشاهدات الأدلة في الفيديو والمصادر المؤرخة" />;
  }

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <TimelineTrack events={events} media={media} onSelect={setSelected} />
      </Card>
      <OffsetsPanel runId={runId} />
      {selected && <EventViewer event={selected} media={media} />}
      <Card className="p-5">
        <h3 className="font-semibold text-sm mb-3">الوقائع الموثقة</h3>
        <ul className="space-y-2 text-sm">
          {events.map((ev, i) => (
            <li key={ev.id ?? i}>
              <button onClick={() => setSelected(ev)}
                      className="text-start hover:text-primary cursor-pointer">
                <span className="inline-block h-2 w-2 rounded-full me-2"
                      style={{ background: CATEGORY_COLOR[ev.category ?? ""] }} />
                {ev.description_ar}
              </button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function EventViewer({ event, media }: { event: TimelineEventItem; media: Media[] }) {
  const m = media.find((x) => x.id === event.media_file_id);
  const { data: entity } = useQuery({
    queryKey: ["entity", event.entity_id],
    queryFn: () => get<EntityDetail>(`/entities/${event.entity_id}`),
  });
  const obs: Observation | undefined = (entity?.observations as Observation[] | undefined)
    ?.find((o) => o.frame_id === event.frame_id)
    ?? (entity?.observations as Observation[] | undefined)?.[0];

  return (
    <Card className="p-5 space-y-3">
      <h3 className="font-semibold text-sm">{event.description_ar}</h3>
      {m?.kind === "video" && event.timestamp_source_s !== null ? (
        <VideoWithBox mediaId={m.id} t={event.timestamp_source_s} box={obs?.bbox ?? null}
                      color={CATEGORY_COLOR[event.category ?? ""]} />
      ) : event.frame_id ? (
        <img
          src={`/api/files/annotated/frame/${event.frame_id}?run_id=${entity?.run_id ?? ""}`}
          onError={(e) => {
            (e.target as HTMLImageElement).src = `/api/files/frame/${event.frame_id}`;
          }}
          className="max-h-[420px] rounded-lg border border-hairline mx-auto" alt="" />
      ) : null}
    </Card>
  );
}

function VideoWithBox({ mediaId, t, box, color }: {
  mediaId: string; t: number; box: [number, number, number, number] | null;
  color?: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [ratio, setRatio] = useState(16 / 9);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const seek = () => { v.currentTime = Math.max(0, t); };
    if (v.readyState >= 1) seek();
    else v.addEventListener("loadedmetadata", seek, { once: true });
  }, [t, mediaId]);

  return (
    <div className="relative mx-auto max-w-3xl" dir="ltr"
         style={{ aspectRatio: String(ratio) }}>
      <video ref={ref} src={`/api/files/original/${mediaId}`} controls
             className="w-full h-full rounded-lg border border-hairline bg-black"
             onLoadedMetadata={(e) => {
               const v = e.target as HTMLVideoElement;
               if (v.videoWidth) setRatio(v.videoWidth / v.videoHeight);
             }} />
      {box && (
        <div className="absolute border-2 rounded-sm pointer-events-none"
             style={{
               left: `${box[0] * 100}%`, top: `${box[1] * 100}%`,
               width: `${(box[2] - box[0]) * 100}%`,
               height: `${(box[3] - box[1]) * 100}%`,
               borderColor: color ?? "#f54e00",
             }} />
      )}
    </div>
  );
}
