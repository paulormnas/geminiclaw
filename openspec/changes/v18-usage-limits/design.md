# Design: Limites de Uso como Condições de Parada

## 1. Orçamento

```python
# src/usage.py
@dataclass(frozen=True)
class UsageBudget:
    max_tokens: int                 # todos os agentes, inclusive Curator
    max_minutes: float              # tempo de relógio da sessão
    max_task_retries: int           # retentativas da MESMA tarefa (task_name)
    max_connection_retries: int     # retentativas de conexão acumuladas na sessão
    closing_reserve_pct: float      # fração de max_tokens reservada ao fechamento
```

| Variável (`src/config.py`) | Default | Opção da CLI |
|---|---|---|
| `SESSION_MAX_TOKENS` (substitui `MAX_SESSION_TOKENS`, que vira alias) | 500000 | `--max-tokens` |
| `SESSION_MAX_MINUTES` | 120 | `--max-minutes` |
| `SESSION_MAX_TASK_RETRIES` (substitui `MAX_RETRY_PER_SUBTASK`, alias) | 3 | `--max-task-retries` |
| `SESSION_MAX_CONNECTION_RETRIES` | 20 | `--max-connection-retries` |
| `SESSION_CLOSING_RESERVE_PCT` | 0.05 | — |

O orçamento efetivo é gravado em `agent_sessions.payload["budget"]` e exibido no início da
sessão. Uma sessão retomada (`v18-research-continuity`) recebe um orçamento **novo**; o
consumo acumulado do projeto é informativo.

## 2. Contabilização (`UsageTracker`)

- **Tokens:** soma de `usage.total_tokens` de toda chamada LLM na sessão, por papel, a partir
  da telemetria existente (`token_usage`).
- **Tempo:** desde o início da sessão (relógio monotônico).
- **Retentativas por tarefa:** por `task_name`, contando reexecuções da mesma subtarefa
  (inclusive após replanejamento que mantém o nome).
- **Retentativas de conexão:** cada retentativa por erro de conexão/timeout/429/5xx nos
  provedores LLM e cada falha de conexão com o daemon Docker do sandbox emitem o evento
  `connection_retry` na telemetria; o tracker soma por sessão.

`UsageTracker.check() -> LimitStatus` retorna, para cada limite, o percentual consumido e se
foi atingido.

## 3. Comportamento por limite

| Limite atingido | Ação | `motivo_parada` |
|---|---|---|
| Tokens (descontada a reserva) | Não despacha novas chamadas de exploração; aguarda as em andamento; entra em **fechamento** | `limite_tokens` |
| Tempo | Não despacha novas subtarefas; aguarda as em andamento até `LIMIT_GRACE_SECONDS` (120); cancela o restante; **fechamento** | `limite_tempo` |
| Retentativas da mesma tarefa | **Só a tarefa** é abandonada: subtarefa marcada `abandonada`, hipótese correspondente fica com o caminho registrado como sem conclusão; o restante do DAG e a sessão continuam | (sessão continua) |
| Retentativas de conexão | Sessão entra em **fechamento** (o problema é de infraestrutura) | `limite_conexao` |

Se todas as tarefas pendentes forem abandonadas por retentativas, a sessão fecha com
`motivo_parada="limite_retentativas"`.

**Fechamento** = checkpoint (`v18-research-continuity`) + `curator.close_session` usando a
reserva de tokens. Se a reserva também se esgotar, o checkpoint determinístico é gravado
mesmo assim (não usa LLM) e o Curator fica pendente para a próxima execução.

## 4. Avisos (Spec G5)

`OPERATIONAL_THRESHOLDS` continua existindo como **avisos** antes da parada, agora como
percentual de cada limite: `token_usage_pct` sobre `max_tokens`, e o novo
`session_duration_pct` sobre `max_minutes` (o antigo `session_duration_min` vira alias,
convertido). `cost_usd` segue como aviso. `container_count_pct` passa a se referir aos
containers de sandbox (ADR 014). O comportamento do modo `assisted` (perguntar se deseja
suspender) é mantido.

## 5. Correção de inconsistências

- `AutonomousLoop` lê `max_retries` e `max_subtasks` de `src/config.py` (fonte única).
- **Mudança de comportamento:** o default efetivo de retentativas por tarefa passa de 10 para
  3 (valor documentado em `config`). O PR deve destacar isso; o pesquisador pode ajustar por
  `SESSION_MAX_TASK_RETRIES` ou `--max-task-retries`.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Verificação de limites antes de cada despacho; fechamento gracioso. |
| Agentes & Prompts | Nenhum. |
| Sandboxes & Containers | Evento de retentativa de conexão com o Docker. |
| Persistência | `budget` e `motivo_parada` no payload da sessão. |
| Segurança | Limita consumo descontrolado de recursos e custos. |
| Testes & Telemetria | Evento `connection_retry`; consumo por papel. |
