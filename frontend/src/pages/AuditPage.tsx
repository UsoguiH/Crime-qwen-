import AuditTable from "../components/AuditTable";

export default function AuditPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-normal">سجل التدقيق</h1>
        <p className="text-muted text-sm mt-1">
          سجل غير قابل للتعديل الخفي: كل قيد يحمل بصمة تسلسلية مرتبطة بما قبله،
          وأي عبث لاحق يكسر السلسلة ويُكشف عند التحقق.
        </p>
      </div>
      <AuditTable />
    </div>
  );
}
