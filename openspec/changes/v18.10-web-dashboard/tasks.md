# Tarefas: v18.10-web-dashboard

**Estado (2026-10-24):** especificada; aguarda aprovação do pesquisador.

## 0. Pré-requisitos
- [ ] 0.1 `v18.10-web-skeleton` mergeada; conferir no `geminiclaw_bench` (só leitura) os caminhos do grafo de cada rótulo até o projeto e os estados reais; divergência volta ao Arquiteto.

## 1. Backend
- [ ] 1.1 `deps.read_only_store` e `deps.read_only_connection`; teste estático de importações.
- [ ] 1.2 `queries/dashboard.py` e `routes/dashboard.py` (projeto e global), cache com relógio injetável, `WEB_DASHBOARD_CACHE_SECONDS` em `src/config.py` e `.env.example`.
- [ ] 1.3 Testes de unidade dos cenários da spec; integração com AGE real no banco de teste; regenerar o OpenAPI.

## 2. Frontend
- [ ] 2.1 Página do painel (projeto e global), cartões, barras SVG com tabela acessível, sessões recentes. Testes dos cenários da spec com MSW.

## 3. Validação final
- [ ] 3.1 `ruff`, `lint-imports`, `pytest -m "unit or integration"`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 3.2 Manual no Mac contra o `geminiclaw_bench`: painel global com 21 projetos; conferir 2 projetos contra contagens por `psql`.
- [ ] 3.3 Revisão nos 7 eixos; PR pelo GitHub App; linha **Estado**.
