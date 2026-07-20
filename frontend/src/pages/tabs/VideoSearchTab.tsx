import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Play, RefreshCcw, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import PhotoCanvas from "../../components/PhotoCanvas";
import {
  Badge, Button, Card, ConfidenceMeter, Dialog, EmptyState, Spinner,
  StatusBadge, inputCls,
} from "../../components/ui";
import {
  ApiError, Media, VideoClip, VideoIndexInfo, VideoSearchRow, get, post,
} from "../../lib/api";
import { arDigits, fmtDateTime, fmtSeconds } from "../../lib/format";

const RUNNING = ["queued", "translating", "retrieving", "verifying"];

function IndexChip({ m }: { m: Media }) {
  const qc = useQueryClient();
  const { data: idx } = useQuery({
    queryKey: ["video-index", m.id],
    queryFn: () => get<VideoIndexInfo>(`/media/${m.id}/video-index`),
    refetchInterval: (q) =>
      ["queued", "building"].includes(q.state.data?.status ?? "") ? 2000 : false,
  });
  const build = async () => {
    await post(`/media/${m.id}/video-index`);
    await qc.invalidateQueries({ queryKey: ["video-index", m.id] });
  };
  if (!idx) return <Spinner />;
  return (
    <span className="flex items-center gap-2 flex-wrap">
      {idx.status === "none" ? (
        <Button className="h-8 px-3 text-xs" onClick={() => void build()}>
          بناء الفهرس
        </Button>
      ) : (
        <StatusBadge status={idx.status} />
      )}
      {idx.status === "building" && (idx.progress_total ?? 0) > 0 && (
        <span className="text-[11px] text-muted">
          {arDigits(idx.progress_current ?? 0)}/{arDigits(idx.progress_total ?? 0)}
        </span>
      )}
      {idx.status === "ready" && (
        <span className="text-[11px] text-muted">
          {arDigits(idx.frames_indexed ?? 0)} إطار مفهرس
        </span>
      )}
      {idx.status === "failed" && (
        <>
          <span className="text-[11px] text-error truncate max-w-56" title={idx.error ?? ""}>
            {idx.error}
          </span>
          <Button className="h-8 px-3 text-xs" onClick={() => void build()}>
            <RefreshCcw size={13} /> إعادة المحاولة
          </Button>
        </>
      )}
    </span>
  );
}

function ThumbWithBox({ clip }: { clip: VideoClip }) {
  return (
    <div className="relative shrink-0 w-44" dir="ltr">
      <img src={`/api/files/data/${clip.thumb_path}`} alt=""
           className="w-44 rounded-md border border-hairline bg-canvas-soft" />
      {clip.bbox && (
        <span className="absolute border-2 rounded-[3px] pointer-events-none"
              style={{
                borderColor: "var(--color-cat-weapons)",
                left: `${clip.bbox[0] * 100}%`,
                top: `${clip.bbox[1] * 100}%`,
                width: `${(clip.bbox[2] - clip.bbox[0]) * 100}%`,
                height: `${(clip.bbox[3] - clip.bbox[1]) * 100}%`,
              }} />
      )}
    </div>
  );
}

function ClipCard({ clip, onOpen }: { clip: VideoClip; onOpen: () => void }) {
  return (
    <Card className="p-4 flex gap-4 items-start">
      <button onClick={onOpen} className="cursor-pointer relative group" title="تشغيل المقطع">
        <ThumbWithBox clip={clip} />
        <span className="absolute inset-0 grid place-items-center opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="h-10 w-10 rounded-full bg-primary text-on-primary grid place-items-center">
            <Play size={18} />
          </span>
        </span>
      </button>
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge status={clip.status} />
          {clip.label_ar && <span className="text-sm font-semibold">{clip.label_ar}</span>}
          <span className="text-xs text-muted flex items-center gap-1">
            <Clock3 size={12} />
            {fmtSeconds(clip.ts_in)} – {fmtSeconds(clip.ts_out)}
          </span>
          <span className="text-[11px] text-muted truncate">{clip.media_label}</span>
        </div>
        <ConfidenceMeter value={clip.confidence} />
        {clip.description_ar && (
          <p className="text-sm text-body leading-relaxed">{clip.description_ar}</p>
        )}
      </div>
    </Card>
  );
}

