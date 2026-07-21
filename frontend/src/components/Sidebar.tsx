import { useQuery } from "@tanstack/react-query";
import {
  FilePlus2, FileText, FolderKanban, Images, LogOut, Menu, Moon,
  PanelRightClose, PanelRightOpen, Search, Settings, Sun, X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useMatch, useSearchParams } from "react-router-dom";
import { Case, Entity, Run, get } from "../lib/api";
import { STATUS_AR, ROLE_AR, arDigits } from "../lib/format";
import { useSession } from "../lib/session";
import { Badge } from "./ui";

const CASE_TABS: Array<{ key: string; label: string; icon: ReactNode }> = [
  { key: "media", label: "الوسائط", icon: <Images size={15} /> },
  { key: "evidence", label: "الأدلة", icon: <Search size={15} /> },
  { key: "report", label: "التقرير", icon: <FileText size={15} /> },
];

function NavItem({ to, icon, label, active, badge, onClick, collapsed }: {
  to: string; icon: ReactNode; label: string; active: boolean;
  badge?: ReactNode; onClick?: () => void; collapsed?: boolean;
}) {
  return (
    <Link
      to={to}
      onClick={onClick}
      title={collapsed ? label : undefined}
      className={`flex items-center rounded-md text-sm transition-colors border-s-2 ${
        collapsed ? "justify-center py-2.5" : "gap-2.5 px-3 py-2"} ${
        active
          ? "bg-canvas-soft text-ink font-semibold border-primary"
          : "text-body hover:text-ink hover:bg-canvas-soft border-transparent"
      }`}
    >
      <span className={active ? "text-primary" : "text-muted"}>{icon}</span>
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && badge}
    </Link>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="px-3 pt-5 pb-1.5 text-[11px] font-semibold text-muted">
      {children}
    </div>
  );
}

