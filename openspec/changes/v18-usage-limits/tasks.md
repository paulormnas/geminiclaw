# Tarefas: v18-usage-limits

## 1. Orçamento e contabilização
- [x] 1.1 `src/usage.py` com `UsageBudget`, `UsageTracker`, `LimitStatus`.
- [x] 1.2 Configurações e aliases em `src/config.py`; `.env.example`.
- [x] 1.3 Opções da CLI `--max-tokens`, `--max-minutes`, `--max-task-retries`, `--max-connection-retries`; orçamento no payload e exibido no início.
- [x] 1.4 Evento `connection_retry` nos provedores LLM e no sandbox.

## 2. Comportamento
- [x] 2.1 Verificação antes de cada despacho no `AutonomousLoop`.
- [x] 2.2 Parada graciosa por tokens e tempo (com `LIMIT_GRACE_SECONDS`).
- [x] 2.3 Abandono da tarefa por retentativas, sem parar a sessão.
- [x] 2.4 Fechamento por retentativas de conexão.
- [x] 2.5 Reserva de tokens para o fechamento.
- [x] 2.6 `motivo_parada` gravado na sessão (`agent_sessions.payload`). O "nó `Sessao`"
      referido aqui pertence ao armazenamento em grafo do Curator (ADR 012), que ainda
      não existe neste codebase — ver nota de integração em `_close_session`
      (`src/autonomous_loop.py`). Quando `v18-research-continuity`/Curator forem
      implementados, esse gravamento deve ser estendido ao nó do grafo.

## 3. Avisos G5
- [x] 3.1 Avisos como percentuais dos novos limites; aliases das variáveis antigas.

## 4. Correções
- [x] 4.1 `AutonomousLoop` lê limites de `src/config.py`; destacar no PR a mudança do default efetivo de 10 para 3.

## 5. Testes
- [x] 5.1 Tokens: sessão para ao atingir `max_tokens × (1 − reserva)`; fechamento usa a reserva.
- [x] 5.2 Tempo: subtarefa em andamento termina dentro da carência; demais são canceladas.
- [x] 5.3 Retentativas: tarefa abandonada, outra ramificação do DAG continua.
- [x] 5.4 Conexão: 20 retentativas encerram a sessão com `limite_conexao`.
- [x] 5.5 Tokens do Curator entram na conta (o leitor default soma por `execution_id`,
      sem filtrar por `agent_id`/papel — coberto por teste; o agente Curator em si
      ainda não existe neste codebase).
- [x] 5.6 Reserva esgotada: checkpoint determinístico é gravado e Curator fica pendente
      (`consolidation_pending=True`).

## 6. Fechamento
- [x] 6.1 Ruff, testes.
- [ ] 6.2 Revisão nos 7 eixos, PR.

- [ ] X.1 **Gate humano** (de `v17-curator-agent` 6.99): ligar `ativar_modo_sem_limite` ao `HumanGate` (`src/human_gate.py`, origem `Source.TERMINAL`/`Source.CLI`) quando o modo existir; a resposta de `ask_researcher`/consultor nunca autoriza; teste de integração do ponto de decisão.
