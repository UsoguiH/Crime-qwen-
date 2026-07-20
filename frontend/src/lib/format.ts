const AR_DIGITS = "٠١٢٣٤٥٦٧٨٩";

export function arDigits(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => AR_DIGITS[Number(d)]);
}

export function fmtPercent(fraction: number): string {
  return arDigits(Math.round(fraction * 100)) + "٪";
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const text = h
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
  return arDigits(text);
}

export function fmtBytes(n: number): string {
  if (n >= 1 << 30) return arDigits((n / (1 << 30)).toFixed(1)) + " ج.ب";
  if (n >= 1 << 20) return arDigits((n / (1 << 20)).toFixed(1)) + " م.ب";
  if (n >= 1 << 10) return arDigits(Math.round(n / (1 << 10))) + " ك.ب";
  return arDigits(n) + " بايت";
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return arDigits(
    d.toLocaleDateString("ar-SA-u-nu-latn", {
      year: "numeric", month: "long", day: "numeric",
    }),
  );
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return arDigits(
    d.toLocaleString("ar-SA-u-nu-latn", {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    }),
  );
}

export const CATEGORY_AR: Record<string, string> = {
  weapons: "أسلحة",
  biological: "أدلة بيولوجية",
  impressions: "انطباعات وآثار",
  documents_devices: "وثائق وأجهزة",
  scene_markers: "علامات المشهد",
  trace: "مواد أثرية",
  human_presence: "وجود بشري",
};

export const CATEGORY_COLOR: Record<string, string> = {
  weapons: "var(--color-cat-weapons)",
  biological: "var(--color-cat-biological)",
  impressions: "var(--color-cat-impressions)",
  documents_devices: "var(--color-cat-documents)",
  scene_markers: "var(--color-cat-markers)",
  trace: "var(--color-cat-trace)",
  human_presence: "var(--color-cat-human)",
};

export const STATUS_AR: Record<string, string> = {
  new: "جديدة",
  analyzing: "قيد التحليل",
  complete: "مكتملة",
  queued: "في الانتظار",
  running: "قيد التنفيذ",
  paused: "متوقف مؤقتاً",
  failed: "متعثر",
  completed: "مكتمل",
  completed_with_errors: "مكتمل مع ملاحظات",
  cancelled: "أُلغي",
  pending: "بانتظار المراجعة",
  confirmed: "مؤكد",
  rejected: "مرفوض",
  edited: "معدّل ومعتمد",
  uncertain: "غير مؤكد — للمراجعة",
  ready: "جاهز",
  building: "قيد الفهرسة",
  translating: "تهيئة الاستعلام",
  retrieving: "استرجاع المرشحات",
  verifying: "التحقق بالنموذج",
  done: "اكتمل",
};

export const ROLE_AR: Record<string, string> = {
  investigator: "محقق",
  reviewer: "مراجع",
  admin: "مشرف",
};
