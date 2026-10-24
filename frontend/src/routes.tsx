import { Navigate, Route, Routes } from "react-router";

import { useSession } from "./api/queries";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { DesignPage } from "./pages/DesignPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectFormPage } from "./pages/ProjectFormPage";
import { ProjectsPage } from "./pages/ProjectsPage";

export function AppRoutes() {
  const session = useSession();
  if (session.isPending) {
    return (
      <div style={{ padding: 32 }}>
        <Spinner />
      </div>
    );
  }
  if (!session.data) return <LoginPage />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/projetos" replace />} />
        <Route path="projetos" element={<ProjectsPage />} />
        <Route path="projetos/novo" element={<ProjectFormPage />} />
        <Route path="p/:projetoId" element={<ProjectDetailPage />} />
        <Route path="p/:projetoId/editar" element={<ProjectFormPage />} />
        <Route path="_design" element={<DesignPage />} />
        <Route path="*" element={<Navigate to="/projetos" replace />} />
      </Route>
    </Routes>
  );
}