function PlayerDialog({ clip, onClose }: { clip: VideoClip | null; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clip) return;
    const seek = () => {
      v.currentTime = clip.ts_in;
      void v.play().catch(() => undefined);
    };
    if (v.readyState >= 1) seek();
    else v.addEventListener("loadedmetadata", seek, { once: true });
    return () => v.removeEventListener("loadedmetadata", seek);
  }, [clip]);
  return (
    <Dialog open={clip !== null} onClose={onClose} wide
            title={clip ? `${clip.label_ar || "المقطع"} — ${fmtSeconds(clip.ts_in)}` : ""}>
      {clip && (
        <div className="space-y-4">
          <video ref={videoRef} controls className="w-full rounded-lg bg-black"
                 src={`/api/files/original/${clip.media_file_id}`} />
          <div className="grid sm:grid-cols-[auto_1fr] gap-4 items-start">
            <PhotoCanvas
              src={`/api/files/data/${clip.thumb_path}`}
              boxes={clip.bbox ? [{
                id: "hit", bbox: clip.bbox, label: clip.label_ar || "الهدف",
                color: "var(--color-cat-weapons)", dashed: true, alwaysLabel: true,
              }] : []}
              focus={null} onHover={() => undefined} onSelect={() => undefined} />
            <div className="text-sm space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={clip.status} />
                <ConfidenceMeter value={clip.confidence} />
              </div>
              <p className="text-body leading-relaxed">{clip.description_ar}</p>
              <p className="text-xs text-muted">
                اللقطة الحاسمة عند {fmtSeconds(clip.ts_best)} — الإطار أعلاه مع
                الصندوق المحيط كما رآه النموذج.
              </p>
            </div>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function SearchProgress({ search }: { search: VideoSearchRow }) {
  const pct = search.status === "verifying" && search.progress_total > 0
    ? Math.round((search.progress_current / search.progress_total) * 100)
    : null;
  return (
    <Card className="p-5 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <Spinner />
        <StatusBadge status={search.status} />
        {search.sensitive && <Badge tone="warning">تحقق مزدوج (استعلام حساس)</Badge>}
        <span className="text-sm text-muted truncate">«{search.query_ar}»</span>
      </div>
      {pct !== null && (
        <div className="h-1.5 rounded-full bg-strong overflow-hidden">
          <div className="h-full rounded-full bg-primary transition-all"
               style={{ width: `${pct}%` }} />
        </div>
      )}
      {search.status === "verifying" && (
        <p className="text-xs text-muted">
          التحقق من المرشح {arDigits(search.progress_current)} من{" "}
          {arDigits(search.progress_total)}…
        </p>
      )}
    </Card>
  );
}

function Results({ search }: { search: VideoSearchRow }) {
  const [playing, setPlaying] = useState<VideoClip | null>(null);
  const r = search.results;
  if (!r) return null;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap text-xs text-muted">
        <span>«{search.query_ar}»</span>
        {search.sensitive && <Badge tone="warning">تحقق مزدوج</Badge>}
        <span>{arDigits(r.stats.candidates)} مرشح</span>
        <span className="text-success">{arDigits(r.stats.confirmed)} مؤكد</span>
        <span className="text-warning">{arDigits(r.stats.uncertain)} غير مؤكد</span>
        <span>{arDigits(r.stats.rejected)} مرفوض</span>
        <span>({arDigits(Math.round(search.latency_ms / 1000))} ثانية)</span>
      </div>

      {r.clips.length === 0 ? (
        <EmptyState title="لا نتائج مؤكدة عند هذه التغطية"
                    hint="جرّب صياغة أخرى — أو راجع المرفوضات أدناه" />
      ) : (
        <div className="space-y-3">
          {r.clips.map((c, i) => (
            <ClipCard key={i} clip={c} onOpen={() => setPlaying(c)} />
          ))}
        </div>
      )}

      {r.rejected.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted hover:text-ink">
            مرشحات رفضها النموذج بعد الفحص ({arDigits(r.rejected.length)})
          </summary>
          <div className="mt-3 space-y-3">
            {r.rejected.map((c, i) => (
              <ClipCard key={i} clip={c} onOpen={() => setPlaying(c)} />
            ))}
          </div>
        </details>
      )}

      {r.coverage.skipped_media.length > 0 && (
        <p className="text-xs text-warning">
          مقاطع لم تُشمل: {r.coverage.skipped_media.map((s) =>
            `${s.label} (${s.reason === "no_index" ? "بلا فهرس"
              : s.reason === "building" || s.reason === "queued" ? "الفهرسة جارية"
              : s.reason === "embedder_mismatch" ? "فهرس بنموذج مختلف — أعد البناء"
              : "فشل الفهرس"})`).join("، ")}
        </p>
      )}
      <p className="text-xs text-muted bg-canvas-soft border border-hairline-soft rounded-md p-3 leading-relaxed">
        {r.coverage.statement_ar}
      </p>
      <PlayerDialog clip={playing} onClose={() => setPlaying(null)} />
    </div>
  );
}

export default function VideoSearchTab({ caseId, media }: {
  caseId: string; media: Media[];
}) {
  const qc = useQueryClient();
  const videos = media.filter((m) => m.kind === "video" && !m.excluded);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const { data: searches } = useQuery({
    queryKey: ["video-searches", caseId],
    queryFn: () => get<VideoSearchRow[]>(`/cases/${caseId}/video-searches`),
  });
  const shownId = selectedId ?? searches?.[0]?.id ?? null;
  const { data: search } = useQuery({
    queryKey: ["video-search", shownId],
    queryFn: () => get<VideoSearchRow>(`/video-searches/${shownId}`),
    enabled: !!shownId,
    refetchInterval: (q) =>
      RUNNING.includes(q.state.data?.status ?? "") ? 1500 : false,
  });
  useEffect(() => {
    if (search && !RUNNING.includes(search.status)) {
      void qc.invalidateQueries({ queryKey: ["video-searches", caseId] });
    }
  }, [search?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    const q = query.trim();
    if (!q) return;
    setBusy(true);
    setError("");
    try {
      const created = await post<VideoSearchRow>(
        `/cases/${caseId}/video-search`, { query_ar: q });
      setSelectedId(created.id);
      setQuery("");
      await qc.invalidateQueries({ queryKey: ["video-searches", caseId] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "تعذر بدء البحث");
    } finally {
      setBusy(false);
    }
  };

  if (videos.length === 0) {
    return <EmptyState title="لا مقاطع فيديو في القضية"
                       hint="ارفع فيديو من تبويب «الوسائط» ليُفهرس تلقائياً ويصبح قابلاً للبحث" />;
  }

  return (
    <div className="space-y-5">
      <Card className="p-5 space-y-4">
        <h2 className="font-semibold flex items-center gap-2">
          <Search size={16} className="text-primary" /> البحث في الفيديو بلغة طبيعية
        </h2>
        <p className="text-xs text-muted">
          مثال: «متى يظهر شخص يحمل سلاحاً؟» — يسترجع النظام اللقطات المرشحة ثم
          يتحقق منها النموذج ويعرضها لقرارك. البحث لا يحسم؛ القرار للمحقق.
        </p>
        <div className="flex gap-2 flex-wrap">
          <input value={query} onChange={(e) => setQuery(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && void submit()}
                 placeholder="اكتب ما تبحث عنه في التسجيلات…"
                 className={inputCls + " flex-1 min-w-64"} />
          <Button variant="primary" disabled={busy || !query.trim()}
                  onClick={() => void submit()}>
            <Search size={15} /> بحث
          </Button>
        </div>
        {error && <p className="text-sm text-error">{error}</p>}
        <div className="space-y-2 pt-2 border-t border-hairline-soft">
          {videos.map((m) => (
            <div key={m.id} className="flex items-center gap-3 flex-wrap text-sm">
              <span className="truncate max-w-64 latin" dir="ltr">
                {m.source_label_ar || m.original_filename}
              </span>
              {m.duration_s && (
                <span className="text-xs text-muted">{fmtSeconds(m.duration_s)}</span>
              )}
              <IndexChip m={m} />
            </div>
          ))}
        </div>
      </Card>

      {search && RUNNING.includes(search.status) && <SearchProgress search={search} />}
      {search && search.status === "failed" && (
        <Card className="p-5 text-sm text-error">
          تعذر إتمام البحث: {search.error ?? "خطأ غير معروف"}
        </Card>
      )}
      {search && search.status === "done" && <Results search={search} />}

      {(searches ?? []).length > 1 && (
        <Card className="p-5 space-y-2">
          <h3 className="font-semibold text-sm">عمليات بحث سابقة</h3>
          {(searches ?? []).map((s) => (
            <button key={s.id} onClick={() => setSelectedId(s.id)}
                    className={`w-full text-start flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors cursor-pointer ${
                      s.id === shownId ? "bg-canvas-soft" : "hover:bg-canvas-soft"
                    }`}>
              <span className="flex-1 truncate">«{s.query_ar}»</span>
              <StatusBadge status={s.status} />
              {s.results && (
                <span className="text-xs text-muted">
                  {arDigits(s.results.stats.confirmed + s.results.stats.uncertain)} نتيجة
                </span>
              )}
              <span className="text-[11px] text-muted">{fmtDateTime(s.created_at)}</span>
            </button>
          ))}
        </Card>
      )}
    </div>
  );
}
