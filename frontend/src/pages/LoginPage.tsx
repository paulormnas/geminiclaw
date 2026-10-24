import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useLogin } from "../api/queries";
import { Button, TextField } from "../components/ui";
import styles from "./pages.module.css";

function message(error: unknown): string | null {
  if (!(error instanceof ApiError)) return error ? "Não foi possível entrar." : null;
  if (error.erro === "bloqueado") {
    const seconds = Number(error.extra["tentar_em_segundos"] ?? 0);
    return `Muitas tentativas. Tente de novo em ${Math.ceil(seconds / 60)} min.`;
  }
  if (error.erro === "sessoes_esgotadas") return "Há sessões demais abertas; saia de uma delas.";
  if (error.status === 401) return "Senha incorreta.";
  return "Não foi possível entrar.";
}

export function LoginPage() {
  const [senha, setSenha] = useState("");
  const login = useLogin();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate(senha);
  };
  return (
    <div className={styles["login"]}>
      <form className={styles["loginCard"]} onSubmit={submit}>
        <h1>Bancada</h1>
        <TextField
          label="Senha"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={senha}
          onChange={(e: { target: { value: string } }) => setSenha(e.target.value)}
          error={message(login.error)}
        />
        <Button variant="primary" type="submit" loading={login.isPending} disabled={!senha}>
          Entrar
        </Button>
      </form>
    </div>
  );
}