function RunChip({ run }: { run: Run }) {
  const active = ["queued", "running"].includes(run.status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
        active ? "text-ink" : run.status === "failed" || run.status === "cancelled"
          ? "bg-error-soft text-error" : "bg-success-soft text-success"
      }`}
      style={active ? { background: "var(--color-pill-read)" } : undefined}
    >
      {active && (
        <span className="h-1.5 w-1.5 rounded-full bg-ink animate-pulse" />
      )}
      {STATUS_AR[run.status] ?? run.status}
    </span>
  );
}

function SidebarBody({ onNavigate, collapsed = false, onToggle }: {
  onNavigate?: () => void; collapsed?: boolean; onToggle?: () => void;
}) {
  const { user, logout } = useSession();
  const location = useLocation();
  const [params] = useSearchParams();
  const caseMatch = useMatch("/cases/:caseId");
  const caseId = caseMatch?.params.caseId;
  const inCase = !!caseId && caseId !== "new";
  const activeTab = params.get("tab") ?? "media";

  const { data: caseData } = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => get<Case>(`/cases/${caseId}`),
    enabled: inCase,
  });
  const latestRunId = caseData?.runs?.[0]?.id ?? null;
  const { data: run } = useQuery({
    queryKey: ["run", latestRunId],
    queryFn: () => get<Run>(`/runs/${latestRunId}`),
    enabled: !!latestRunId,
  });
  const { data: pending } = useQuery({
    queryKey: ["review-count", latestRunId],
    queryFn: () => get<Entity[]>(
      `/runs/${latestRunId}/entities?needs_review=true&review_status=pending`),
    enabled: !!latestRunId,
    refetchInterval: 60_000,
  });

  const [dark, setDark] = useState(document.documentElement.dataset.theme === "dark");
  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "";
    localStorage.setItem("athar-theme", next ? "dark" : "light");
  };

  return (
    <div className="flex h-full flex-col">
      <div className={`border-b border-hairline ${collapsed ? "px-2 pt-4 pb-3" : "px-4 pt-5 pb-4"}`}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-3">
            {onToggle && (
              <button onClick={onToggle} title="توسيع القائمة"
                      className="text-muted hover:text-ink cursor-pointer p-1">
                <PanelRightOpen size={17} />
              </button>
            )}
            <Link to="/" onClick={onNavigate} className="text-lg font-semibold">أثر</Link>
            <Link to="/cases/new" onClick={onNavigate} title="قضية جديدة"
                  className="grid h-9 w-9 place-items-center rounded-md bg-primary text-on-primary hover:bg-primary-active transition-colors">
              <FilePlus2 size={15} />
            </Link>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <Link to="/" onClick={onNavigate} className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold">أثر</span>
                <span className="text-[10px] text-muted">تحليل مسرح الجريمة</span>
              </Link>
              <span className="flex items-center gap-1">
                <Badge tone="error">سري</Badge>
                {onToggle && (
                  <button onClick={onToggle} title="طي القائمة"
                          className="text-muted hover:text-ink cursor-pointer p-1">
                    <PanelRightClose size={16} />
                  </button>
                )}
              </span>
            </div>
            <Link to="/cases/new" onClick={onNavigate}
                  className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary text-on-primary text-sm font-medium hover:bg-primary-active transition-colors">
              <FilePlus2 size={15} /> قضية جديدة
            </Link>
          </>
        )}
      </div>

      <nav className={`flex-1 overflow-y-auto pb-4 ${collapsed ? "px-2" : "px-3"}`}>
        {collapsed ? <div className="pt-3" /> : <SectionLabel>التنقل</SectionLabel>}
        <div className="space-y-0.5">
          <NavItem to="/" icon={<FolderKanban size={15} />} label="القضايا"
                   active={location.pathname === "/"} onClick={onNavigate}
                   collapsed={collapsed} />
          <NavItem to="/settings" icon={<Settings size={15} />} label="الإعدادات"
                   active={location.pathname === "/settings"} onClick={onNavigate}
                   collapsed={collapsed} />
        </div>

        {inCase && caseData && (
          <>
            {collapsed ? (
              <div className="my-3 border-t border-hairline" />
            ) : (
              <SectionLabel>
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-ink normal-case text-xs font-semibold"
                        title={caseData.title_ar}>
                    {caseData.title_ar}
                  </span>
                  {run && <RunChip run={run} />}
                </span>
                <span className="font-mono text-[10px] text-muted-soft latin" dir="ltr">
                  {caseData.case_number}
                </span>
              </SectionLabel>
            )}
            <div className="space-y-0.5">
              {CASE_TABS.map((t) => (
                <NavItem
                  key={t.key}
                  to={`/cases/${caseId}?tab=${t.key}`}
                  icon={t.icon}
                  label={t.label}
                  active={activeTab === t.key}
                  onClick={onNavigate}
                  collapsed={collapsed}
                  badge={t.key === "review" && (pending?.length ?? 0) > 0 ? (
                    <span className="rounded-full bg-warning-soft text-warning border border-warning/40 px-1.5 text-[10px] font-bold">
                      {arDigits(pending!.length)}
                    </span>
                  ) : undefined}
                />
              ))}
            </div>
          </>
        )}
      </nav>

      <div className={`border-t border-hairline ${collapsed ? "p-2" : "p-3"}`}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <span title={user?.display_name_ar}
                  className="h-8 w-8 shrink-0 rounded-full bg-strong grid place-items-center text-xs">
              {user?.display_name_ar.slice(0, 2)}
            </span>
            <button onClick={toggleTheme} title="الوضع الفاتح/الداكن"
                    className="text-muted hover:text-ink cursor-pointer p-1">
              {dark ? <Sun size={15} /> : <Moon size={15} />}
            </button>
            <button title="خروج" className="text-muted hover:text-error cursor-pointer p-1"
                    onClick={() => void logout().then(() => window.location.assign("/login"))}>
              <LogOut size={15} />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2.5">
            <span className="h-9 w-9 shrink-0 rounded-full bg-strong grid place-items-center text-sm">
              {user?.display_name_ar.slice(0, 2)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{user?.display_name_ar}</span>
              <span className="block text-[11px] text-muted">
                {user ? ROLE_AR[user.role] : ""}
              </span>
            </span>
            <button onClick={toggleTheme} title="الوضع الفاتح/الداكن"
                    className="text-muted hover:text-ink cursor-pointer p-1">
              {dark ? <Sun size={15} /> : <Moon size={15} />}
            </button>
            <button title="خروج" className="text-muted hover:text-error cursor-pointer p-1"
                    onClick={() => void logout().then(() => window.location.assign("/login"))}>
              <LogOut size={15} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Sidebar() {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("athar-sidebar") === "collapsed");
  const routerLocation = useLocation();
  useEffect(() => setOpen(false), [routerLocation]);
  useEffect(() => {
    document.documentElement.dataset.sidebar = collapsed ? "collapsed" : "";
    localStorage.setItem("athar-sidebar", collapsed ? "collapsed" : "open");
  }, [collapsed]);

  return (
    <>
      {/* desktop */}
      <aside className="fixed inset-y-0 start-0 z-40 hidden w-[var(--sidebar-w)] border-e border-hairline bg-canvas lg:block transition-[width] duration-200 overflow-hidden">
        <SidebarBody collapsed={collapsed}
                     onToggle={() => setCollapsed((c) => !c)} />
      </aside>

      {/* mobile top bar */}
      <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center justify-between border-b border-hairline bg-canvas px-4 lg:hidden">
        <button onClick={() => setOpen(true)} className="text-body cursor-pointer p-1"
                aria-label="القائمة">
          <Menu size={20} />
        </button>
        <Link to="/" className="text-lg font-semibold">أثر</Link>
        <Badge tone="error">سري</Badge>
      </header>

      {/* mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0" style={{ background: "#26251e66" }}
               onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 start-0 w-72 bg-canvas border-e border-hairline">
            <button onClick={() => setOpen(false)} aria-label="إغلاق"
                    className="absolute top-4 end-3 text-muted hover:text-ink cursor-pointer z-10">
              <X size={18} />
            </button>
            <SidebarBody onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
