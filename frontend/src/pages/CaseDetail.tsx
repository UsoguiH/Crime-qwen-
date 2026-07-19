import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import PipelineProgress from "../components/PipelineProgress";
import AuditTable from "../components/AuditTable";
import {
  Badge, Button, Card, Spinner, StatusBadge, inputCls,
} from "../components/ui";
import {
  ApiError, Case, Media, ModelCallsSummary, Run, get, post,
} from "../lib/api";
import { arDigits, fmtDate } from "../lib/format";
import { useRunEvents } from "../lib/sse";
import EvidenceTab from "./tabs/EvidenceTab";
import MediaTab from "./tabs/MediaTab";
import ReportTab from "./tabs/ReportTab";
import ReviewTab from "./tabs/ReviewTab";
import TimelineTab from "./tabs/TimelineTab";

const TABS = [
  ["overview", "نظرة عامة"], ["media", "الوسائط"], ["timeline", "الجدول الزمني"],
  ["evidence", "الأدلة"], ["review", "المراجعة"],
  ["report", "التقرير"], ["audit", "التدقيق"],
] as const;

export default function CaseDetail() {
  const { caseId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const qc = useQueryClient();

  const { data: caseData, isLoading } = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => get<Case>(`/cases/${caseId}`),
  });
  const { data: media } = useQuery({
    queryKey: ["media", caseId],
    queryFn: () => get<Media[]>(`/cases/${caseId}/media`),
  });
  const latestRunId = caseData?.runs?.[0]?.id ?? null;
  const { data: run } = useQuery({
    queryKey: ["run", latestRunId],
    queryFn: () => get<Run>(`/runs/${latestRunId}`),
    enabled: !!latestRunId,
  });
  const runActive = !!run && ["queued", "running"].includes(run.status);
  useRunEvents(latestRunId, runActive);

  if (isLoading || !caseData) {
    return <div className="py-20 text-center"><Spinner /></div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-normal">{caseData.title_ar}</h1>
            <StatusBadge status={caseData.status} />
          </div>
          <div className="text-sm text-muted mt-1 flex flex-wrap gap-x-4">
            <span className="font-mono text-xs bg-strong rounded-full px-2.5 py-0.5">
              {caseData.case_number}
            </span>
            {caseData.location_ar && <span>{caseData.location_ar}</span>}
            {caseData.incident_date_hijri && (
              <span>{caseData.incident_date_hijri} — {fmtDate(caseData.incident_date_gregorian)}</span>
            )}
          </div>
        </div>
      </div>

      {/* mobile-only tab strip — on lg+ the sidebar owns case navigation */}
      <nav className="flex gap-1 border-b border-hairline overflow-x-auto lg:hidden">
        {TABS.map(([key, label]) => (
          <button key={key}
                  onClick={() => setParams({ tab: key })}
                  className={`px-4 py-2.5 text-sm whitespace-nowrap cursor-pointer border-b-2 -mb-px transition-colors ${
                    tab === key
                      ? "border-primary text-ink font-semibold"
                      : "border-transparent text-body hover:text-ink"
                  }`}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <Overview caseData={caseData} run={run ?? null} mediaCount={(media ?? []).length}
                  onChanged={() => {
                    void qc.invalidateQueries({ queryKey: ["case", caseId] });
                    void qc.invalidateQueries({ queryKey: ["run"] });
                  }} />
      )}
      {tab === "media" && <MediaTab caseId={caseId} media={media ?? []} />}
      {tab === "timeline" && <TimelineTab runId={latestRunId} media={media ?? []} />}
      {tab === "evidence" && <EvidenceTab runId={latestRunId} />}
      {tab === "review" && <ReviewTab runId={latestRunId} />}
      {tab === "report" && <ReportTab runId={latestRunId} />}
      {tab === "audit" && <AuditTable />}
    </div>
  );
}

