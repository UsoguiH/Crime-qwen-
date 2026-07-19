import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { AuditRow, get } from "../lib/api";
import { arDigits, fmtDateTime } from "../lib/format";
import { Badge, Button, HashChip, Spinner } from "./ui";

export default function AuditTable({ objectId }: { objectId?: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["audit", objectId],
    queryFn: () => get<AuditRow[]>(
      `/audit?limit=200${objectId ? `&object_id=${objectId}` : ""}`),
  });
  const [verifying, setVerifying] = useState(false);
  const [verdict, setVerdict] = useState<{
    valid: boolean; length: number; head_hash: string;
    first_broken_id: number | null } | null>(null);

  const verify = async () => {
    setVerifying(true);
    try {
      setVerdict(await get("/audit/verify"));
    } finally {
      setVerifying(false);
    }
  };

  if (isLoading) return <Spinner />;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <Button onClick={() => void verify()} disabled={verifying}>
          <ShieldCheck size={15} />
          {verifying ? "جارٍ التحقق…" : "التحقق من سلسلة السجل"}
        </Button>
        {verdict && (verdict.valid ? (
          <span className="flex items-center gap-2 text-sm text-success">
            <Badge tone="success">السلسلة سليمة</Badge>
            الطول: {arDigits(verdict.length)} · الرأس:
            <HashChip value={verdict.head_hash} />
          </span>
        ) : (
          <Badge tone="error">
            كُسرت السلسلة عند القيد رقم {arDigits(verdict.first_broken_id ?? 0)}
          </Badge>
        ))}
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-start text-muted border-b border-hairline">
              <th className="p-2.5 text-start">#</th>
              <th className="p-2.5 text-start">الوقت</th>
              <th className="p-2.5 text-start">الفاعل</th>
              <th className="p-2.5 text-start">الإجراء</th>
              <th className="p-2.5 text-start">البصمة</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((r) => (
              <tr key={r.id} className="border-b border-hairline-soft">
                <td className="p-2.5 text-muted">{arDigits(r.id)}</td>
                <td className="p-2.5 whitespace-nowrap">{fmtDateTime(r.ts)}</td>
                <td className="p-2.5">{r.actor_label || "النظام"}</td>
                <td className="p-2.5 font-mono">{r.action}</td>
                <td className="p-2.5"><HashChip value={r.entry_hash} short={12} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
