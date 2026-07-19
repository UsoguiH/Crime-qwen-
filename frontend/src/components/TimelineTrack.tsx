import { Media, TimelineEventItem } from "../lib/api";
import { CATEGORY_COLOR, fmtSeconds } from "../lib/format";

/* RTL-mirrored global time axis: time flows leftward (right = 0). */
const MARKER: Record<string, string> = {
  first_seen: "◆", moved: "●", disappeared: "◇", reappeared: "◈", last_seen: "■",
};

export default function TimelineTrack({ events, media, onSelect }: {
  events: TimelineEventItem[];
  media: Media[];
  onSelect: (ev: TimelineEventItem) => void;
}) {
  const stamped = events.filter((e) =>
    e.timestamp_global_s !== null || e.timestamp_source_s !== null);
  const ts = (e: TimelineEventItem) =>
    e.timestamp_global_s ?? e.timestamp_source_s ?? 0;
  const max = Math.max(10, ...stamped.map(ts));
  const lanes = media.filter((m) =>
    events.some((e) => e.media_file_id === m.id));

  if (stamped.length === 0) {
    return <div className="text-muted text-sm py-8 text-center">
      لا أحداث زمنية بعد — الأحداث تُبنى من الفيديو والمصادر المرسوّة زمنياً
    </div>;
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-between text-[11px] text-muted px-1">
        <span>{fmtSeconds(max)}</span>
        <span>٠:٠٠</span>
      </div>
      {lanes.map((m) => {
        const laneEvents = stamped.filter((e) => e.media_file_id === m.id);
        return (
          <div key={m.id}>
            <div className="text-xs text-body mb-1">
              {m.source_label_ar || m.original_filename}
            </div>
            <div className="relative h-10 rounded-md bg-canvas-soft border border-hairline">
              {laneEvents.map((e, i) => (
                <button
                  key={e.id ?? i}
                  title={e.description_ar}
                  onClick={() => onSelect(e)}
                  className="absolute top-1/2 -translate-y-1/2 translate-x-1/2 text-sm cursor-pointer hover:scale-125 transition-transform"
                  style={{
                    right: `${(ts(e) / max) * 96 + 2}%`,
                    color: CATEGORY_COLOR[e.category ?? ""] ?? "var(--color-ink)",
                  }}
                >
                  {MARKER[e.event_type] ?? "•"}
                </button>
              ))}
            </div>
          </div>
        );
      })}
      <div className="flex flex-wrap gap-3 text-[11px] text-muted pt-1">
        <span>◆ أول ظهور</span><span>● تغيّر الموضع</span>
        <span>◇ اختفاء</span><span>◈ معاودة ظهور</span><span>■ آخر رصد</span>
      </div>
    </div>
  );
}
