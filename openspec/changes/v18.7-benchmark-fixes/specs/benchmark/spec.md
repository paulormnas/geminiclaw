# Delta: benchmark

## MODIFIED Requirements

### Requirement: Classificação dos motivos de parada
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../../archive/v18.6-auto-metrics-and-stop-reasons/proposal.md); modificado por `v18.7-benchmark-fixes`._
O benchmark SHALL classificar o `motivo_parada` de cada execução em `limite`, `erro`, `interrupcao`, `criterio_pesquisa` ou `hipoteses_nao_testadas`. Somente `limite`, `erro` e `interrupcao` SHALL ser anomalia. `limite_cota_provedor` SHALL ser classificado como `limite` e listado no relatório com o provedor e o modelo do evento `cota_provedor_esgotada`. `hipoteses_nao_testadas` SHALL ser tratado como parada de pesquisa, listado no relatório e nunca contado como erro. O resumo de interações SHALL contar os motivos de reprovação de subtarefa (`sem_hipotese`).

#### Scenario: Parada por hipótese não testada não é anomalia
- **GIVEN** uma execução com `stop_reason = "hipoteses_nao_testadas"` e `exit 0`
- **WHEN** `anomalies()` avalia a execução
- **THEN** nenhum problema de parada é reportado

#### Scenario: Classificação
- **WHEN** `stop_class` recebe `limite_tokens`, `limite_cota_provedor`, `erro`, `interrompida_pesquisador`, `solucao_encontrada` e `hipoteses_nao_testadas`
- **THEN** devolve `limite`, `limite`, `erro`, `interrupcao`, `criterio_pesquisa` e `hipoteses_nao_testadas`

#### Scenario: Parada por cota é anomalia identificada
- **GIVEN** uma execução com `stop_reason = "limite_cota_provedor"` e um evento `cota_provedor_esgotada` com `provedor="google"` e `modelo="gemini-4-argon"`
- **WHEN** o relatório é gerado
- **THEN** a execução aparece como anomalia de parada e o texto cita `google/gemini-4-argon`

#### Scenario: Relatório lista a parada
- **GIVEN** duas execuções da combinação `c1`, uma fechada por `hipoteses_nao_testadas`
- **WHEN** o relatório é gerado
- **THEN** há uma seção que cita `c1` e a repetição afetada

#### Scenario: Reprovação sem hipótese no resumo
- **GIVEN** um evento `subtask_review` com `motivos = ["sem_hipotese"]`
- **WHEN** `summarize_events` resume os eventos
- **THEN** `subtask_reviews.motivos` é `{"sem_hipotese": 1}`

## ADDED Requirements

### Requirement: Tabela de egresso com a grandeza limitada
_Origem: `v18.7-benchmark-fixes` (achado 6 da bateria V18.6)._
A tabela de métricas de operação do relatório (`render_operation`) SHALL trazer as colunas "Egresso total (bytes)", "Saídas novas (bytes)" e "Limite de saídas (bytes)", nessa ordem, preenchidas com `egresso.bytes_total`, `egresso.bytes_limitados` e `egresso.limite_bytes` (`sem limite` quando nulo). Resultado sem `bytes_limitados` (execução anterior a esta mudança) SHALL mostrar `-` na coluna de saídas novas. A coluna "Cadeia de execuções" SHALL mostrar a primeira causa não nula de `cadeia.motivos` entre parênteses quando o resultado for `divergente`.

#### Scenario: Colunas de egresso
- **GIVEN** um resultado com `bytes_total=3942301`, `bytes_limitados=412000` e `limite_bytes=2000000`
- **WHEN** `render_operation` gera a tabela
- **THEN** a linha da combinação contém `| 3942301 | 412000 | 2000000 |` nas três colunas de egresso

#### Scenario: Resultado antigo
- **GIVEN** um resultado gravado antes desta mudança, sem `bytes_limitados`
- **WHEN** `render_operation` gera a tabela
- **THEN** a coluna "Saídas novas (bytes)" mostra `-` e a tabela é gerada sem erro

#### Scenario: Modo sem limite
- **GIVEN** um resultado com `limite_bytes` nulo
- **WHEN** `render_operation` gera a tabela
- **THEN** a coluna "Limite de saídas (bytes)" mostra `sem limite`

#### Scenario: Causa da cadeia divergente
- **GIVEN** um resultado com `cadeia.resultado="divergente"` e `cadeia.motivos.arquivos_alterados=2`
- **WHEN** `render_operation` gera a tabela
- **THEN** a coluna "Cadeia de execuções" mostra `divergente (arquivos_alterados)`
