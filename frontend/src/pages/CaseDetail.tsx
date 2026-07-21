import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { Spinner, StatusBadge } from "../components/ui";
import { Case, Media, Run, get } from "../lib/api";
import { fmtDate } from "../lib/format";
import { useRunEvents } from "../lib/sse";
import EvidenceTab from "./tabs/EvidenceTab";
import MediaTab from "./tabs/MediaTab";
import ReportTab from "./tabs/ReportTab";

const TABS = [
  ["media", "الوسائط"], ["evidence", "الأدلة"], ["report", "التقرير"],
] as const;

export default function CaseDetail() {
  const { caseId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "media";

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

      {tab === "media" && <MediaTab caseId={caseId} media={media ?? []} />}
      {tab === "evidence" && <EvidenceTab runId={latestRunId} />}
      {tab === "report" && <ReportTab runId={latestRunId} />}
    </div>
  );
}

