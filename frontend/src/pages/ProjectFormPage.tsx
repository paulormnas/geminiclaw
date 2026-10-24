import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import { useCreateProject, useProject, useUpdateProject } from "../api/queries";
import { Button, Spinner, TextField } from "../components/ui";
import styles from "./pages.module.css";

const MAX_TITULO = 200;
const MAX_OBJETIVO = 20_000;

type Errors = Partial<Record<"titulo" | "objetivo", string>>;

function validate(titulo: string, objetivo: string): Errors {
  const errors: Errors = {};
  if (!titulo.trim()) errors.titulo = "O título é obrigatório.";
  else if (titulo.length > MAX_TITULO) errors.titulo = `O título tem no máximo ${MAX_TITULO} caracteres.`;
  if (!objetivo.trim()) errors.objetivo = "O objetivo é obrigatório.";
  else if (objetivo.length > MAX_OBJETIVO) errors.objetivo = `O objetivo tem no máximo ${MAX_OBJETIVO} caracteres.`;
  return errors;
}

export function ProjectFormPage() {
  const { projetoId } = useParams();
  const existing = useProject(projetoId);
  if (projetoId && existing.isPending) return <Spinner />;
  return (
    <ProjectForm
      projetoId={projetoId}
      initial={{ titulo: existing.data?.titulo ?? "", objetivo: existing.data?.objetivo ?? "" }}
    />
  );
}

function ProjectForm({ projetoId, initial }: { projetoId: string | undefined; initial: { titulo: string; objetivo: string } }) {
  const editing = Boolean(projetoId);
  const navigate = useNavigate();
  const create = useCreateProject();
  const update = useUpdateProject(projetoId ?? "");
  const [titulo, setTitulo] = useState(initial.titulo);
  const [objetivo, setObjetivo] = useState(initial.objetivo);
  const [errors, setErrors] = useState<Errors>({});
  const [generic, setGeneric] = useState<string | null>(null);

  const fail = (error: unknown) => {
    if (error instanceof ApiError && (error.campo === "titulo" || error.campo === "objetivo")) {
      setErrors({ [error.campo]: error.message });
    } else {
      setGeneric("Não foi possível salvar o projeto.");
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setGeneric(null);
    const found = validate(titulo, objetivo);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    if (editing && projetoId) {
      update.mutate({ titulo, objetivo }, { onSuccess: () => void navigate(`/p/${projetoId}`), onError: fail });
    } else {
      create.mutate(
        { titulo, objetivo, dominios: [] },
        { onSuccess: (r) => void navigate(`/p/${r.projeto_id}`), onError: fail },
      );
    }
  };

  return (
    <>
      <header className={styles["head"]}>
        <h1>{editing ? "Editar projeto" : "Novo projeto"}</h1>
      </header>
      <form className={styles["form"]} onSubmit={submit} noValidate>
        <TextField
          label="Título"
          value={titulo}
          maxLength={MAX_TITULO + 50}
          onChange={(e: { target: { value: string } }) => setTitulo(e.target.value)}
          error={errors.titulo}
          hint={`${titulo.length}/${MAX_TITULO}`}
        />
        <TextField
          label="Objetivo"
          multiline
          value={objetivo}
          onChange={(e: { target: { value: string } }) => setObjetivo(e.target.value)}
          error={errors.objetivo}
        />
        {generic ? <span role="alert">{generic}</span> : null}
        <div className={styles["actions"]}>
          <Button type="submit" variant="primary" loading={create.isPending || update.isPending}>
            {editing ? "Salvar" : "Criar projeto"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => void navigate(-1)}>
            Cancelar
          </Button>
        </div>
      </form>
    </>
  );
}
