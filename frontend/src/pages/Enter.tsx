import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Spinner } from "../components/ui";
import { Case, User, get } from "../lib/api";
import { useSession } from "../lib/session";

/* Platform-shell entry point (/enter): one click on مسرح الجريمة lands the
   user INSIDE the case — auto-login as the investigator (mock auth, POC),
   then straight to the latest case's media screen; falls back to the
   new-case form when the system is empty. */
export default function Enter() {
  const { user, loading, login } = useSession();
  const navigate = useNavigate();
  const started = useRef(false);

  useEffect(() => {
    if (loading || started.current) return;
    started.current = true;
    void (async () => {
      try {
        if (!user) {
          const users = await get<User[]>("/auth/users");
          const inv = users.find((u) => u.role === "investigator") ?? users[0];
          if (inv) await login(inv.id);
        }
        const cases = await get<Case[]>("/cases");
        navigate(cases[0] ? `/cases/${cases[0].id}` : "/", { replace: true });
      } catch {
        navigate("/login", { replace: true });
      }
    })();
  }, [loading, user, login, navigate]);

  return (
    <div className="min-h-screen grid place-items-center"><Spinner /></div>
  );
}
