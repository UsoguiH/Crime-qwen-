import { CloudUpload } from "lucide-react";
import { useRef, useState } from "react";
import { Media, postForm } from "../lib/api";
import { HashChip, Spinner } from "./ui";

interface Item {
  name: string;
  status: "uploading" | "done" | "error" | "duplicate";
  sha?: string;
  error?: string;
}

export default function UploadZone({ caseId, onUploaded }: {
  caseId: string; onUploaded: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [dragOver, setDragOver] = useState(false);

  const uploadFiles = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      setItems((prev) => [...prev, { name: file.name, status: "uploading" }]);
      try {
        const form = new FormData();
        form.append("file", file);
        const media = await postForm<Media>(`/cases/${caseId}/media`, form);
        setItems((prev) => prev.map((it) =>
          it.name === file.name
            ? { ...it, status: media.duplicate ? "duplicate" : "done",
                sha: media.content_sha256 }
            : it));
        onUploaded();
      } catch (e: any) {
        setItems((prev) => prev.map((it) =>
          it.name === file.name
            ? { ...it, status: "error", error: e.message }
            : it));
      }
    }
  };

  return (
    <div>
      <button
        className={`w-full rounded-lg border-2 border-dashed p-8 text-center transition-colors cursor-pointer ${
          dragOver ? "border-primary bg-canvas-soft" : "border-hairline-strong bg-card hover:bg-canvas-soft"
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void uploadFiles(e.dataTransfer.files);
        }}
      >
        <CloudUpload className="mx-auto mb-2 text-muted" size={28} />
        <div className="text-sm text-body">اسحب الصور أو مقاطع الفيديو هنا، أو انقر للاختيار</div>
        <div className="text-xs text-muted mt-1">
          تُحسب بصمة SHA-256 أثناء الرفع، وتُحفظ الأصول للقراءة فقط ضمن سلسلة الحيازة
        </div>
      </button>
      <input
        ref={inputRef} type="file" multiple hidden
        accept="image/*,video/*"
        onChange={(e) => e.target.files && void uploadFiles(e.target.files)}
      />
      {items.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {items.map((it, i) => (
            <li key={i} className="flex items-center gap-3 text-sm">
              <span className="truncate max-w-56 latin" dir="ltr">{it.name}</span>
              {it.status === "uploading" && <Spinner />}
              {it.status === "done" && it.sha && <HashChip value={it.sha} />}
              {it.status === "duplicate" && (
                <span className="text-xs text-warning">مكرر — محفوظ سابقاً</span>
              )}
              {it.status === "error" && (
                <span className="text-xs text-error">{it.error}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
