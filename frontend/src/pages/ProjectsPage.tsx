import { useState } from "react";
import { Link } from "react-router";

import { useProjects } from "../api/queries";
import { EmptyState, ErrorState, Spinner, StatusBadge } from "../components/ui";
import ui from "../components/ui.module.css";
import styles from "./pages.module.css";

const FILTERS: [string, string][] = [
  ["ativos", "Ativos"],
  ["pausado", "Pausados"],
  ["concluido", "Concluídos"],
  ["arquivado", "Arquivados"],
  ["todos", "Todos"],
];

export function ProjectsPage() {
  const [filter, setFilter] = useState("ativos");
  const [search, setSearch] = useState("");
  const projects = useProjects(filter);
  const shown = (projects.data ?? []).filter((p) => p.titulo.toLowerCase().includes(search.toLowerCase()));
  return (
    <>
      <header className={styles["head"]}>
        <div>
          <span className={styles["label"]}>Pesquisa</span>
          <h1>Projetos</h1>
        </div>
        <Link className={`${ui["btn"]} ${ui["primary"]}`} to="/projetos/novo">
          Novo projeto
        </Link>
      </header>
      <div className={styles["filters"]}>
        <div className={ui["field"]}>
          <label className={ui["label"]} htmlFor="filtro-estado">
            Estado
          </label>
          <select id="filtro-estado" className={ui["input"]} value={filter} onChange={(e) => setFilter(e.target.value)}>
            {FILTERS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className={ui["field"]}>
          <label className={ui["label"]} htmlFor="busca-titulo">
            Buscar por título
          </label>
          <input id="busca-titulo" className={ui["input"]} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>
      {projects.isPending ? <Spinner /> : null}
      {projects.isError ? <ErrorState message="Não foi possível listar os projetos." onRetry={() => void projects.refetch()} /> : null}
      {projects.data && shown.length === 0 ? (
        <EmptyState title={search ? "Nenhum projeto com esse título" : "Nenhum projeto ainda"}>
          {search ? null : (
            <Link className={`${ui["btn"]} ${ui["primary"]}`} to="/projetos/novo">
              Criar o primeiro projeto
            </Link>
          )}
        </EmptyState>
      ) : null}
      {shown.length > 0 ? (
        <div className={`${styles["panel"]} ${styles["tablewrap"]}`}>
          <table className={styles["table"]}>
            <thead>
              <tr>
                <th className={styles["label"]}>Título</th>
                <th className={styles["label"]}>Estado</th>
                <th className={styles["label"]}>Criado em</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.projeto_id}>
                  <td>
                    <Link to={`/p/${p.projeto_id}`}>{p.titulo}</Link>
                  </td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                  <td>{p.criado_em.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}
