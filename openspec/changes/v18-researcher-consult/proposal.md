# Proposta: Researcher como Consultor nos Modos Autônomos

**ID:** `v18-researcher-consult` · **Versão:** V18 · **Capacidade:** `researcher-consult`
**ADRs de origem:** [ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §8
(consulta ao Researcher nos modos `semi` e `auto`) e §5 (limites de uso);
[ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md) item 9
(busca na web para enriquecer o contexto, sem busca bibliográfica);
[ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §3
(nenhum dado bruto de pesquisa nas consultas)
**Depende de:** `v18-usage-limits` (implementada: `src/usage.py`); revisa o comportamento da
Spec G5 (`roadmaps/specs/G5_human_feedback_loop.md`) nos modos `semi`/`auto`
**Relaciona-se com:** `v18-hypothesis-loop` (as consultas acontecem dentro do ciclo; ver nota
de 2026-10-01 naquela mudança); `v18.5-egress-gate` (quando existir, as consultas passam por
ela)

## Por quê

Nos modos `semi` e `auto`, `ask_researcher` hoje não pergunta nada a ninguém: a skill devolve
"prossiga com a melhor suposição" e registra um evento
(`src/skills/human_feedback/skill.py:75-104`). O agente que perguntou fica sem informação nova:
a pergunta só é registrada para avaliação posterior. O pesquisador decidiu (ADR 012 §8, 2026-10-01) que,
nesses modos, o **Researcher responde no lugar do humano**, podendo fazer consultas simples na
internet — documentação, definições, valores usuais; não artigos —, e que tudo fica registrado
para avaliar depois se a consulta foi relevante.

## O que muda

- **Modificado:** em `semi` e `auto`, `ask_researcher` passa a chamar o **Researcher consultor**
  (uma chamada de LLM do papel `researcher`, com prompt e ferramentas próprios) e devolve a
  resposta dele ao agente que perguntou. Em `assisted`, nada muda: a pergunta vai ao humano.
- **Novo:** ferramentas do consultor restritas a `quick_search` (busca na web) e `web_reader`
  (leitura de uma página), com número máximo de buscas por consulta; sem `ask_researcher`, sem
  sandbox, sem escrita no grafo ou em arquivos.
- **Novo:** **guarda de consulta**: o texto enviado ao buscador é verificado antes de sair do
  nó (sem números com casas decimais nem sequências longas de dígitos, sem nomes de arquivos de
  `input_snapshot/`, tamanho máximo). Consulta recusada não é enviada e o motivo é registrado.
- **Novo:** resposta estruturada (`resposta`, `confianca`, `fontes`, `suposicoes`,
  `buscas_realizadas`) registrada em `researcher_interactions` com `respondido_por="researcher"`
  e em evento de telemetria `researcher_consult`.
- **Novo:** decisões **reservadas ao humano** nunca são respondidas pelo consultor (aprovar
  `Oportunidade`, confirmar `Problema`, aprovar termo de vocabulário, autorizar escrita em
  instrumento, ativar o modo sem limite). Nesses casos, a pergunta fica pendente para o
  pesquisador e o agente recebe essa informação.
- **Novo:** limite de consultas por sessão; tokens do consultor contam no orçamento da sessão
  (`UsageTracker`). Limite atingido, falha ou timeout → comportamento atual (suposição
  documentada), com o motivo registrado.
- **Modificado:** instruções de `ask_researcher` nos prompts dos agentes (`agents/*/agent.py`)
  descrevem o consultor nos modos autônomos.
- **Fora do escopo:** busca bibliográfica (ADR 010); avaliação automática da relevância das
  consultas (`v16-agent-communication-eval`, a descrever); filtro de saída geral
  (`v18.5-egress-gate`).

## Impacto

- **Código:** `src/skills/human_feedback/skill.py`, `src/agent_runtime/context.py`
  (callback `consult_researcher`), `src/orchestrator.py` (núcleo da consulta, registro,
  deduplicação), `agents/researcher/consult.py` (novo: prompt e laço do consultor),
  `src/research_consult/query_guard.py` (novo), `src/skills/search_quick/skill.py` e
  `src/skills/web_reader/skill.py` (reutilizados, sem mudança de contrato), `agents/*/agent.py`
  (texto das instruções), `src/config.py`, `.env.example`.
- **Custo:** chamadas LLM do papel `researcher` por consulta (limitadas por sessão) e acessos a
  buscadores públicos.
- **Comportamento:** em `semi`/`auto` os agentes recebem respostas reais; as sessões ficam um
  pouco mais longas. Com `RESEARCHER_CONSULT_ENABLED=false`, o comportamento atual é mantido.

## Aprovações necessárias

- Nenhuma alteração de schema (payload JSONB), Dockerfile ou compose.
- **Saída de texto para buscadores públicos** nos modos autônomos: decisão de política de dados
  tomada no ADR 012 §8; o Analista de Segurança revisa a guarda de consulta (design §4) antes
  do merge.
