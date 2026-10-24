import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "../test/server";
import { authenticated, DETAIL, PROJECT, renderApp, unauthenticated } from "../test/helpers";

describe("login", () => {
  it("sem sessão mostra o login e, ao entrar, vai para os projetos", async () => {
    unauthenticated();
    server.use(
      http.post("/api/session/login", () => {
        server.use(http.get("/api/session", () => HttpResponse.json({ autenticado: true, expira_em: 1, csrf_token: "t" })));
        return HttpResponse.json({ csrf_token: "t", expira_em: 1 });
      }),
      http.get("/api/projects", () => HttpResponse.json([])),
    );
    renderApp("/projetos");
    await userEvent.type(await screen.findByLabelText("Senha"), "segredo");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Projetos" })).toBeInTheDocument();
  });

  it("senha errada mostra o erro", async () => {
    unauthenticated();
    server.use(http.post("/api/session/login", () => HttpResponse.json({ erro: "credenciais_invalidas" }, { status: 401 })));
    renderApp("/");
    await userEvent.type(await screen.findByLabelText("Senha"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Senha incorreta.");
  });

  it("bloqueio mostra o tempo", async () => {
    unauthenticated();
    server.use(
      http.post("/api/session/login", () => HttpResponse.json({ erro: "bloqueado", tentar_em_segundos: 300 }, { status: 429 })),
    );
    renderApp("/");
    await userEvent.type(await screen.findByLabelText("Senha"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("5 min");
  });
});

describe("lista de projetos", () => {
  it("lista, filtra por título e abre o detalhe", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () =>
        HttpResponse.json([PROJECT, { ...PROJECT, projeto_id: "22222222-2222-4222-8222-222222222222", titulo: "Wine" }]),
      ),
    );
    renderApp("/projetos");
    expect(await screen.findByRole("link", { name: "Íris" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Buscar por título"), "wine");
    expect(screen.queryByRole("link", { name: "Íris" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wine" })).toBeInTheDocument();
  });

  it("vazio convida a criar", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([])));
    renderApp("/projetos");
    expect(await screen.findByText("Nenhum projeto ainda")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Criar o primeiro projeto" })).toBeInTheDocument();
  });

  it("erro permite tentar de novo", async () => {
    authenticated();
    let calls = 0;
    server.use(
      http.get("/api/projects", () => (++calls === 1 ? HttpResponse.json({ erro: "interno" }, { status: 500 }) : HttpResponse.json([PROJECT]))),
    );
    renderApp("/projetos");
    await userEvent.click(await screen.findByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("link", { name: "Íris" })).toBeInTheDocument();
  });

  it("filtro de estado consulta a API com o status", async () => {
    authenticated();
    const urls: string[] = [];
    server.use(
      http.get("/api/projects", ({ request }) => {
        urls.push(new URL(request.url).search);
        return HttpResponse.json([]);
      }),
    );
    renderApp("/projetos");
    await screen.findByText("Nenhum projeto ainda");
    await userEvent.selectOptions(screen.getByLabelText("Estado"), "arquivado");
    await waitFor(() => expect(urls).toContain("?status=arquivado"));
  });
});

describe("detalhe", () => {
  const url = `/p/${PROJECT.projeto_id}`;
  const base = () => server.use(
    http.get("/api/projects", () => HttpResponse.json([PROJECT])),
    http.get(`/api/projects/${PROJECT.projeto_id}`, () => HttpResponse.json(DETAIL)),
  );

  it("mostra os dados e o Problema não confirmado", async () => {
    authenticated();
    base();
    renderApp(url);
    expect(await screen.findByRole("heading", { name: "Íris" })).toBeInTheDocument();
    expect(screen.getByText("Classificar espécies")).toBeInTheDocument();
    expect(screen.getByText(/ainda não confirmado/)).toBeInTheDocument();
  });

  it("projeto inexistente", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([])),
      http.get("/api/projects/nada", () => HttpResponse.json({ erro: "projeto_nao_encontrado" }, { status: 404 })),
    );
    renderApp("/p/nada");
    expect(await screen.findByText("Projeto não encontrado.")).toBeInTheDocument();
  });

  it("concluir pede confirmação e envia PATCH com o CSRF", async () => {
    authenticated("csrf-9");
    base();
    let sent: { csrf: string | null; body: unknown } | null = null;
    server.use(
      http.patch(`/api/projects/${PROJECT.projeto_id}`, async ({ request }) => {
        sent = { csrf: request.headers.get("x-csrf-token"), body: await request.json() };
        return HttpResponse.json({ ...DETAIL, status: "concluido" });
      }),
    );
    renderApp(url);
    await userEvent.click(await screen.findByRole("button", { name: "Concluir" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(sent).toEqual({ csrf: "csrf-9", body: { status: "concluido" } }));
    expect(await screen.findByText("Concluído")).toBeInTheDocument();
  });

  it("Escape fecha o diálogo sem alterar", async () => {
    authenticated();
    base();
    renderApp(url);
    await userEvent.click(await screen.findByRole("button", { name: "Arquivar" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("409 mostra as pesquisas em execução", async () => {
    authenticated();
    base();
    server.use(
      http.patch(`/api/projects/${PROJECT.projeto_id}`, () =>
        HttpResponse.json({ erro: "pesquisa_em_execucao", sessoes: [{ session_id: "s", alias: "iris-04" }] }, { status: 409 }),
      ),
    );
    renderApp(url);
    await userEvent.click(await screen.findByRole("button", { name: "Pausar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("iris-04");
  });

  it("arquivado só oferece desarquivar", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([])),
      http.get(`/api/projects/${PROJECT.projeto_id}`, () => HttpResponse.json({ ...DETAIL, status: "arquivado" })),
    );
    renderApp(url);
    expect(await screen.findByRole("button", { name: "Desarquivar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Concluir" })).not.toBeInTheDocument();
  });
});

describe("formulário", () => {
  it("valida título e objetivo antes de enviar", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([])));
    let posted = false;
    server.use(http.post("/api/projects", () => ((posted = true), HttpResponse.json({ projeto_id: "x" }, { status: 201 }))));
    renderApp("/projetos/novo");
    await userEvent.click(await screen.findByRole("button", { name: "Criar projeto" }));
    expect(await screen.findByText("O título é obrigatório.")).toBeInTheDocument();
    expect(screen.getByText("O objetivo é obrigatório.")).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  it("título acima de 200 caracteres", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([])));
    renderApp("/projetos/novo");
    await userEvent.click(await screen.findByLabelText("Título"));
    await userEvent.paste("x".repeat(201));
    await userEvent.type(screen.getByLabelText("Objetivo"), "ok");
    await userEvent.click(screen.getByRole("button", { name: "Criar projeto" }));
    expect(await screen.findByText(/no máximo 200/)).toBeInTheDocument();
  });

  it("erro do servidor aparece no campo", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([])),
      http.post("/api/projects", () =>
        HttpResponse.json({ erro: "campo_invalido", mensagem: "Campo 'titulo' excede 200 caracteres.", campo: "titulo" }, { status: 422 }),
      ),
    );
    renderApp("/projetos/novo");
    await userEvent.type(await screen.findByLabelText("Título"), "Íris");
    await userEvent.type(screen.getByLabelText("Objetivo"), "Algo");
    await userEvent.click(screen.getByRole("button", { name: "Criar projeto" }));
    expect(await screen.findByText("Campo 'titulo' excede 200 caracteres.")).toBeInTheDocument();
  });

  it("cria e navega para o detalhe", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([])),
      http.post("/api/projects", () => HttpResponse.json({ projeto_id: PROJECT.projeto_id }, { status: 201 })),
      http.get(`/api/projects/${PROJECT.projeto_id}`, () => HttpResponse.json(DETAIL)),
    );
    renderApp("/projetos/novo");
    await userEvent.type(await screen.findByLabelText("Título"), "Íris");
    await userEvent.type(screen.getByLabelText("Objetivo"), "Classificar espécies");
    await userEvent.click(screen.getByRole("button", { name: "Criar projeto" }));
    expect(await screen.findByRole("heading", { name: "Íris" })).toBeInTheDocument();
  });

  it("edição carrega os valores atuais", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([PROJECT])),
      http.get(`/api/projects/${PROJECT.projeto_id}`, () => HttpResponse.json(DETAIL)),
    );
    renderApp(`/p/${PROJECT.projeto_id}/editar`);
    await waitFor(() => expect(screen.getByLabelText("Título")).toHaveValue("Íris"));
    expect(screen.getByLabelText("Objetivo")).toHaveValue("Classificar espécies");
  });
});

