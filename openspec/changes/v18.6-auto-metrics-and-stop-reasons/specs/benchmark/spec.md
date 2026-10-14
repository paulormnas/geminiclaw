# Delta: benchmark

## ADDED Requirements

### Requirement: Classificação dos motivos de parada
O benchmark SHALL classificar o `motivo_parada` de cada execução em `limite`, `erro`, `interrupcao`, `criterio_pesquisa` ou
`hipoteses_nao_testadas`. Somente `limite`, `erro` e `interrupcao` SHALL ser anomalia. `hipoteses_nao_testadas` SHALL ser
tratado como parada de pesquisa, listado no relatório e nunca contado como erro. O resumo de interações SHALL contar os
motivos de reprovação de subtarefa (`sem_hipotese`).

#### Scenario: Parada por hipótese não testada não é anomalia
- **GIVEN** uma execução com `stop_reason = "hipoteses_nao_testadas"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Classificação
- **WHEN** `stop_class` recebe `limite_tokens`, `erro`, `interrompida_pesquisador`, `solucao_encontrada` e `hipoteses_nao_testadas`
- **THEN** devolve `limite`, `erro`, `interrupcao`, `criterio_pesquisa` e `hipoteses_nao_testadas`

#### Scenario: Relatório lista a parada
- **GIVEN** duas execuções da combinação `c1`, uma fechada por `hipoteses_nao_testadas`
- **WHEN** o relatório é gerado
- **THEN** há uma seção que cita `c1` e a repetição afetada

#### Scenario: Reprovação sem hipótese no resumo
- **GIVEN** um evento `subtask_review` com `motivos = ["sem_hipotese"]`
- **WHEN** `summarize_events` resume os eventos
- **THEN** `subtask_reviews.motivos` é `{"sem_hipotese": 1}`
