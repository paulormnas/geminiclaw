import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router";

import { useLogout, useProjects } from "../api/queries";
import { applyTheme, loadTheme, type Theme } from "../theme";
import styles from "./Layout.module.css";
import { Button, Dialog } from "./ui";

const SOON = ["Painel", "Conversa", "Artefatos", "Grafo", "Configurações"];

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(loadTheme);
  useEffect(() => applyTheme(theme), [theme]);
  const options: [Theme, string][] = [
    ["light", "Claro"],
    ["dark", "Escuro"],
    ["system", "Sistema"],
  ];
  return (
    <div>
      <span className={styles["label"]}>Tema</span>
      <div className={styles["seg"]} role="group" aria-label="Tema">
        {options.map(([value, label]) => (
          <button key={value} type="button" aria-pressed={theme === value} onClick={() => setTheme(value)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function CommandPalette({ onClose }: { onClose: () => void }) {
  const projects = useProjects("ativos");
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const go = (to: string) => {
    onClose();
    void navigate(to);
  };
  const entries = [
    { label: "Projetos", to: "/projetos" },
    { label: "Novo projeto", to: "/projetos/novo" },
    ...(projects.data ?? []).map((p) => ({ label: `Projeto: ${p.titulo}`, to: `/p/${p.projeto_id}` })),
  ].filter((e) => e.label.toLowerCase().includes(query.toLowerCase()));
  return (
    <Dialog title="Buscar ou executar" onClose={onClose}>
      <div className={styles["palette"]}>
        <input
          aria-label="Buscar"
          placeholder="Digite para filtrar…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ height: 36, padding: "0 12px", borderRadius: 10, border: "1px solid var(--border-strong)", background: "var(--surface)", color: "var(--text)" }}
        />
        <ul>
          {entries.map((e) => (
            <li key={e.to}>
              <button type="button" onClick={() => go(e.to)}>
                {e.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  );
}

export function Layout() {
  const projects = useProjects("ativos");
  const logout = useLogout();
  const navigate = useNavigate();
  const { projetoId } = useParams();
  const [palette, setPalette] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className={styles["app"]}>
      <aside className={styles["side"]} aria-label="Navegação">
        <div className={styles["brand"]}>
          <span className={styles["mark"]} aria-hidden="true" />
          Bancada
        </div>
        <div>
          <label className={styles["label"]} htmlFor="seletor-projeto">
            Projeto
          </label>
          <select
            id="seletor-projeto"
            className={styles["select"]}
            value={projetoId ?? ""}
            onChange={(e) => void navigate(e.target.value ? `/p/${e.target.value}` : "/projetos")}
          >
            <option value="">Todos os projetos</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.projeto_id} value={p.projeto_id}>
                {p.titulo}
              </option>
            ))}
          </select>
        </div>
        <nav className={styles["nav"]} aria-label="Seções">
          <NavLink to="/projetos">Projetos</NavLink>
          {SOON.map((name) => (
            <span key={name} className={styles["soon"]} aria-disabled="true">
              {name}
              <small>em breve</small>
            </span>
          ))}
        </nav>
        <div className={styles["foot"]}>
          <button className={styles["cmd"]} type="button" onClick={() => setPalette(true)}>
            Buscar ou executar…<span className={styles["kbd"]}>⌘K</span>
          </button>
          <ThemeToggle />
          <Button variant="ghost" onClick={() => logout.mutate()} loading={logout.isPending}>
            Sair
          </Button>
        </div>
      </aside>
      <main className={styles["main"]}>
        <Outlet />
      </main>
      {palette ? <CommandPalette onClose={() => setPalette(false)} /> : null}
    </div>
  );
}
