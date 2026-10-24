# Proposta: Containers da Web e Lançador de Sessões no Host

**ID:** `v18.10-web-containers` · **Versão:** V18.10 · **Capacidades:** `web-interface`, `session-launcher` (nova)
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §9 (decisão do pesquisador, 2026-10-24); ADR 014 (sandbox e processos locais); ADR 023 (sessão em processo próprio, arquivo de lançamento); ADR 024 (camadas)
**Depende de:** `v18.10-web-skeleton`; idealmente depois de painel, artefatos, grafo e configurações (os volumes cobrem o que eles leem e gravam). **Antes de** `v18.10-web-chat`, que passa a iniciar pesquisa pela fila desta mudança.

## Por quê

O pesquisador quer subir tudo com um comando, ter o mesmo build em qualquer máquina e isolar o processo web, sem um container por sessão de pesquisa (cada execução de código já tem o seu sandbox; containers paralelos por exploração pesariam no futuro). O backend web em container não pode iniciar sessões: precisaria do socket do Docker, que equivale a root no host e anula o isolamento do sandbox (ADR 027, alternativa D2).

## O que muda

- **Novo:** container `geminiclaw-web` (FastAPI) e container `geminiclaw-web-frontend` (Node, build com `pnpm`), no perfil `web` do `docker-compose.yml`, na `geminiclaw-net`.
- **Novo:** tabela `session_start_requests` (fila de pedidos de início) e migração `scripts/migrations/v18_10_001_session_start_requests.sql`, também em `scripts/init_db.sql`.
- **Novo:** pacote `src/launcher/` (camada de topo, ao lado de `cli` e `web`): processo no host (`uv run python -m src.launcher`) que assume pedidos da fila, faz as mesmas verificações do REPL e inicia a sessão pelo `LaunchSpec`/`spawn_session` existentes.
- **Movido (era a seção 0.2 de `v18.10-web-chat`, só a parte de iniciar pesquisa):** preparar e lançar pesquisa sai de `src/cli/session_start.py` para `src/interaction/research.py`, usado pelo REPL e pelo lançador.
- **Novo:** `scripts/up.sh` e `scripts/down.sh` (infra + web + lançador com um comando).
- **Fora do escopo:** sessões, Researcher ou orquestrador em container; acesso ao socket do Docker por qualquer container novo; o chat em si (`v18.10-web-chat`).

## Impacto

- **Schema:** uma tabela nova, aditiva e idempotente; nada existente muda. **Aprovado pelo pesquisador em 2026-10-24.** Trilha 1 avisada (o Pi não roda a web nem o lançador).
- **Infra:** `docker-compose.yml` ganha dois serviços sob perfil (quem não usa `--profile web` não vê diferença); `containers/web/Dockerfile` e `containers/web-frontend/Dockerfile` novos. **Aprovado pelo pesquisador em 2026-10-24.**
- **Código:** `src/launcher/`, `src/interaction/research.py`, `src/web/` (rota que grava o pedido, estado do lançador), `src/config.py` (`LAUNCHER_*`), contrato de camadas.
- **REPL:** comportamento igual; só passa a chamar `src/interaction/research.py`.
