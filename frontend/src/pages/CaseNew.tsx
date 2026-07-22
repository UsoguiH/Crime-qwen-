import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Card, Field, inputCls } from "../components/ui";
import { ApiError, Case, get, post } from "../lib/api";

export default function CaseNew() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // simple-flow has no cases screen — offer a shortcut to the latest case
  const { data: cases } = useQuery({
    queryKey: ["cases", ""],
    queryFn: () => get<Case[]>("/cases"),
  });
  const latest = cases?.[0];
  const [form, setForm] = useState({
    case_number: "", title_ar: "", location_ar: "",
    investigator_name_ar: "", notes_ar: "", incident_date_gregorian: "",
  });
  const set = (k: string) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await post<Case>("/cases", {
        ...form,
        incident_date_gregorian: form.incident_date_gregorian || null,
      });
      navigate(`/cases/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "تعذر إنشاء القضية");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <h1 data-anim="title" className="text-3xl font-normal mb-6">قضية جديدة</h1>
      <Card data-anim="hero" className="p-6">
        <form onSubmit={submit} className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="رقم القضية *">
              <input required className={inputCls + " latin"} dir="ltr"
                     value={form.case_number} onChange={set("case_number")} />
            </Field>
            <Field label="تاريخ الواقعة (ميلادي — يُحسب الهجري تلقائياً)">
              <input type="date" className={inputCls + " latin"} dir="ltr"
                     value={form.incident_date_gregorian}
                     onChange={set("incident_date_gregorian")} />
            </Field>
          </div>
          <Field label="عنوان القضية *">
            <input required className={inputCls} value={form.title_ar}
                   onChange={set("title_ar")} />
          </Field>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="الموقع">
              <input className={inputCls} value={form.location_ar}
                     onChange={set("location_ar")} />
            </Field>
            <Field label="اسم المحقق">
              <input className={inputCls} value={form.investigator_name_ar}
                     onChange={set("investigator_name_ar")} />
            </Field>
          </div>
          <Field label="ملاحظات موجزة (تُعرض على النموذج سياقاً للتحليل)">
            <textarea rows={3} value={form.notes_ar} onChange={set("notes_ar")}
                      className="w-full rounded-md border border-hairline-strong bg-card px-4 py-2.5 text-sm outline-none focus:border-primary" />
          </Field>
          {error && <div className="text-sm text-error">{error}</div>}
          <div className="flex gap-3 justify-end">
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "جارٍ الإنشاء…" : "إنشاء القضية"}
            </Button>
          </div>
        </form>
      </Card>

      {latest && (
        <Link to={`/cases/${latest.id}`} data-anim="chip"
              className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-hairline bg-card px-4 py-3 text-sm hover:border-hairline-strong hover:bg-canvas-soft transition-colors">
          <span className="min-w-0">
            <span className="block text-xs text-muted">متابعة آخر قضية</span>
            <span className="block truncate font-semibold">{latest.title_ar}</span>
          </span>
          <ArrowLeft size={15} className="shrink-0 text-muted" />
        </Link>
      )}
    </div>
  );
}
