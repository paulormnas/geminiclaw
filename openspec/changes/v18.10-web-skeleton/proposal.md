# Proposta: Esqueleto da Interface Web (autenticação, estáticos e CRUD de projetos)

**ID:** `v18.10-web-skeleton` · **Versão:** V18.10 · **Capacidade:** `web-interface` (nova)
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §1–§5, §6.1, §7, §8; ADR 024 §3 (camadas); ADR 015 §11; ADR 019 (proveniência: sem exclusão física)
**Depende de:** nada novo (usa `src/knowledge/projects.py`, `GraphStore`, `src/db.py`). As mudanças `v18.10-web-dashboard`, `-artifacts`, `-graph` e `-chat` dependem desta.

## Por quê

O pesquisador quer acompanhar e conduzir os projetos fora do terminal. Antes de qualquer tela de dados, é preciso o servidor local autenticado, o frontend com tokens e testes, e a primeira funcionalidade de ponta a ponta: o CRUD de projetos.

## O que muda

- **Novo:** pacote `src/web/` (FastAPI): `app.py` (fábrica da aplicação), `auth.py` (senha argon2id, sessões em memória, CSRF, bloqueio de tentativas), `security.py` (cabeçalhos, `Host`/`Origin`), `routes/projects.py`, `routes/session.py` (login, logout, quem sou), `static.py` (SPA de `frontend/dist`, `index.html` como fallback de rota), `__main__.py` (Uvicorn em `WEB_HOST`, recusa endereço fora do loopback), `password.py` (gera o hash sem eco).
- **Novo:** `update_project(store, projeto_id, *, titulo=None, objetivo=None, status=None)` em `src/knowledge/projects.py` (ator `pesquisador`, mesmas validações do `create_project`).
- **Novo:** `frontend/` (Vite + React + TypeScript estrito, `pnpm`): tokens, layout com barra lateral e seletor de projeto, tela de login, telas de projetos (lista, detalhe, criar, editar, concluir/pausar/reativar), cliente da API tipado por `openapi-typescript`, testes Vitest + Testing Library + MSW.
- **Modificado:** `pyproject.toml` (dependências e contrato `cli | web`), `.env.example`, `src/config.py`, `.gitignore` (`frontend/node_modules`, `frontend/dist`, `frontend/coverage`), `AGENTS.md` §1/§6/§7/§9, `.agents/rules/frontend-dev.md`, `.agents/rules/designer.md`, `.agents/workflows/commit.md` e `run-tests.md` (comandos do frontend), `README.md` (como rodar).
- **Novo (decisão do pesquisador, 2026-10-24):** estado `arquivado` do `Projeto`, que marca projeto que não deve mais ser explorado: some das listas por padrão, recusa nova pesquisa e retomada (pela web e pela CLI) e pode ser desarquivado. Substitui a exclusão.
- **Fora do escopo:** painel, artefatos, grafo e conversa (mudanças próprias); exclusão física de projeto; confirmação do Problema (decisão reservada; fica na conversa ou na CLI); mais de um usuário.

## Impacto

- **Código:** só arquivos novos, mais `projects.py` (função nova) e configuração. Nada no orquestrador, nos agentes ou na sessão.
- **Contratos:** API `/api/session/*` e `/api/projects/*` (design §2); esquema OpenAPI versionado em `frontend/src/api/schema.d.ts`.
- **Schema:** nenhum relacional. No grafo, só o valor novo `arquivado` no `enum` de `Projeto.status` (sem migração: nós existentes continuam válidos). `list_projects` aceita o filtro novo; o início e a retomada de pesquisa (`src/cli/session_start.py`) recusam projeto arquivado.
- **Custo:** nenhuma chamada de LLM.

## Aprovações necessárias

- **Dependências novas (backend):** `fastapi`, `uvicorn`, `argon2-cffi` (`uv add`).
- **Dependências novas (frontend, `pnpm`):** `react`, `react-dom`, `react-router`, `@tanstack/react-query`, `@fontsource-variable/plus-jakarta-sans`, `@fontsource-variable/jetbrains-mono`; dev: `vite`, `@vitejs/plugin-react`, `typescript`, `vitest`, `@vitest/coverage-v8`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `msw`, `openapi-typescript`, `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`.
- **`AGENTS.md`:** §1, §6, §7 e §9 (ADR 027 §8).
- **Regras e workflows:** `frontend-dev.md`, `designer.md`, `commit.md`, `run-tests.md`.
- **Escrita no grafo:** criar e editar nós `Projeto` pela web (aprovada pelo pesquisador em 2026-10-24).
- **Vocabulário do grafo:** `Projeto.status` ganha `arquivado` em `src/knowledge/schema.py` (aditivo; avisar a trilha 1 antes do merge).
