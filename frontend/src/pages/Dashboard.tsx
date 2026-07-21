import { useQuery } from "@tanstack/react-query";
import { FolderSearch } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, EmptyState, Spinner, StatusBadge, Badge } from "../components/ui";
import { Case, get } from "../lib/api";
import { arDigits, fmtDate } from "../lib/format";

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-4 text-center">
      <div className="text-2xl">{arDigits(value)}</div>
      <div className="text-xs text-muted">{label}</div>
    </Card>
  );
}

export default function Dashboard() {
  const [q, setQ] = useState("");
  const { data: cases, isLoading } = useQuery({
    queryKey: ["cases", q],
    queryFn: () => get<Case[]>(`/cases${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

  const all = cases ?? [];
  const active = all.filter((c) => c.status === "analyzing").length;
  const pending = all.reduce((sum, c) => sum + (c.pending_review ?? 0), 0);

  return (
    <div className="space-y-8">
      <div>
        <h1 data-anim="title" className="text-3xl font-normal">القضايا</h1>
        <p data-anim="rise" className="text-muted text-sm mt-1">إدارة قضايا التحليل الجنائي البصري</p>
      </div>

      <div data-anim="hero" className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Kpi label="إجمالي القضايا" value={all.length} />
        <Kpi label="قيد التحليل" value={active} />
        <Kpi label="بانتظار المراجعة" value={pending} />
        <Kpi label="مكتملة" value={all.filter((c) => c.status === "complete").length} />
      </div>

      <input
        value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="بحث برقم القضية أو عنوانها…"
        data-anim="hero"
        className="w-full h-11 rounded-md border border-hairline-strong bg-card px-4 text-sm outline-none focus:border-primary"
      />

      {isLoading ? (
        <Spinner />
      ) : all.length === 0 ? (
        <EmptyState title="لا قضايا بعد" hint="ابدأ بإنشاء قضية جديدة ورفع موادها المصورة" />
      ) : (
        <div className="anim-list grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {all.map((c) => (
            <Link key={c.id} to={`/cases/${c.id}`}>
              <Card className="p-5 h-full hover:border-hairline-strong transition-colors">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="font-mono text-xs text-body bg-strong rounded-full px-2.5 py-0.5">
                    {c.case_number}
                  </span>
                  <StatusBadge status={c.status} />
                </div>
                <div className="font-semibold leading-snug mb-2">{c.title_ar}</div>
                <div className="text-xs text-muted space-y-1">
                  {c.location_ar && <div><FolderSearch className="inline ms-0 me-1" size={12} />{c.location_ar}</div>}
                  <div>
                    الوسائط: {arDigits(c.media_count ?? 0)}
                    {" · "}أُنشئت: {fmtDate(c.created_at)}
                  </div>
                </div>
                {(c.pending_review ?? 0) > 0 && (
                  <div className="mt-3">
                    <Badge tone="warning">
                      {arDigits(c.pending_review!)} بانتظار المراجعة البشرية
                    </Badge>
                  </div>
                )}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
