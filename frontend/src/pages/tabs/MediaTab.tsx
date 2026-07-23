import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, ScanSearch, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import UploadZone from "../../components/UploadZone";
import { Badge, Card, HashChip, Spinner, inputCls } from "../../components/ui";
import { Media, Run, del, get, patch } from "../../lib/api";
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
          className="btn-pop inline-flex items-center gap-2 rounded-md bg-primary text-on-primary px-5 h-10 text-xs font-medium hover:bg-primary-active">
      <ScanSearch size={16} />
      {latest === undefined && data === undefined ? <Spinner /> :
        !latest ? "تحليل فردي" :
        ["queued", "running"].includes(latest.status) ? (
          <span>قيد التحليل…</span>
        ) : latest.status === "failed" ? (
          <span>متعثر — افتح للتفاصيل</span>
        ) : (
          <span>
            عرض التحليل ({arDigits(latest.detections_count ?? 0)} أدلة)
          </span>
        )}
    </Link>
  );
}

function MediaRow({ m }: { m: Media }) {
  const qc = useQueryClient();
  const [label, setLabel] = useState(m.source_label_ar);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(m.original_filename);
  const [removing, setRemoving] = useState(false);
  const save = async (fields: Partial<Media>) => {
    await patch(`/media/${m.id}`, fields);
    await qc.invalidateQueries({ queryKey: ["media", m.case_id] });
  };
  const saveName = async () => {
    setEditing(false);
    const clean = name.trim();
    if (clean && clean !== m.original_filename) {
      await save({ original_filename: clean } as any);
    } else {
      setName(m.original_filename);
    }
  };
  const remove = async () => {
    if (!window.confirm(`حذف «${m.original_filename}» وتحليلاتها من القضية؟`)) return;
    setRemoving(true);
    try {
      await del(`/media/${m.id}`);
      await qc.invalidateQueries({ queryKey: ["media", m.case_id] });
    } finally {
      setRemoving(false);
    }
  };
  return (
    <Card className={`p-4 flex gap-4 ${m.excluded ? "opacity-50" : ""} ${removing ? "opacity-40 pointer-events-none" : ""}`}>
      <img src={`/api/files/thumb/${m.id}`} alt=""
           className="h-20 w-28 object-cover rounded-md border border-hairline bg-canvas-soft"
           onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          {editing ? (
            <span className="inline-flex items-center gap-1">
              <input value={name} autoFocus dir="auto"
                     onChange={(e) => setName(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") void saveName();
                                         if (e.key === "Escape") { setEditing(false); setName(m.original_filename); } }}
                     onBlur={() => void saveName()}
                     className={inputCls + " h-8 w-64 text-xs"} />
              <button onMouseDown={(e) => e.preventDefault()}
                      onClick={() => void saveName()} title="حفظ الاسم"
                      className="text-success cursor-pointer p-1"><Check size={14} /></button>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 min-w-0 group">
              <span className="text-sm font-semibold truncate latin" dir="ltr">
                {m.original_filename}
              </span>
              <button onClick={() => setEditing(true)} title="إعادة تسمية"
                      className="text-muted hover:text-ink cursor-pointer p-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <Pencil size={13} />
              </button>
            </span>
          )}
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
          <label className="text-xs text-body flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={!m.excluded}
                   onChange={(e) => void save({ excluded: !e.target.checked } as any)} />
            ضمن التحليل
          </label>
          <button onClick={() => void remove()} title="حذف الصورة من القضية"
                  className="ms-auto text-muted hover:text-error cursor-pointer p-1.5 transition-colors">
            <Trash2 size={15} />
          </button>
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
      <div data-anim="hero">
        <UploadZone caseId={caseId}
                    onUploaded={() => void qc.invalidateQueries({ queryKey: ["media", caseId] })} />
      </div>
      <div className="anim-list space-y-3">
        {media.map((m) => <MediaRow key={m.id} m={m} />)}
      </div>
    </div>
  );
}
