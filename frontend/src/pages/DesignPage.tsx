import { Button, EmptyState, ErrorState, Spinner, StatusBadge, TextField } from "../components/ui";
import styles from "./pages.module.css";

const TOKENS = ["--bg", "--surface", "--surface-2", "--surface-3", "--primary", "--accent", "--pos", "--neg", "--warn", "--info", "--neu"];

/** Catálogo de estados dos componentes (design system, "página /_design"). */
export function DesignPage() {
  return (
    <>
      <header className={styles["head"]}>
        <h1>Design system</h1>
      </header>
      <section className={styles["panel"]} aria-label="Cores">
        <div className={styles["swatches"]}>
          {TOKENS.map((t) => (
            <div key={t} className={styles["swatch"]} style={{ background: `var(${t})` }}>
              {t}
            </div>
          ))}
        </div>
      </section>
      <section className={styles["panel"]} style={{ padding: 24, display: "grid", gap: 16 }} aria-label="Componentes">
        <div className={styles["actions"]}>
          <Button variant="primary">Primário</Button>
          <Button variant="signal">Sinal</Button>
          <Button>Secundário</Button>
          <Button variant="ghost">Discreto</Button>
          <Button variant="danger">Parar</Button>
          <Button disabled>Desabilitado</Button>
          <Button loading>Carregando</Button>
        </div>
        <div className={styles["actions"]}>
          {["ativo", "pausado", "concluido", "arquivado"].map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
        </div>
        <TextField label="Campo com erro" error="O título é obrigatório." defaultValue="" />
        <Spinner />
        <EmptyState title="Vazio">Nenhum item.</EmptyState>
        <ErrorState message="Falha de exemplo." onRetry={() => undefined} />
      </section>
    </>
  );
}
