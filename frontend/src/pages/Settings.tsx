import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Spinner, inputCls } from "../components/ui";
import { get, put } from "../lib/api";
import { arDigits } from "../lib/format";
import { useSession } from "../lib/session";

interface SettingsView {
  model_mode: string; model_provider: string;
  model_name_fast: string; model_name_thinking: string;
  openrouter_data_collection: string; openrouter_zdr: boolean;
  report_pdf_variant: string;
  effective: {
    confidence_review_threshold: number; thinking_policy: string;
    face_blur_default: boolean; max_frames_per_video: number;
  };
}

export default function Settings() {
  const { user } = useSession();
  const isAdmin = user?.role === "admin";
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => get<SettingsView>("/settings"),
  });
  const { data: health } = useQuery({
    queryKey: ["models-health"],
    queryFn: () => get<{ ok: boolean; mode: string; model?: string; error?: string }>(
      "/models/health"),
  });
  const save = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      put("/settings", { key, value }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  if (isLoading || !data) return <Spinner />;

  return (
    <div className="max-w-3xl space-y-6">
      <h1 data-anim="title" className="text-3xl font-normal">الإعدادات</h1>

      <Card data-anim="hero" className="p-6 space-y-3">
        <h2 className="font-semibold">النموذج</h2>
        <div className="grid sm:grid-cols-2 gap-3 text-sm">
          <div><span className="text-muted">الوضع: </span>
            <Badge tone={data.model_mode === "mock" ? "warning" : "success"}>
              {data.model_mode === "mock" ? "محاكاة (بدون نموذج فعلي)" :
               data.model_mode === "local" ? "محلي معزول (vLLM)" : "سحابي (API)"}
            </Badge>
          </div>
          <div><span className="text-muted">المزود: </span>{data.model_provider}</div>
          <div className="font-mono text-xs truncate" title={data.model_name_fast}>
            {data.model_name_fast}</div>
          <div className="font-mono text-xs truncate" title={data.model_name_thinking}>
            {data.model_name_thinking}</div>
        </div>
        {data.model_mode === "api" && (
          <div className="text-xs bg-warning-soft text-warning border border-warning/30 rounded-md p-3">
            تنبيه سيادة البيانات: الوضع السحابي يرسل صور المسرح إلى مزود خارجي.
            توجيه الخصوصية الحالي: data_collection={data.openrouter_data_collection}
            {data.openrouter_zdr ? " · ZDR مفعل" : ""}.
            للقضايا الحقيقية استخدم الوضع المحلي المعزول.
          </div>
        )}
        <div className="text-sm flex items-center gap-2">
          <span className="text-muted">فحص الاتصال: </span>
          {health ? (
            health.ok
              ? <Badge tone="success">متصل ({health.model ?? health.mode})</Badge>
              : <Badge tone="error">{health.error ?? "غير متصل"}</Badge>
          ) : <Spinner />}
        </div>
      </Card>

      <Card data-anim="hero" className="p-6 space-y-4">
        <h2 className="font-semibold">
          معايير التحليل {!isAdmin && <span className="text-xs text-muted">(التعديل للمشرف)</span>}
        </h2>
        <div className="grid sm:grid-cols-2 gap-4 text-sm">
          <label className="block">
            <div className="text-body mb-1">
              حد المراجعة البشرية: {arDigits(Math.round(
                data.effective.confidence_review_threshold * 100))}٪
            </div>
            <input type="range" min={50} max={95} step={5} dir="ltr"
                   disabled={!isAdmin}
                   defaultValue={Math.round(data.effective.confidence_review_threshold * 100)}
                   onMouseUp={(e) => isAdmin && save.mutate({
                     key: "confidence_review_threshold",
                     value: Number((e.target as HTMLInputElement).value) / 100,
                   })}
                   className="w-full accent-[--color-primary]" />
          </label>
          <label className="block">
            <div className="text-body mb-1">سياسة التفكير العميق الافتراضية</div>
            <select disabled={!isAdmin} className={inputCls}
                    value={data.effective.thinking_policy}
                    onChange={(e) => save.mutate({ key: "thinking_policy", value: e.target.value })}>
              <option value="auto">تلقائي (حسب تعقيد الإطار)</option>
              <option value="always">دائماً</option>
              <option value="never">أبداً</option>
            </select>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" disabled={!isAdmin}
                   checked={data.effective.face_blur_default}
                   onChange={(e) => save.mutate({ key: "face_blur_default", value: e.target.checked })} />
            تمويه الوجود البشري افتراضياً في النسخ المعلمة
          </label>
          <label className="block">
            <div className="text-body mb-1">
              أقصى إطارات لكل فيديو: {arDigits(data.effective.max_frames_per_video)}
            </div>
            <input type="number" dir="ltr" disabled={!isAdmin}
                   defaultValue={data.effective.max_frames_per_video}
                   onBlur={(e) => isAdmin && save.mutate({
                     key: "max_frames_per_video", value: Number(e.target.value) || 240,
                   })}
                   className={inputCls + " latin"} />
          </label>
        </div>
        {save.isSuccess && <div className="text-xs text-success">حُفظ الإعداد وسُجّل في التدقيق.</div>}
      </Card>

      <Card data-anim="hero" className="p-6 text-xs text-muted space-y-1.5">
        <div>تنسيق تصدير PDF: <span className="font-mono">{data.report_pdf_variant}</span> (أرشفة قضائية)</div>
        <div>الملفات الأصلية محفوظة للقراءة فقط، وكل التعليم يتم على نسخ.</div>
        <div>سجل التدقيق مسلسل البصمات — أي تعديل لاحق على قيوده يُكشف عند التحقق.</div>
      </Card>
    </div>
  );
}
