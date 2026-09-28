# Proposta: Acesso do Pesquisador ao Grafo pela CLI

**ID:** `v17-graph-cli` · **Versão:** V17 · **Capacidade:** `graph-cli`
**ADRs de origem:** [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §11;
discussão, questão 7

## Por quê

O pesquisador precisa ver o grafo do projeto em que atua e poder corrigi-lo. Decisões:
**visualizar é um comando simples da CLI, sem agente e sem LLM**; **alterar é sempre com o
Curator**, que traduz o pedido, mostra a alteração proposta e só aplica após confirmação; o
pesquisador **não tem acesso direto ao banco**. Um frontend visual virá no futuro.

## O que muda

- **Novo:** `geminiclaw graph show` e `geminiclaw graph node <id>` — consultas fixas,
  somente-leitura, com filtros e formatos de saída (texto, tabela, JSON, Mermaid).
- **Novo:** `geminiclaw graph edit "<pedido>"` — o Curator, em modo de edição, produz uma
  lista de **operações tipadas propostas** (sem aplicar); a CLI valida, exibe a diferença e
  aplica somente após confirmação, com autoria `pesquisador`.
- **Fora do escopo:** frontend visual; comandos de vocabulário (`v17-controlled-vocabulary`).

## Impacto

- **Código:** `src/cli.py`, `src/knowledge/graph_views.py` (novo),
  `src/knowledge/change_proposals.py` (novo), `agents/curator/agent.py` (modo de edição).

## Aprovações necessárias

Nenhuma alteração de schema ou infraestrutura.
