# Proposta: Continuidade da Pesquisa entre Execuções

**ID:** `v18-research-continuity` · **Versão:** V18 · **Capacidade:** `session-continuity`
**ADRs de origem:** [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md)
("Continuidade entre execuções"), [ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §5

## Por quê

O pesquisador decidiu: **atingir um limite interrompe a execução, não a pesquisa**. Todo o
avanço deve ser registrado para que a próxima execução continue de onde parou, usando toda a
informação da anterior — inclusive após paradas inesperadas (queda de energia, erro fatal).

Hoje, `geminiclaw resume` (`src/cli.py::resume_session`) documenta a limitação: "o framework
não faz checkpoint do estado de execução do DAG, então 'retomar' reinicia o ciclo de
planejamento a partir do prompt original". Só artefatos em disco são reaproveitados.

## O que muda

- **Novo:** checkpoint incremental e atômico da sessão (`checkpoint.json`), gravado a cada
  subtarefa concluída, a cada mudança de plano e no fechamento.
- **Novo:** batimento da sessão e detecção de paradas inesperadas na inicialização.
- **Modificado:** `geminiclaw resume --session <id>` retoma **a partir do checkpoint**; novo
  `geminiclaw continue --project <id>` retoma a última sessão do projeto.
- **Novo:** a sessão retomada é uma sessão nova ligada à anterior (`Sessao-CONTINUA->Sessao`),
  com contexto de retomada para o Researcher (estado do plano, hipóteses abertas, caminhos
  sem conclusão, experiência relacionada do grafo) e leitura dos artefatos anteriores.

## Impacto

- **Código:** `src/continuity.py` (novo), `src/autonomous_loop.py`, `src/orchestrator.py`,
  `src/session.py` (batimento), `src/cli.py`, `src/agent_runtime/context.py` (diretórios
  legíveis), `agents/researcher/agent.py` (modo de retomada).
- **Dependências:** `v18-usage-limits` (fechamento), `v17-structural-fact-ingestion` (grafo
  com os fatos), `v17-curator-agent` (descobertas e caminhos).

## Aprovações necessárias

Nenhuma alteração de schema (checkpoint em arquivo; status e ponteiro no payload JSONB).
