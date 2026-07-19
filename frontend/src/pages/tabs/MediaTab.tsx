import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ScanSearch } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import UploadZone from "../../components/UploadZone";
import { Badge, Card, HashChip, Spinner, inputCls } from "../../components/ui";
import { Media, Run, get, patch } from "../../lib/api";
import { arDigits, fmtBytes, fmtDateTime, fmtSeconds } from "../../lib/format";

function PhotoChip({ m }: { m: Media }) {
  const { data } = useQuery({
    queryKey: ["photo-analyses", m.id],
    queryFn: () => get<Array<Run & { detections_count?: number }>>(
      `/media/${m.id}/analyses`),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((a) => ["queued", "running"].includes(a.status))
        ? 3000 : false,
  });
  const latest = data?.[0];
  return (
    <Link to={`/cases/${m.case_id}/photos/${m.id}`}
          className="inline-flex items-center gap-1.5 rounded-md border border-hairline-strong bg-card px-3 h-9 text-xs hover:bg-canvas-soft transition-colors">
      <ScanSearch size={14} className="text-primary" />
      {latest === undefined && data === undefined ? <Spinner /> :
        !latest ? "تحليل فردي" :
        ["queued", "running"].includes(latest.status) ? (
          <span className="text-warning">قيد التحليل…</span>
        ) : latest.status === "failed" ? (
          <span className="text-error">متعثر — افتح للتفاصيل</span>
        ) : (
          <span>
            عرض التحليل
            <span className="text-muted"> ({arDigits(latest.detections_count ?? 0)} أدلة)</span>
          </span>
        )}
    </Link>
  );
}

const SOURCE_TYPES: Record<string, string> = {
  cctv: "كاميرا مراقبة", bodycam: "كاميرا جسدية", handheld: "تصوير يدوي",
  photo: "صورة فوتوغرافية", other: "مصدر آخر",
};

function MediaRow({ m }: { m: Media }) {
  const qc = useQueryClient();
  const [label, setLabel] = useState(m.source_label_ar);
  const save = async (fields: Partial<Media>) => {
    await patch(`/media/${m.id}`, fields);
    await qc.invalidateQueries({ queryKey: ["media", m.case_id] });
  };
  return (
    <Card className={`p-4 flex gap-4 ${m.excluded ? "opacity-50" : ""}`}>
      <img src={`/api/files/thumb/${m.id}`} alt=""
           className="h-20 w-28 object-cover rounded-md border border-hairline bg-canvas-soft"
           onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold truncate latin" dir="ltr">
            {m.original_filename}
          </span>
          <Badge>{m.kind === "video" ? "فيديو" : "صورة"}</Badge>
          {m.duration_s && <span className="text-xs text-muted">{fmtSeconds(m.duration_s)}</span>}
          <span className="text-xs text-muted">{fmtBytes(m.size_bytes)}</span>
          <HashChip value={m.content_sha256} />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {m.kind === "image" && !m.excluded && <PhotoChip m={m} />}
          <input value={label} placeholder="تسمية المصدر (مثال: كاميرا المدخل الشمالي)"
                 onChange={(e) => setLabel(e.target.value)}
                 onBlur={() => label !== m.source_label_ar && void save({ source_label_ar: label } as any)}
                 className={inputCls + " h-9 max-w-72 text-xs"} />
          <select value={m.source_type}
                  onChange={(e) => void save({ source_type: e.target.value } as any)}
                  className={inputCls + " h-9 w-auto text-xs"}>
            {Object.entries(SOURCE_TYPES).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          <label className="text-xs text-body flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={!m.excluded}
                   onChange={(e) => void save({ excluded: !e.target.checked } as any)} />
            ضمن التحليل
          </label>
        </div>
        <div className="text-[11px] text-muted flex flex-wrap gap-x-4">
          <span>رُفع: {fmtDateTime(m.uploaded_at)}</span>
          {m.metadata_creation_time && (
            <span>وقت الإنشاء (بيانات وصفية): {fmtDateTime(m.metadata_creation_time)}</span>
          )}
          {m.exif?.gps && (
            <span className="font-mono">
              GPS: {m.exif.gps.lat}, {m.exif.gps.lon}
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function MediaTab({ caseId, media }: { caseId: string; media: Media[] }) {
  const qc = useQueryClient();
  return (
    <div className="space-y-4">
      <UploadZone caseId={caseId}
                  onUploaded={() => void qc.invalidateQueries({ queryKey: ["media", caseId] })} />
      <div className="space-y-3">
        {media.map((m) => <MediaRow key={m.id} m={m} />)}
      </div>
    </div>
  );
}
