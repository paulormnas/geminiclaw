# Proposta: Painel com o Resumo dos Bancos

**ID:** `v18.10-web-dashboard` · **Versão:** V18.10 · **Capacidade:** `web-interface`
**ADRs de origem:** [ADR 027](../../../docs/decisions/adr_027_interface_web.md) §6.2, §6.4; ADR 015 (rótulos e estados); ADR 026 (`RegistroResultado`)
**Depende de:** `v18.10-web-skeleton`. Pode ser implementada em paralelo com `v18.10-web-artifacts` e `v18.10-web-graph`.

## Por quê

O pesquisador quer ver de relance o que cada projeto acumulou (hipóteses e seus estados, experimentos, resultados, registros, abordagens, sessões, custo) sem montar consultas na CLI.

## O que muda

- **Novo:** `src/web/routes/dashboard.py` e `src/web/queries/dashboard.py` (consultas fixas, só leitura): `GET /api/dashboard` (global) e `GET /api/projects/{id}/dashboard`.
- **Novo:** página Painel no frontend: cartões de contagem, barras SVG por estado, tabela de sessões recentes, custo e tokens.
- **Fora do escopo:** séries temporais, comparação entre projetos em gráfico, exportação.

## Impacto

- **Código:** só arquivos novos em `src/web/` e `frontend/src/pages/dashboard/`.
- **Schema:** nenhum. Leitura do grafo por `ReadOnlyGraphStore.read_query` (papel `knowledge_reader`) e de `agent_sessions`, `token_usage`, `session_events` em transação somente leitura.
- **Custo:** nenhuma chamada de LLM.

## Aprovações necessárias

Nenhuma (sem dependência, schema ou arquivo de governança novos).
