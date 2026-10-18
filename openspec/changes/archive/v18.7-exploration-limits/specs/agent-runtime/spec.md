# Delta: agent-runtime

## MODIFIED Requirements

### Requirement: Limites de execução separados
O sistema SHALL contar as execuções de agente da sessão (planejamento e subtarefa, em contadores distintos) e as relatar nas métricas de operação, e MUST NOT interromper novas execuções nem encerrar a sessão por esse número (ADR 021 §5.1). O controle de gasto fica com os limites de custo, tokens, tempo e egresso (spec `usage-limits`). `MAX_AGENT_RUNS_PER_SESSION` e o alias `MAX_CONTAINERS_PER_SESSION` deixam de existir.
(Antes: o circuit breaker por `MAX_AGENT_RUNS_PER_SESSION` interrompia novas execuções e fechava com `limite_execucoes`.)

#### Scenario: Muitas execuções não encerram a sessão
- **GIVEN** uma sessão simulada que já fez 45 execuções de subtarefa e 25 de planejamento, com limites de uso folgados
- **WHEN** uma nova subtarefa é despachada
- **THEN** a execução ocorre, nenhuma `AgentRunLimitReached` é lançada e nenhum `motivo_parada = "limite_execucoes"` é gravado
- **AND** `operation_metrics.custo_recursos.execucoes_agente` registra `{"planejamento": 25, "execucao": 46}` no fechamento
