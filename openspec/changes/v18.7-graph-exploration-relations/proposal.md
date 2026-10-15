# Proposta: Relações de Exploração no Grafo (papel do experimento, hipótese do sistema, PREPARA, REFERENCIA_DE)

**ID:** `v18.7-graph-exploration-relations` · **Versão:** V18.7 · **Capacidade:** `knowledge-graph` (reutilizada de `v17-graph-store`)
**ADRs de origem:** [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §2 (três papéis de `Experimento`), §3 (ligações derivadas, hipótese do sistema, chave estruturada, referência R fixada, ciclo de vida com `abandonada_por`), §4 (`DERIVADA_DE` entre hipóteses, transições de status de hipóteses concluídas) e §9 (compatibilidade); emenda ao [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §2, §4 e §5 registrada no ADR 021.
**Depende de:** nenhuma mudança em aberto (V18.6 arquivada). É pré-requisito de [`v18.7-hypothesis-linking`](../v18.7-hypothesis-linking/proposal.md), que escreve os nós e arestas definidos aqui. Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.

## Por quê

O ADR 021 troca o bloqueio por falta de `hypothesis_ref` pelo registro da ligação: toda execução se liga a um `Problema` e todo teste a uma `Hipotese`, e o que o plano não declara o sistema deriva. O schema do grafo (`src/knowledge/schema.py`) ainda não tem onde guardar isso:

| O que o ADR 021 exige | Estado atual do código |
|---|---|
| `Experimento.papel` (`teste` / `preparacao` / `referencia`) | `Experimento` não tem a propriedade (`schema.py:218-238`) |
| `Hipotese.origem = "sistema"` | enum só aceita `pesquisador`, `researcher`, `curator`, `oportunidade` (`schema.py:186`) |
| Chave estruturada `(problema, abordagem, metrica)` e referência R fixada na hipótese do sistema | não existem; a deduplicação é só por similaridade de texto (`hypotheses.py:464-496`) |
| `abandonada_por` (pesquisador / sistema) | não existe; toda `abandonada` bloqueia para sempre (`hypotheses.py:585-606`, `hypotheses.py:810`, `ingestion.py:587`) |
| `(Experimento)-[:PREPARA]->(Hipotese \| Problema)` | relação inexistente (`schema.py:386-444`) |
| `(Resultado)-[:REFERENCIA_DE]->(Problema)` | relação inexistente |
| `(Hipotese)-[:DERIVADA_DE]->(Hipotese)` | `DERIVADA_DE` só aceita `Insumo`, `Descoberta`, `Oportunidade` (`schema.py:398`) |
| Grafos antigos lidos sem reescrita | não há regra de leitura para `papel` ausente nem para `abandonada` sem autor |

## O que muda

- **Novo:**
  - Propriedade opcional `Experimento.papel` com enum `teste`, `preparacao`, `referencia`.
  - Valor `sistema` no enum `Hipotese.origem`.
  - Propriedades opcionais de `Hipotese`: `chave_estruturada` (texto `"<problema_id>|<abordagem_id>|<metrica_id>"`), `referencia_fixada` (mapa com `valor`, `origem_referencia`, `metrica_id`, `resultado_id` e `fixada_em`), `abandonada_por` (enum `pesquisador`, `sistema`, `agente`) e `motivo_abandono`.
  - Regra condicional: `Hipotese` com `origem = "sistema"` exige `chave_estruturada` e `referencia_fixada` na criação; as duas são imutáveis depois de gravadas.
  - Regra de autoridade: só o `Actor` `pesquisador` grava `abandonada_por = "pesquisador"` ou tira a hipótese desse estado (mesmo mecanismo de `HUMAN_ONLY_TRANSITIONS`, `validation.py:263`).
  - Relações `Experimento-PREPARA->(Hipotese | Problema)` e `Resultado-REFERENCIA_DE->Problema`.
  - Construtores compartilhados de grafo em memória para testes (`tests/support/exploration_graph.py`: `Problema` por tipo de objetivo, hipóteses, `Experimento`, `Resultado` e referência), reutilizados pelas mudanças seguintes da V18.7 (design §5.1).
  - Funções de leitura compatível: `experiment_role(node)` (ausente = `teste`) e `abandoned_by(node)` (ausente = `pesquisador`, proposta do design §6, sujeita à questão 1).
- **Modificado:**
  - `Hipotese-DERIVADA_DE->` passa a aceitar `Hipotese` como destino, sem laço para o próprio nó.
  - A migração idempotente `scripts/migrate_v17_knowledge.py` passa a criar os rótulos de aresta `PREPARA` e `REFERENCIA_DE` (já gera os rótulos a partir de `schema.RELATION_TYPES`; nenhuma linha nova de SQL).
- **Removido:** nada.
- **Fora do escopo:**
  - Quem decide o papel, quando a hipótese do sistema é criada, a deduplicação pela chave, o ciclo de vida e as transições de status: `v18.7-hypothesis-linking`.
  - Tipo de objetivo do `Problema`, `ao_atingir_objetivo`, novos motivos de parada (`limite_custo`, `saturacao`) e restrições por direção: `v18.7-exploration-limits`.
  - Contadores por papel e origem: `v18.7-exploration-metrics`.
  - Publicação de `papel` nos registros federados: pendência das mudanças `v20-federated-records` (ADR 021 §9).

## Impacto

- **Código:** `src/knowledge/schema.py` (enum, propriedades, relações, imutáveis por rótulo), `src/knowledge/validation.py` (regra condicional de `origem = "sistema"`, autoridade sobre `abandonada_por`, imutabilidade por rótulo), `src/knowledge/graph_views.py` ou módulo novo `src/knowledge/exploration_reads.py` (leitura compatível), `scripts/migrate_v17_knowledge.py` (sem mudança de código; reexecução cria os rótulos novos).
- **Contratos:** os leitores do grafo (Curator, `graph-cli`, relatório, veredito) passam a ver `origem = "sistema"`, `papel` e as duas relações novas. `KnowledgeService.collect_attempts` não muda: `PREPARA` e `REFERENCIA_DE` não são tentativas.
- **Schema de banco:** nenhuma tabela ou coluna relacional. No grafo AGE: dois rótulos de aresta novos (`PREPARA`, `REFERENCIA_DE`), criados pela migração existente; propriedades novas não exigem DDL.
- **Custo:** nenhuma chamada LLM. Mais arestas por sessão (uma `PREPARA` por par preparação-hipótese servida).

## Aprovações necessárias

- **Mudança de schema do grafo** (AGENTS.md §1.5): novo valor de enum `Hipotese.origem = "sistema"`, propriedades `Experimento.papel`, `Hipotese.chave_estruturada`, `Hipotese.referencia_fixada`, `Hipotese.abandonada_por`, `Hipotese.motivo_abandono`, relações `PREPARA` e `REFERENCIA_DE`, e destino `Hipotese` em `DERIVADA_DE`. Exige aprovação explícita do pesquisador antes da implementação.
- **Execução da migração** no banco de desenvolvimento e no Pi 5 (cria rótulos de aresta; não apaga nem reescreve nós): confirmação do pesquisador antes de rodar no Pi.
- **Decisão do pesquisador** sobre as questões em aberto do `design.md` §9, em especial a leitura de hipóteses `abandonada` antigas sem `abandonada_por` (questão 1).
- Nenhuma alteração de Dockerfile, `docker-compose.yml`, exclusão de arquivos ou `AGENTS.md`.
