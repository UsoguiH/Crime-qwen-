import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import EvidenceCard from "../../components/EvidenceCard";
import { Button, EmptyState, Spinner, inputCls } from "../../components/ui";
import { Entity, get } from "../../lib/api";
import { CATEGORY_AR, arDigits } from "../../lib/format";

export default function EvidenceTab({ runId }: { runId: string | null }) {
  const [category, setCategory] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);
  const { data: entities, isLoading } = useQuery({
    queryKey: ["entities", runId, category, onlyReview],
    queryFn: () => {
      const params = new URLSearchParams();
      if (category) params.set("category", category);
      if (onlyReview) params.set("needs_review", "true");
      const qs = params.toString();
      return get<Entity[]>(`/runs/${runId}/entities${qs ? `?${qs}` : ""}`);
    },
    enabled: !!runId,
  });

  if (!runId) return <EmptyState title="لا تحليل بعد" />;
  if (isLoading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <select value={category} onChange={(e) => setCategory(e.target.value)}
                className={inputCls + " w-auto h-9 text-xs"}>
          <option value="">كل الفئات</option>
          {Object.entries(CATEGORY_AR).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <label className="text-sm text-body flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={onlyReview}
                 onChange={(e) => setOnlyReview(e.target.checked)} />
          «يتطلب مراجعة بشرية» فقط
        </label>
        <span className="text-xs text-muted">
          {arDigits(entities?.length ?? 0)} دليلاً
        </span>
      </div>
      {!entities?.length ? (
        <div className="text-center">
          <EmptyState title="لم يتم رصد أدلة ظاهرة"
                      hint="القائمة الفارغة نتيجة صحيحة — لا يختلق النظام أدلة" />
          <Link to="?tab=media"><Button>إدارة الوسائط ورفع المزيد</Button></Link>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {entities.map((e) => <EvidenceCard key={e.id} e={e} />)}
        </div>
      )}
    </div>
  );
}
