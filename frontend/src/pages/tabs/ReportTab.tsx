import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Package, RefreshCw } from "lucide-react";
import { useState } from "react";
import {
  Badge, Button, Card, EmptyState, HashChip, Spinner,
} from "../../components/ui";
import { ReportRow, get, post } from "../../lib/api";
import { arDigits, fmtBytes, fmtDateTime } from "../../lib/format";

const KIND_AR: Record<string, string> = {
  pdf_a: "PDF/A", docx: "DOCX", bundle_zip: "حزمة المحكمة (ZIP)",
};

export default function ReportTab({ runId }: { runId: string | null }) {
  const qc = useQueryClient();
  const [generating, setGenerating] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const { data: reports, isLoading } = useQuery({
    queryKey: ["reports", runId],
    queryFn: () => get<ReportRow[]>(`/runs/${runId}/reports`),
    enabled: !!runId,
    refetchInterval: generating ? 2500 : false,
  });

  if (!runId) return <EmptyState title="لا تحليل بعد" />;

  const generate = async (kinds: string[]) => {
    setGenerating(true);
    await post(`/runs/${runId}/reports`, { kinds });
    setTimeout(() => setGenerating(false), 45_000);
    void qc.invalidateQueries({ queryKey: ["reports", runId] });
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="primary" onClick={() => void generate(["pdf"])}>
          <FileText size={15} /> تصدير PDF/A
        </Button>
        <Button onClick={() => void generate(["docx"])}>تصدير DOCX</Button>
        <Button onClick={() => void generate(["bundle"])}>
          <Package size={15} /> حزمة المحكمة الكاملة
        </Button>
        <Button variant="text" onClick={() => setPreviewKey((k) => k + 1)}>
          <RefreshCw size={14} /> تحديث المعاينة
        </Button>
        {generating && <span className="text-xs text-muted flex items-center gap-2">
          <Spinner /> جارٍ الإخراج…
        </span>}
      </div>

      {isLoading ? <Spinner /> : (reports?.length ?? 0) > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted border-b border-hairline">
                <th className="p-2.5 text-start">النوع</th>
                <th className="p-2.5 text-start">الإصدار</th>
                <th className="p-2.5 text-start">الحجم</th>
                <th className="p-2.5 text-start">بصمة الملف</th>
                <th className="p-2.5 text-start">رأس سجل التدقيق</th>
                <th className="p-2.5 text-start">أُصدر</th>
                <th className="p-2.5 text-start"></th>
              </tr>
            </thead>
            <tbody>
              {reports!.map((r) => (
                <tr key={r.id} className="border-b border-hairline-soft">
                  <td className="p-2.5">
                    {KIND_AR[r.kind] ?? r.kind}
                    {r.pdf_variant && r.pdf_variant !== "pdf" && (
                      <Badge tone="success">{r.pdf_variant}</Badge>
                    )}
                  </td>
                  <td className="p-2.5">{arDigits(r.version)}</td>
                  <td className="p-2.5">{fmtBytes(r.size_bytes)}</td>
                  <td className="p-2.5"><HashChip value={r.file_sha256} /></td>
                  <td className="p-2.5"><HashChip value={r.audit_head_hash} short={12} /></td>
                  <td className="p-2.5 whitespace-nowrap">{fmtDateTime(r.generated_at)}</td>
                  <td className="p-2.5">
                    <a href={`/api/reports/${r.id}/download`}
                       className="inline-flex items-center gap-1 text-primary hover:text-primary-active">
                      <Download size={13} /> تنزيل
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div className="px-4 py-2.5 border-b border-hairline text-xs text-muted flex items-center justify-between">
          <span>معاينة حية للتقرير (HTML)</span>
          <Badge tone="error">سري</Badge>
        </div>
        <iframe key={previewKey} title="معاينة التقرير" sandbox=""
                src={`/api/runs/${runId}/report-preview`}
                className="w-full h-[75vh] bg-white" />
      </Card>
    </div>
  );
}
