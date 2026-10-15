# Delta: benchmark

Este delta parte do texto do requisito "Classificação dos motivos de parada" como modificado por `v18.7-benchmark-fixes` (com `limite_cota_provedor`), que é mergeada antes desta mudança. A regra dos motivos `*_pesquisador` (classe `interrupcao`) é de `v18.7-background-sessions`, também mergeada antes, e não muda aqui.

## MODIFIED Requirements

### Requirement: Classificação dos motivos de parada
_Redação final da V18.7: substitui a de `v18.7-benchmark-fixes` (mergeada antes, onda 1) e a contém por inteiro; quem implementar esta mudança parte do texto já aplicado por aquela._
O benchmark SHALL classificar o `motivo_parada` de cada execução em `limite`, `erro`, `interrupcao`, `criterio_pesquisa`, `hipoteses_nao_testadas` ou `planos_rejeitados`. Somente `limite`, `erro` e `interrupcao` SHALL ser anomalia. `versao_modelo` SHALL ser `limite` (anomalia: a comparação exige sessões completas com a versão declarada; `v18.7-benchmark-fixes`). `planos_rejeitados` SHALL ter classe própria `planos_rejeitados`, identificável nos relatórios e não anomalia, como `hipoteses_nao_testadas`; os dois motivos só ocorrem na bateria com `ON_PLAN_REJECTIONS=parar` e `ON_MODEL_VERSION_CHANGE=parar`. `limite_custo` SHALL ser `limite`; `limite_cota_provedor` SHALL ser `limite` e listado no relatório com o provedor e o modelo do evento `cota_provedor_esgotada`; `saturacao` SHALL ser `criterio_pesquisa`; `limite_ciclos` e `limite_execucoes`, presentes só em resultados antigos, SHALL continuar `limite`. `hipoteses_nao_testadas` SHALL ser tratado como parada de pesquisa, listado no relatório e nunca contado como erro. O resumo de interações SHALL contar os motivos de reprovação de subtarefa registrados (ADR 021 §5, "Mudanças OpenSpec exigidas").

#### Scenario: Classificação
- **WHEN** `stop_class` recebe `limite_tokens`, `limite_custo`, `limite_cota_provedor`, `limite_ciclos`, `erro`, `interrompida_pesquisador`, `solucao_encontrada`, `saturacao`, `hipoteses_nao_testadas`, `versao_modelo` e `planos_rejeitados`
- **THEN** devolve `limite`, `limite`, `limite`, `limite`, `erro`, `interrupcao`, `criterio_pesquisa`, `criterio_pesquisa`, `hipoteses_nao_testadas`, `limite` e `planos_rejeitados`

#### Scenario: Bateria usa a política parar para planos rejeitados
- **GIVEN** um ambiente base com `ON_PLAN_REJECTIONS=explorar`
- **WHEN** `build_env` monta o ambiente do subprocesso de uma combinação
- **THEN** o ambiente devolvido tem `ON_PLAN_REJECTIONS == "parar"` e o ambiente base não é alterado

#### Scenario: Saturação não é anomalia
- **GIVEN** uma execução com `stop_reason = "saturacao"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Planos rejeitados não é anomalia
- **GIVEN** uma execução com `stop_reason = "planos_rejeitados"` e `status="exit 3"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado e o relatório a lista como `planos_rejeitados`

#### Scenario: Limite de custo é anomalia
- **GIVEN** uma execução com `stop_reason = "limite_custo"`
- **WHEN** `anomalies()` avalia a execução
- **THEN** a lista contém o problema de sessão fechada por `limite_custo` antes de concluir

#### Scenario: Parada por hipótese não testada não é anomalia
- **GIVEN** uma execução com `stop_reason = "hipoteses_nao_testadas"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Parada por cota é anomalia identificada
- **GIVEN** uma execução com `stop_reason = "limite_cota_provedor"` e um evento `cota_provedor_esgotada` com `provedor="google"` e `modelo="gemini-4-argon"`
- **WHEN** o relatório é gerado
- **THEN** a execução aparece como anomalia de parada e o texto cita `google/gemini-4-argon`

#### Scenario: Relatório lista a parada
- **GIVEN** duas execuções da combinação `c1`, uma fechada por `hipoteses_nao_testadas`
- **WHEN** o relatório é gerado
- **THEN** há uma seção que cita `c1` e a repetição afetada

## ADDED Requirements

### Requirement: Teto de custo da sessão declarado na matriz
A matriz do benchmark SHALL declarar `SESSION_MAX_COST_USD` em `env` (o teto por sessão, distinto do `budget_usd` por provedor e por rodada do runner), e o runner SHALL recusar, antes de qualquer execução e sem apagar nada, a matriz sem esse valor ou com valor não positivo (ADR 021 §5.4).

#### Scenario: Matriz sem teto de custo
- **GIVEN** uma matriz cujo `env` não tem `SESSION_MAX_COST_USD`
- **WHEN** o runner valida a matriz
- **THEN** o runner termina com erro que cita `SESSION_MAX_COST_USD` e nenhuma execução começa

#### Scenario: Matriz com teto
- **GIVEN** `env.SESSION_MAX_COST_USD = "5"`
- **WHEN** uma combinação roda
- **THEN** o subprocesso recebe `SESSION_MAX_COST_USD=5`
