import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { Spinner, StatusBadge } from "../components/ui";
import { Case, Media, Run, get } from "../lib/api";
import { fmtDate } from "../lib/format";
import { useRunEvents } from "../lib/sse";
import MediaTab from "./tabs/MediaTab";

export default function CaseDetail() {
  const { caseId = "" } = useParams();

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
          <Link to="/" className="text-sm text-body hover:text-ink inline-flex items-center gap-1">
            <ArrowRight size={14} /> قضية جديدة
          </Link>
          <div className="flex items-center gap-3 flex-wrap mt-1">
            <h1 data-anim="title" className="text-2xl font-normal">{caseData.title_ar}</h1>
            <StatusBadge status={caseData.status} />
          </div>
          <div data-anim="rise" className="text-sm text-muted mt-1 flex flex-wrap gap-x-4">
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

      <MediaTab caseId={caseId} media={media ?? []} />
    </div>
  );
}