function Overview({ caseData, run, mediaCount, onChanged }: {
  caseData: Case; run: Run | null; mediaCount: number; onChanged: () => void;
}) {
  const [policy, setPolicy] = useState("auto");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: costs } = useQuery({
    queryKey: ["model-calls", run?.id],
    queryFn: () => get<ModelCallsSummary>(`/runs/${run!.id}/model-calls`),
    enabled: !!run && ["completed", "completed_with_errors", "failed", "paused"]
      .includes(run.status),
  });

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "تعذر تنفيذ الإجراء");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <Card className="p-6 lg:col-span-2 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h2 className="font-semibold">التحليل</h2>
          {run && <StatusBadge status={run.status} />}
        </div>
        {run ? (
          <PipelineProgress run={run} />
        ) : (
          <p className="text-sm text-muted">
            لم يبدأ تحليل بعد. ارفع الوسائط ثم ابدأ التحليل.
          </p>
        )}
        <div className="flex items-center gap-3 flex-wrap pt-2 border-t border-hairline-soft">
          <select value={policy} onChange={(e) => setPolicy(e.target.value)}
                  className={inputCls + " w-auto"}>
            <option value="auto">تفكير عميق (أعلى دقة — موصى به)</option>
            <option value="never">بدون تفكير عميق (أسرع، دقة أقل)</option>
          </select>
          <Button variant="primary" disabled={busy || mediaCount === 0 ||
                    (run ? ["queued", "running"].includes(run.status) : false)}
                  onClick={() => void act(() =>
                    post(`/cases/${caseData.id}/runs`, { thinking_policy: policy }))}>
            <Play size={15} /> بدء تحليل جديد
          </Button>
          {run && ["failed", "paused", "cancelled"].includes(run.status) && (
            <Button disabled={busy}
                    onClick={() => void act(() => post(`/runs/${run.id}/resume`))}>
              <RotateCcw size={15} /> استئناف
            </Button>
          )}
          {run && ["queued", "running", "paused"].includes(run.status) && (
            <Button variant="danger" disabled={busy}
                    onClick={() => void act(() => post(`/runs/${run.id}/cancel`))}>
              <Ban size={15} /> إلغاء
            </Button>
          )}
        </div>
        {mediaCount === 0 && (
          <p className="text-xs text-warning">لا وسائط مرفوعة بعد — الرفع من تبويب «الوسائط».</p>
        )}
        {error && <p className="text-sm text-error">{error}</p>}
      </Card>

      <div className="space-y-4">
        <Card className="p-5 text-sm space-y-2">
          <h3 className="font-semibold mb-1">بطاقة القضية</h3>
          {caseData.investigator_name_ar && (
            <div><span className="text-muted">المحقق: </span>{caseData.investigator_name_ar}</div>
          )}
          <div><span className="text-muted">الوسائط: </span>{arDigits(mediaCount)}</div>
          <div><span className="text-muted">التحليلات: </span>{arDigits(caseData.runs?.length ?? 0)}</div>
          <div>
            <span className="text-muted">تمويه الوجوه: </span>
            {caseData.face_blur_enabled ? "مفعّل" : "معطّل"}
          </div>
          {caseData.notes_ar && (
            <p className="text-xs text-body bg-canvas-soft rounded-md p-2 border border-hairline-soft">
              {caseData.notes_ar}
            </p>
          )}
        </Card>
        {run?.model_snapshot && (
          <Card className="p-5 text-xs space-y-1.5">
            <h3 className="font-semibold text-sm mb-1">النموذج</h3>
            <div><span className="text-muted">الوضع: </span>{run.model_mode}</div>
            <div className="font-mono truncate" title={run.model_snapshot.model_fast}>
              {run.model_snapshot.model_fast}
            </div>
            {costs && (
              <div className="pt-1.5 border-t border-hairline-soft space-y-1">
                <div>الاستدعاءات: {arDigits(costs.totals.calls)}
                  {costs.totals.repaired > 0 && (
                    <span className="text-warning"> ({arDigits(costs.totals.repaired)} مُصلح)</span>
                  )}
                </div>
                <div>الرموز: {arDigits(costs.totals.input_tokens)} دخل /{" "}
                  {arDigits(costs.totals.output_tokens)} خرج</div>
                <div>التكلفة التقديرية:{" "}
                  <span className="font-mono">${costs.totals.cost_usd}</span></div>
              </div>
            )}
          </Card>
        )}
        <Badge tone="warning">
          كل النتائج استرشادية وتتطلب مراجعة خبير مؤهل
        </Badge>
      </div>
    </div>
  );
}
