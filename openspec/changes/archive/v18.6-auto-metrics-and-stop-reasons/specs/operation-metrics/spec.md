# Delta: operation-metrics

## ADDED Requirements

### Requirement: Motivos de parada e de reprovação nas métricas de operação
O grupo `verificacao` SHALL registrar `fechada_por_hipoteses_nao_testadas` (booleano), `hipoteses_sem_tentativa_no_fechamento` e
`reprovacoes_sem_hipotese` (subtarefas distintas com o motivo `sem_hipotese`). A seção Markdown "Métricas de operação" SHALL descrever
o motivo de parada `hipoteses_nao_testadas` com a contagem de hipóteses sem tentativa.

#### Scenario: Contadores
- **GIVEN** um evento `exploration_stop` com `motivo_parada = "hipoteses_nao_testadas"`, um evento `hipoteses_sem_tentativa` com duas hipóteses e dois `subtask_review` da mesma subtarefa com `motivos = ["sem_hipotese"]`
- **WHEN** o leitor do grupo lê a sessão
- **THEN** `fechada_por_hipoteses_nao_testadas` é `true`, `hipoteses_sem_tentativa_no_fechamento` é 2 e `reprovacoes_sem_hipotese` é 1

#### Scenario: Seção do relatório
- **GIVEN** `stop_reason = "hipoteses_nao_testadas"`
- **WHEN** a seção é renderizada
- **THEN** o texto contém o motivo e a explicação "hipóteses em teste sem nenhuma tentativa"
