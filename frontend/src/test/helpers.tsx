import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { setCsrfToken } from "../api/client";
import { makeQueryClient } from "../App";
import { AppRoutes } from "../routes";
import { server } from "./server";

export const PROJECT = {
  projeto_id: "11111111-1111-4111-8111-111111111111",
  titulo: "Íris",
  status: "ativo",
  criado_em: "2026-10-24T10:00:00Z",
};

export const DETAIL = {
  ...PROJECT,
  objetivo: "Classificar espécies",
  dominios: ["ml"],
  problema: null,
  n_sessoes: 2,
  n_hipoteses: 3,
};

export function authenticated(csrf = "csrf-1") {
  setCsrfToken(null);
  server.use(
    http.get("/api/session", () => HttpResponse.json({ autenticado: true, expira_em: 1, csrf_token: csrf })),
  );
}

export function unauthenticated() {
  server.use(http.get("/api/session", () => HttpResponse.json({ erro: "nao_autenticado" }, { status: 401 })));
}

export function renderApp(path = "/", ui: ReactElement | null = null) {
  const client = makeQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui ?? <AppRoutes />}</MemoryRouter>
    </QueryClientProvider>,
  );
}
