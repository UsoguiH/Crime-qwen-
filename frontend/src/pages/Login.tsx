import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Spinner } from "../components/ui";
import { get, User } from "../lib/api";
import { ROLE_AR } from "../lib/format";
import { useSession } from "../lib/session";

export default function Login() {
  const { login } = useSession();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => get<User[]>("/auth/users"),
  });

  const enter = async (u: User) => {
    setBusy(u.id);
    try {
      await login(u.id);
      navigate("/");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-3xl text-center">
        <Badge tone="error">سري</Badge>
        <h1 className="text-5xl mt-6 mb-2 font-normal">أثر</h1>
        <p className="text-body mb-1">نظام تحليل مسرح الجريمة بمساعدة الذكاء الاصطناعي</p>
        <p className="text-muted text-sm mb-10">«كل تماسٍ يترك أثراً» — اختر حسابك للدخول</p>
        {isLoading ? (
          <Spinner />
        ) : (
          <div className="grid sm:grid-cols-3 gap-4">
            {(users ?? []).map((u) => (
              <button key={u.id} onClick={() => void enter(u)}
                      disabled={busy !== null}
                      className="card p-6 hover:border-hairline-strong transition-colors cursor-pointer text-center">
                <div className="mx-auto mb-3 h-12 w-12 rounded-full bg-strong grid place-items-center text-lg">
                  {u.display_name_ar.slice(0, 2)}
                </div>
                <div className="font-semibold text-sm">{u.display_name_ar}</div>
                <div className="mt-2">
                  <Badge>{ROLE_AR[u.role] ?? u.role}</Badge>
                </div>
                {busy === u.id && <div className="mt-3"><Spinner /></div>}
              </button>
            ))}
          </div>
        )}
        <p className="text-[11px] text-muted mt-10 max-w-md mx-auto">
          تحليل بمساعدة الذكاء الاصطناعي — يتطلب تحقيق خبير مؤهل قبل أي استخدام قانوني.
          كل إجراء يُسجَّل باسم صاحبه في سجل تدقيق مسلسل البصمات.
        </p>
      </div>
    </div>
  );
}
