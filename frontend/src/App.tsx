import { useEffect, useRef } from "react";
import {
  createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation,
} from "react-router-dom";
import TopBar from "./components/TopBar";
import { Spinner } from "./components/ui";
import { runEntrance } from "./lib/anim";
import { useSession } from "./lib/session";
import CaseDetail from "./pages/CaseDetail";
import CaseNew from "./pages/CaseNew";
import Enter from "./pages/Enter";
import Login from "./pages/Login";
import PhotoAnalysis from "./pages/PhotoAnalysis";

function Shell() {
  const { user, loading } = useSession();
  const mainRef = useRef<HTMLElement>(null);
  const location = useLocation();

  // spring entrance choreography on every page entrance (template spec)
  useEffect(() => {
    if (!mainRef.current) return;
    const raf = requestAnimationFrame(() => {
      if (mainRef.current) runEntrance(mainRef.current);
    });
    return () => cancelAnimationFrame(raf);
  }, [location.pathname, loading, user]);

  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center"><Spinner /></div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <main ref={mainRef} className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <Outlet />
      </main>
      <footer className="anim-disclaimer border-t border-hairline py-4 text-center text-[11px] text-muted">
        تحليل بمساعدة الذكاء الاصطناعي — يتطلب تحقيق خبير مؤهل قبل أي استخدام قانوني
      </footer>
    </div>
  );
}

/* simple-flow: no sidebar, no cases screen — new case → its media → analysis */
const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/enter", element: <Enter /> },
  {
    element: <Shell />,
    children: [
      { path: "/", element: <CaseNew /> },
      { path: "/cases/new", element: <Navigate to="/" replace /> },
      { path: "/cases/:caseId", element: <CaseDetail /> },
      { path: "/cases/:caseId/photos/:mediaId", element: <PhotoAnalysis /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
