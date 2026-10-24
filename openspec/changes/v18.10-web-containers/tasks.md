# Tarefas: v18.10-web-containers

**Estado (2026-10-24):** especificada; schema e `docker-compose.yml` aprovados pelo pesquisador; aguarda aprovação da mudança.

## 0. Pré-requisitos
- [ ] 0.1 `v18.10-web-skeleton` mergeada; conferir a spec contra `dev` (`src/session/launcher.py`, `src/cli/session_start.py`, batimentos existentes) e decidir a Questão 1.
- [ ] 0.2 Movimentação de preparar/lançar pesquisa de `src/cli/session_start.py` para `src/interaction/research.py` (só mover; perguntas e banner ficam no REPL); contrato `"cli | web | launcher"` acima de `"interaction"`; `lint-imports` e suíte verdes antes de seguir.

## 1. Fila
- [ ] 1.1 `scripts/migrations/v18_10_001_session_start_requests.sql` (idempotente) e `scripts/init_db.sql`; aplicar no `geminiclaw` do Mac; avisar a trilha 1. Testes de integração: índice único por projeto, `CHECK`s, `SKIP LOCKED` com dois consumidores.
- [ ] 1.2 `src/launcher/queue.py`: criar (web), assumir, concluir, expirar, cancelar, `NOTIFY`/`LISTEN`. Testes de unidade com relógio injetável.

## 2. Lançador
- [ ] 2.1 `src/launcher/__main__.py` e `service.py`: trava, laço, verificações via `src/interaction/research.py`, `LaunchSpec` + `spawn_session`, estados finais, TERM limpo, pedido órfão → `falhou`. Testes dos cenários da spec com `spawn` falso; um de integração com processo real de sessão simulada.
- [ ] 2.2 `LAUNCHER_POLL_SECONDS`, `LAUNCHER_REQUEST_TTL_SECONDS`, `LAUNCHER_CLAIM_TIMEOUT_SECONDS` em `src/config.py` e `.env.example`; batimento conforme a Questão 1.
- [ ] 2.3 Rotas da web: `POST /api/projects/{id}/research` grava pedido; `GET /api/start-requests/{id}`, `POST .../cancel`; `GET /api/launcher` (presente/ausente); `GET /api/health`. Testes dos cenários; regenerar o OpenAPI.

## 3. Containers
- [ ] 3.1 `containers/web/Dockerfile` e `containers/web-frontend/Dockerfile` (bases por digest, não root); `.dockerignore`.
- [ ] 3.2 Serviços `geminiclaw-web` e `geminiclaw-web-frontend` no perfil `web` do `docker-compose.yml`, volumes e limites do design §4; `WEB_IN_CONTAINER` em `src/web/__main__.py`. Testes: recusa sem `/.dockerenv`; teste `container` com `docker inspect` (usuário, `ReadonlyRootfs`, sem `docker.sock`, porta só em 127.0.0.1).
- [ ] 3.3 `scripts/up.sh` e `scripts/down.sh` (idempotentes, nada destrutivo).

## 4. Frontend
- [ ] 4.1 Aviso "lançador ausente" e botão Nova pesquisa desabilitado; estados do pedido (pendente, recusado com diálogo de confirmação, lançado, falhou, expirado). Testes com MSW.

## 5. Documentação e validação
- [ ] 5.1 `README.md`, `run_project.md`, `clean.md` (tabela nova), `AGENTS.md` §6 (`scripts/up.sh`).
- [ ] 5.2 `uv run ruff check .`, `uv run lint-imports`, `uv run pytest -m "unit or integration" -v`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 5.3 Manual no Mac: `scripts/up.sh` do zero; login pela web; pedido recusado por outra pesquisa viva e confirmado; sessão `semi` curta iniciada pelo lançador (com confirmação do pesquisador antes de gastar tokens); `scripts/down.sh`.
- [ ] 5.4 Parecer do Analista de Segurança; revisão nos 7 eixos; PR pelo GitHub App; linha **Estado**; o Arquiteto atualiza o ADR 027.
