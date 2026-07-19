import { useLayoutEffect, useRef, useState } from "react";
import { arDigits } from "../lib/format";

export interface CanvasBox {
  id: string;
  bbox: [number, number, number, number]; // normalized 0..1
  color: string;
  label: string;
  index?: number;       // numbered chip (evidence)
  dashed?: boolean;     // answer-grounded boxes
  alwaysLabel?: boolean; // show the text label even without hover (Q&A boxes)
}

/** Focus-mode overlay: quiet by default (thin outlines + tiny number chips,
 *  no text). Hovering or selecting a box — or its card — shows ONLY that box
 *  with its label; every other box disappears until focus clears. */
export default function PhotoCanvas({ src, boxes, focus, onHover, onSelect }: {
  src: string;
  boxes: CanvasBox[];
  focus: string | null;              // selected ?? hovered (owned by parent)
  onHover: (id: string | null) => void;
  onSelect: (id: string | null) => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [rect, setRect] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const measure = () => {
      const img = imgRef.current;
      if (img) setRect({ w: img.clientWidth, h: img.clientHeight });
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (imgRef.current) ro.observe(imgRef.current);
    return () => ro.disconnect();
  }, [src]);

  return (
    <div className="relative inline-block max-w-full" dir="ltr"
         onMouseLeave={() => onHover(null)}>
      <img ref={imgRef} src={src} alt=""
           className="block max-w-full rounded-lg cursor-pointer"
           onClick={() => onSelect(null)}
           onLoad={() => imgRef.current &&
             setRect({ w: imgRef.current.clientWidth, h: imgRef.current.clientHeight })} />
      {rect.w > 0 && boxes.map((b) => {
        const [x1, y1, x2, y2] = b.bbox;
        const left = x1 * rect.w, top = y1 * rect.h;
        const w = (x2 - x1) * rect.w, h = (y2 - y1) * rect.h;
        const isFocus = focus === b.id;
        const hidden = focus !== null && !isFocus;
        const labelBelow = top < 24;
        const labelLeft = left > rect.w - 90;
        return (
          <div key={b.id} className="transition-opacity duration-150"
               style={{ opacity: hidden ? 0 : 1,
                        pointerEvents: hidden ? "none" : "auto" }}>
            <button
              onMouseEnter={() => onHover(b.id)}
              onMouseLeave={() => onHover(null)}
              onClick={(e) => { e.stopPropagation(); onSelect(isFocus ? null : b.id); }}
              className="absolute cursor-pointer"
              style={{
                left, top, width: w, height: h,
                border: `${isFocus ? 3 : 2}px ${b.dashed ? "dashed" : "solid"} ${b.color}`,
                background: isFocus ? b.color + "26" : "transparent",
                borderRadius: 3,
                boxShadow: isFocus ? `0 0 0 2px ${b.color}55` : "none",
              }} />
            {/* tiny number chip — the only default decoration */}
            {b.index !== undefined && !isFocus && (
              <span className="absolute grid place-items-center rounded-full text-[9px] font-bold text-white pointer-events-none"
                    style={{ width: 16, height: 16, background: b.color,
                             left: Math.max(0, left - 6), top: Math.max(0, top - 6) }}>
                {arDigits(b.index)}
              </span>
            )}
            {/* label: focused box, or always-on labels (Q&A answers) when idle */}
            {(isFocus || (b.alwaysLabel && focus === null)) && (
              <span
                className="absolute text-[11px] font-semibold text-white px-2 py-0.5 rounded pointer-events-none whitespace-nowrap z-20"
                style={{
                  background: b.color,
                  left: labelLeft ? undefined : left,
                  right: labelLeft ? rect.w - (x2 * rect.w) : undefined,
                  top: labelBelow ? top + h + 3 : Math.max(0, top - 21),
                }}>
                {b.index !== undefined ? `${arDigits(b.index)}· ` : ""}{b.label}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