describe("layout", () => {
  it("tema: escolher escuro aplica o atributo e persiste", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([])));
    renderApp("/projetos");
    await userEvent.click(await screen.findByRole("button", { name: "Escuro" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("bancada-theme")).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Sistema" }));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("seções futuras aparecem desabilitadas", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([])));
    renderApp("/projetos");
    const grafo = await screen.findByText("Grafo");
    expect(grafo.closest("[aria-disabled='true']")).not.toBeNull();
  });

  it("Ctrl+K abre a paleta e navega", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([PROJECT])));
    renderApp("/projetos");
    await screen.findByRole("heading", { name: "Projetos" });
    await userEvent.keyboard("{Control>}k{/Control}");
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Buscar"), "novo");
    await userEvent.click(within(dialog).getByRole("button", { name: "Novo projeto" }));
    expect(await screen.findByRole("heading", { name: "Novo projeto" })).toBeInTheDocument();
  });

  it("seletor de projeto leva ao detalhe", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([PROJECT])),
      http.get(`/api/projects/${PROJECT.projeto_id}`, () => HttpResponse.json(DETAIL)),
    );
    renderApp("/projetos");
    await screen.findByRole("option", { name: "Íris" });
    await userEvent.selectOptions(screen.getByLabelText("Projeto"), PROJECT.projeto_id);
    expect(await screen.findByRole("heading", { name: "Íris" })).toBeInTheDocument();
  });

  it("sair volta ao login", async () => {
    authenticated();
    server.use(
      http.get("/api/projects", () => HttpResponse.json([])),
      http.post("/api/session/logout", () => new HttpResponse(null, { status: 204 })),
    );
    renderApp("/projetos");
    await userEvent.click(await screen.findByRole("button", { name: "Sair" }));
    expect(await screen.findByLabelText("Senha")).toBeInTheDocument();
  });

  it("página /_design lista os estados", async () => {
    authenticated();
    server.use(http.get("/api/projects", () => HttpResponse.json([])));
    renderApp("/_design");
    expect(await screen.findByRole("heading", { name: "Design system" })).toBeInTheDocument();
    expect(screen.getByText("Algo deu errado")).toBeInTheDocument();
  });
});
