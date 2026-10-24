# Tarefas: v18.10-web-graph

**Estado (2026-10-24):** especificada; aguarda aprovação do pesquisador.

## 0. Pré-requisitos
- [ ] 0.1 `v18.10-web-skeleton` mergeada; medir no `geminiclaw_bench` (só leitura) o tempo e o tamanho de `project_subgraph` do maior projeto e propor o padrão de `WEB_GRAPH_MAX_NODES`.

## 1. Backend
- [ ] 1.1 `queries/graph.py` (esquema, subgrafo, filtros, prioridade e omitidos, detalhe, vizinhos, auditoria) e variáveis `WEB_GRAPH_*` em `src/config.py` e `.env.example`.
- [ ] 1.2 `routes/graph.py`. Testes de unidade dos cenários com `InMemoryGraphStore`; integração com AGE real; regenerar o OpenAPI.

## 2. Frontend
- [ ] 2.1 `pnpm --dir frontend add cytoscape`; página do grafo, filtros, legenda, detalhe, lista acessível, expansão. Testes com MSW (Cytoscape em modo `headless` no jsdom).

## 3. Validação final
- [ ] 3.1 `ruff`, `lint-imports`, `pytest -m "unit or integration"`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 3.2 Manual no Mac com 3 projetos do `geminiclaw_bench`, inclusive o maior.
- [ ] 3.3 Revisão nos 7 eixos; PR pelo GitHub App; linha **Estado**.
