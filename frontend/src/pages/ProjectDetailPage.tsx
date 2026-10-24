import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { useProject, useUpdateProject } from "../api/queries";
import { Button, Dialog, dialogActions, ErrorState, Spinner, StatusBadge } from "../components/ui";
import ui from "../components/ui.module.css";
import styles from "./pages.module.css";

type Target = "ativo" | "pausado" | "concluido" | "arquivado";

const ACTIONS: Record<string, [Target, string][]> = {
  ativo: [["pausado", "Pausar"], ["concluido", "Concluir"], ["arquivado", "Arquivar"]],
  pausado: [["ativo", "Reativar"], ["concluido", "Concluir"], ["arquivado", "Arquivar"]],
  concluido: [["ativo", "Reativar"], ["arquivado", "Arquivar"]],
  arquivado: [["pausado", "Desarquivar"]],
};

export function ProjectDetailPage() {
  const { projetoId } = useParams();
  const project = useProject(projetoId);
  const update = useUpdateProject(projetoId ?? "");
  const [confirm, setConfirm] = useState<Target | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  if (project.isPending) return <Spinner />;
  if (project.isError || !project.data) {
    const missing = project.error instanceof ApiError && project.error.status === 404;
    return <ErrorState message={missing ? "Projeto não encontrado." : "Não foi possível carregar o projeto."} />;
  }
  const p = project.data;

  const apply = (target: Target) => {
    setFailure(null);
    setConfirm(null);
    update.mutate(
      { status: target },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.erro === "pesquisa_em_execucao") {
            const sessions = (error.extra["sessoes"] as { alias: string | null }[] | undefined) ?? [];
            setFailure(`Há pesquisa em execução (${sessions.map((s) => s.alias ?? "sem apelido").join(", ")}). Encerre-a antes.`);
          } else {
            setFailure("Não foi possível alterar o estado.");
          }
        },
      },
    );
  };
  const click = (target: Target) => (target === "concluido" || target === "arquivado" ? setConfirm(target) : apply(target));

  return (
    <>
      <header className={styles["head"]}>
        <div>
          <span className={styles["label"]}>Projeto</span>
          <h1>{p.titulo}</h1>
        </div>
        <div className={styles["actions"]}>
          <Link className={ui["btn"]} to={`/p/${p.projeto_id}/editar`}>
            Editar
          </Link>
          {(ACTIONS[p.status] ?? []).map(([target, label]) => (
            <Button key={target} onClick={() => click(target)} loading={update.isPending && update.variables?.status === target}>
              {label}
            </Button>
          ))}
        </div>
      </header>
      {failure ? (
        <div role="alert" className={ui["error"]}>
          {failure}
        </div>
      ) : null}
      <section className={`${styles["panel"]} ${styles["detail"]}`} aria-label="Dados do projeto">
        <dl>
          <dt>Estado</dt>
          <dd>
            <StatusBadge status={p.status} />
          </dd>
          <dt>Objetivo</dt>
          <dd>{p.objetivo}</dd>
          <dt>Domínios</dt>
          <dd>{p.dominios.length ? p.dominios.join(", ") : <span className={styles["muted"]}>nenhum</span>}</dd>
          <dt>Problema</dt>
          <dd>
            {p.problema ? p.problema.resumo : <span className={styles["muted"]}>ainda não confirmado (a confirmação é feita no terminal)</span>}
          </dd>
          <dt>Sessões</dt>
          <dd>{p.n_sessoes}</dd>
          <dt>Hipóteses</dt>
          <dd>{p.n_hipoteses}</dd>
        </dl>
      </section>
      {confirm ? (
        <Dialog title={confirm === "concluido" ? "Concluir o projeto?" : "Arquivar o projeto?"} onClose={() => setConfirm(null)}>
          <p className={styles["muted"]}>
            {confirm === "concluido"
              ? "O projeto sai da lista de ativos. Você pode reativá-lo depois."
              : "Arquivado marca o projeto como não mais a explorar: novas pesquisas serão recusadas até desarquivar."}
          </p>
          <div className={dialogActions}>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={() => apply(confirm)}>
              Confirmar
            </Button>
          </div>
        </Dialog>
      ) : null}
    </>
  );
}
