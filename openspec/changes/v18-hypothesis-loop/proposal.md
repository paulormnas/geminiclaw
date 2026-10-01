# Proposta: Ciclo de Hipóteses e Exploração Ativa Curator ↔ Researcher

**ID:** `v18-hypothesis-loop` · **Versão:** V18 · **Capacidade:** `hypothesis-loop`
**ADRs de origem:** [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md),
[ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §3, §4, §6,
[ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §2, §4, §5

> **Nota de 2026-10-01:** nos modos `semi` e `auto`, as perguntas dos agentes (`ask_researcher`)
> passam a ser respondidas pelo Researcher consultor (`v18-researcher-consult`, ADR 012 §8). As
> decisões reservadas ao humano deste ciclo (aprovar `Oportunidade`, confirmar `Problema`) nunca
> são respondidas pelo consultor; ficam pendentes para o pesquisador.

## Por quê

É a mudança que transforma o sistema em assistente de pesquisa: ele **formula hipóteses** a
partir dos insumos, dos resultados e do conhecimento acumulado; **registra por que escolheu um
caminho e não outro**; e mantém um **ciclo ativo** com o Curator — que sugere novos caminhos —
até **encontrar uma solução ou atingir um limite** definido pelo pesquisador. A autonomia
respeita o `SessionMode`, e oportunidades só são investigadas com decisão humana.

## O que muda

- **Novo:** hipóteses formais no plano — o Researcher declara hipóteses (nós `Hipotese`) e
  cada subtarefa referencia a hipótese que testa (substitui a regra provisória da V17).
- **Novo:** governança por `SessionMode`: no `assisted`, hipóteses propostas por agentes
  exigem aprovação antes da execução; no `semi`/`auto`, as mais prioritárias são executadas
  dentro do orçamento, com registro.
- **Novo:** prioridade de hipóteses calculada a partir do grafo.
- **Novo:** decisões de caminho (`Decisao`) registradas em todo planejamento e replanejamento,
  com avaliação posterior; o Curator consolida lições de caminho.
- **Novo:** sugestões do Curator ao Researcher a cada ciclo; o Researcher responde a cada uma
  (aceita ou recusa com motivo).
- **Novo:** critério de "solução encontrada" e de "sem caminhos promissores"; o ciclo continua
  até um deles ou até um limite de uso.
- **Novo:** `geminiclaw opportunities list|approve|reject` — decisão humana sobre
  oportunidades documentadas.

## Impacto

- **Código:** `src/autonomous_loop.py` (ciclo), `agents/researcher/agent.py` (formato do plano,
  decisões, respostas a sugestões), `agents/curator/agent.py` (`suggest_paths`),
  `src/knowledge/hypotheses.py` (novo), `src/knowledge/ingestion.py` (substitui regra
  provisória), `src/cli.py`, `src/config.py`.
- **Schema do grafo:** novo valor `sem_caminhos_promissores` em `Sessao.motivo_parada`.

## Aprovações necessárias

- Novo valor de enumeração no schema do grafo — aprovação explícita.
