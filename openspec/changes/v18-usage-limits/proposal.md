# Proposta: Limites de Uso como Condições de Parada

**ID:** `v18-usage-limits` · **Versão:** V18 · **Capacidade:** `usage-limits`
**ADRs de origem:** [ADR 010](../../../docs/decisions/adr_010_proposito_assistente_digital_pesquisa.md),
[ADR 012](../../../docs/decisions/adr_012_agente_curator_ciclo_exploracao.md) §5

> **Nota de 2026-10-01:** os tokens do Researcher consultor (`v18-researcher-consult`) são medidos
> com o `execution_id` do agente que perguntou e entram no total da sessão pelo `UsageTracker`;
> o limite próprio de consultas por sessão está naquela mudança. Nada muda aqui.

## Por quê

Com o ciclo de exploração contínua (V18), o sistema continua pesquisando enquanto houver
caminhos promissores. O pesquisador responsável definiu que isso ocorre **sempre dentro de
limites que ele configura**: tokens, tempo, retentativas da mesma tarefa e retentativas de
conexão. Hoje os limites da Spec G5 (`OPERATIONAL_THRESHOLDS`) apenas **avisam**; o término é
decidido por `MAX_PLAN_RETRIES` e por circuit breakers espalhados.

Levantamento do código (2026-09-28) — inconsistências a corrigir:

- `MAX_RETRY_PER_SUBTASK`: `src/config.py` define default **3**, mas
  `AutonomousLoop.__init__` lê `os.environ` diretamente com default **10**.
- `MAX_SUBTASKS_PER_TASK`: `src/config.py` define **5** ou **10** (por perfil), mas o loop lê
  `os.environ` com default **15**.
- Não há contagem de retentativas de conexão por sessão.

## O que muda

- **Novo:** `UsageBudget` por sessão (tokens, minutos, retentativas por tarefa, retentativas de
  conexão), com defaults em `src/config.py` e ajuste por opções da CLI; gravado no payload da
  sessão.
- **Novo:** `UsageTracker`, que acumula o consumo de **todos** os agentes (inclusive Curator),
  o tempo, as retentativas por tarefa e as retentativas de conexão.
- **Novo:** comportamento ao atingir cada limite (parada graciosa, abandono só da tarefa, ou
  parada da sessão), sempre registrando o `motivo_parada`.
- **Novo:** reserva de orçamento para o fechamento (checkpoint + Curator) mesmo após o
  limite de tokens.
- **Modificado:** os avisos da Spec G5 passam a ser percentuais dos novos limites.
- **Corrigido:** o loop lê limites só de `src/config.py`.

## Impacto

- **Código:** `src/usage.py` (novo), `src/autonomous_loop.py`, `src/orchestrator.py`,
  `src/telemetry.py`, `src/llm/providers/*` (evento de retentativa de conexão),
  `src/skills/code/sandbox.py` (idem), `src/config.py`, `src/cli.py`.
- **Comportamento:** o default efetivo de retentativas por subtarefa passa de 10 (valor lido
  pelo loop) para o valor de `config` — ver design §5.

## Aprovações necessárias

Nenhuma alteração de schema (payload JSONB).
