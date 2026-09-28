# Tarefas: v18-usage-limits

## 1. Orçamento e contabilização
- [ ] 1.1 `src/usage.py` com `UsageBudget`, `UsageTracker`, `LimitStatus`.
- [ ] 1.2 Configurações e aliases em `src/config.py`; `.env.example`.
- [ ] 1.3 Opções da CLI `--max-tokens`, `--max-minutes`, `--max-task-retries`, `--max-connection-retries`; orçamento no payload e exibido no início.
- [ ] 1.4 Evento `connection_retry` nos provedores LLM e no sandbox.

## 2. Comportamento
- [ ] 2.1 Verificação antes de cada despacho no `AutonomousLoop`.
- [ ] 2.2 Parada graciosa por tokens e tempo (com `LIMIT_GRACE_SECONDS`).
- [ ] 2.3 Abandono da tarefa por retentativas, sem parar a sessão.
- [ ] 2.4 Fechamento por retentativas de conexão.
- [ ] 2.5 Reserva de tokens para o fechamento.
- [ ] 2.6 `motivo_parada` gravado na sessão e no nó `Sessao`.

## 3. Avisos G5
- [ ] 3.1 Avisos como percentuais dos novos limites; aliases das variáveis antigas.

## 4. Correções
- [ ] 4.1 `AutonomousLoop` lê limites de `src/config.py`; destacar no PR a mudança do default efetivo de 10 para 3.

## 5. Testes
- [ ] 5.1 Tokens: sessão para ao atingir `max_tokens × (1 − reserva)`; fechamento usa a reserva.
- [ ] 5.2 Tempo: subtarefa em andamento termina dentro da carência; demais são canceladas.
- [ ] 5.3 Retentativas: tarefa abandonada, outra ramificação do DAG continua.
- [ ] 5.4 Conexão: 20 retentativas encerram a sessão com `limite_conexao`.
- [ ] 5.5 Tokens do Curator entram na conta.
- [ ] 5.6 Reserva esgotada: checkpoint determinístico é gravado e Curator fica pendente.

## 6. Fechamento
- [ ] 6.1 Ruff, testes, revisão nos 7 eixos, PR.
