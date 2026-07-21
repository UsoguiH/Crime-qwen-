import {
  createBrowserRouter, Navigate, Outlet, RouterProvider,
} from "react-router-dom";
import Sidebar from "./components/Sidebar";
import { Spinner } from "./components/ui";
import { useSession } from "./lib/session";
import CaseDetail from "./pages/CaseDetail";
import CaseNew from "./pages/CaseNew";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import PhotoAnalysis from "./pages/PhotoAnalysis";
import Settings from "./pages/Settings";

function Shell() {
  const { user, loading } = useSession();

  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center"><Spinner /></div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="lg:ms-[var(--sidebar-w)] pt-14 lg:pt-0 flex min-h-screen flex-col transition-[margin] duration-200">
        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-8 sm:px-6 lg:px-8">
          <Outlet />
        </main>
        <footer className="border-t border-hairline py-4 text-center text-[11px] text-muted">
          تحليل بمساعدة الذكاء الاصطناعي — يتطلب تحقيق خبير مؤهل قبل أي استخدام قانوني
        </footer>
      </div>
    </div>
  );
}

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  {
    element: <Shell />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/cases/new", element: <CaseNew /> },
      { path: "/cases/:caseId", element: <CaseDetail /> },
      { path: "/cases/:caseId/photos/:mediaId", element: <PhotoAnalysis /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
