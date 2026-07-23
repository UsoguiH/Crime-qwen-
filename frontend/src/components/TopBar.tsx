import { LayoutGrid, LogOut, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../lib/session";

/* Simple-flow chrome: one slim header instead of the sidebar.
   Logo → home (new case). Platform link, theme toggle, logout. */
export default function TopBar() {
  const { logout } = useSession();
  const [dark, setDark] = useState(document.documentElement.dataset.theme === "dark");
  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "";
    localStorage.setItem("athar-theme", next ? "dark" : "light");
  };

  return (
    <header className="sidebar-surface sticky top-0 z-40 border-b border-hairline">
      <div className="mx-auto flex h-14 max-w-[1500px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <Link to="/" className="flex items-baseline gap-2">
          <span data-anim-logo className="inline-block text-2xl font-semibold">الدليل الجنائي</span>
        </Link>
        <div className="flex items-center gap-2">
          <a href="/shell.html" title="المنصة"
             className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-body hover:text-ink hover:bg-hover transition-colors">
            <LayoutGrid size={14} /> المنصة
          </a>
          <button onClick={toggleTheme} title="الوضع الفاتح/الداكن"
                  className="text-muted hover:text-ink cursor-pointer p-1.5">
            {dark ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button title="خروج" className="text-muted hover:text-error cursor-pointer p-1.5"
                  onClick={() => void logout().then(() => window.location.assign("/login"))}>
            <LogOut size={15} />
          </button>
        </div>
      </div>
    </header>
  );
}
