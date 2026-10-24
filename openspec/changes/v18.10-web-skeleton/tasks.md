# Tarefas: v18.10-web-skeleton

**Estado (2026-10-24):** implementada em `feat/web-skeleton`; falta só a validação manual 4.2 (escreve no banco `geminiclaw`) e a revisão pós-merge. Desvios da spec: `GET /api/session` também devolve `csrf_token` (recarregar a página perde o token em memória); `pnpm` 10.34 e TypeScript 5 (o `openapi-typescript` não roda no TypeScript 7); `scripts/up.sh`/containers ficam em `v18.10-web-containers`; recusa de arquivado também em `retomar` (`src/session/resume.py`); `pnpm-workspace.yaml` bloqueia scripts de instalação.

## 0. Pré-requisitos
- [x] 0.1 Aprovação do ADR 027, desta mudança e das "Aprovações necessárias"; respostas às Questões em aberto do design. Conferir a spec contra `dev` (projetos, `GraphStore`, auditoria, sessões vivas por projeto).

## 1. Backend
- [x] 1.1 `uv add fastapi uvicorn argon2-cffi`; contrato `cli | web` e `forbidden` no `pyproject.toml`; `uv run lint-imports`.
- [x] 1.2 `src/config.py` e `.env.example` com as variáveis do design §4 e validações (exigidas só ao iniciar `src.web`).
- [x] 1.3 `src/web/auth.py` e `security.py` (senha, sessões, bloqueio, CSRF, `Host`/`Origin`, cabeçalhos), com relógio injetável. Testes de unidade dos cenários de login, bloqueio, CSRF, origem, host, cabeçalhos e erro interno.
- [x] 1.4 `src/web/__main__.py` (recusa fora do loopback), `password.py`, `static.py`, `openapi.py`. Testes: endereço externo recusado, sem hash, SPA, build ausente, esquema versionado.
- [x] 1.5 `update_project` em `src/knowledge/projects.py` e `routes/projects.py`. Testes de unidade com `InMemoryGraphStore` (criar, título vazio, editar, concluir, 409 com sessão viva, sem DELETE, 404) e um de integração com AGE real no banco de teste.
- [x] 1.6 `arquivado` em `Projeto.status` (`src/knowledge/schema.py`), filtro em `list_projects` e recusa em `src/cli/session_start.py`; avisar a trilha 1. Testes: arquivar, arquivado recusa pesquisa.

## 2. Frontend
- [x] 2.1 `frontend/` com `pnpm` (`packageManager`, `.nvmrc` LTS), Vite, React, TypeScript estrito, ESLint (`react/no-danger` erro), Vitest com cobertura ≥ 70%.
- [x] 2.2 Tokens, tema, layout, barra lateral, seletor de projeto, componentes base com estados. Testes: contraste, tema, teclado.
- [x] 2.3 Cliente da API tipado (`gen:api`), login, projetos (lista, detalhe, formulário). Testes: login redireciona, erro de campo, estados, CSRF enviado.

## 3. Documentação e governança
- [x] 3.1 `AGENTS.md` §1/§6/§7/§9, `frontend-dev.md`, `designer.md`, `commit.md`, `run-tests.md`, `README.md` (como gerar o hash, buildar e rodar; `tailscale serve`), `.gitignore`.

## 4. Validação final
- [x] 4.1 `uv run ruff check .`, `uv run lint-imports`, `uv run pytest -m "unit or integration" -v`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 4.2 Validação manual no Mac: login, criar/editar/concluir no banco `geminiclaw` (dev); listar os 21 projetos do `geminiclaw_bench` sem escrever nele.
- [x] 4.3 Revisão nos 7 eixos; PR para `dev` pelo GitHub App citando esta mudança; atualizar a linha **Estado**.
