import type { components } from "./schema";

export type ProjectItem = components["schemas"]["ProjectItem"];
export type ProjectDetail = components["schemas"]["ProjectDetailOut"];
export type ProjectCreate = components["schemas"]["ProjectCreate"];
export type ProjectPatch = components["schemas"]["ProjectPatch"];
export type SessionInfo = components["schemas"]["SessionOut"];
export type LoginResult = components["schemas"]["LoginOut"];

export class ApiError extends Error {
  readonly status: number;
  readonly erro: string;
  readonly campo: string | null;
  readonly extra: Record<string, unknown>;

  constructor(status: number, body: Record<string, unknown>) {
    const mensagem = typeof body["mensagem"] === "string" ? body["mensagem"] : "";
    super(mensagem || `Erro ${status}`);
    this.status = status;
    this.erro = typeof body["erro"] === "string" ? body["erro"] : "erro";
    this.campo = typeof body["campo"] === "string" ? body["campo"] : null;
    this.extra = body;
  }
}

/** O token CSRF vive só em memória (nunca em storage); `GET /api/session` o devolve ao recarregar a página. */
let csrfToken: string | null = null;
export const setCsrfToken = (token: string | null): void => {
  csrfToken = token;
};

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (response.status === 204) return undefined as T;
  let payload: Record<string, unknown> = {};
  try {
    payload = (await response.json()) as Record<string, unknown>;
  } catch {
    /* corpo vazio ou não JSON: o status basta */
  }
  if (!response.ok) throw new ApiError(response.status, payload);
  return payload as T;
}
