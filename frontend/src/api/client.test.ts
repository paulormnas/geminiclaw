import { http, HttpResponse } from "msw";

import { server } from "../test/server";
import { api, ApiError, setCsrfToken } from "./client";

describe("api client", () => {
  it("envia o token CSRF só em métodos que mudam estado", async () => {
    const seen: Record<string, string | null> = {};
    server.use(
      http.get("/api/x", ({ request }) => {
        seen["get"] = request.headers.get("x-csrf-token");
        return HttpResponse.json({});
      }),
      http.post("/api/x", ({ request }) => {
        seen["post"] = request.headers.get("x-csrf-token");
        return HttpResponse.json({});
      }),
    );
    setCsrfToken("abc");
    await api("/api/x");
    await api("/api/x", { method: "POST", body: { a: 1 } });
    expect(seen).toEqual({ get: null, post: "abc" });
  });

  it("converte erro da API em ApiError com campo", async () => {
    server.use(
      http.post("/api/y", () =>
        HttpResponse.json({ erro: "campo_invalido", mensagem: "Campo 'titulo' é obrigatório.", campo: "titulo" }, { status: 422 }),
      ),
    );
    const error = await api("/api/y", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, erro: "campo_invalido", campo: "titulo" });
  });

  it("204 devolve undefined", async () => {
    server.use(http.post("/api/z", () => new HttpResponse(null, { status: 204 })));
    await expect(api("/api/z", { method: "POST" })).resolves.toBeUndefined();
  });
});
