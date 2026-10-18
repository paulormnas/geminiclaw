# Delta: operation-metrics

## ADDED Requirements

### Requirement: Egresso limitado separado do total
_Origem: `v18.7-benchmark-fixes` (achado 6 da bateria V18.6); relacionado ao ADR 019 §8 e §11._
O grupo `egresso` SHALL registrar `bytes_limitados`, igual à soma de `bytes_saida_execucao_novos` da sessão (a mesma grandeza que o `UsageTracker` compara com `max_egress_bytes`), além de `bytes_total`. A seção Markdown "Métricas de operação" SHALL mostrar o limite ao lado de `bytes_limitados`, nunca ao lado de `bytes_total`, e SHALL nomear as duas grandezas.

#### Scenario: Total acima do limite sem violação
- **GIVEN** uma sessão com `bytes_total=3942301`, soma de `bytes_saida_execucao_novos` igual a 412000 e `limite_bytes=2000000`
- **WHEN** a seção é renderizada
- **THEN** o texto contém `3942301` como total enviado fora do nó e `412000 de 2000000` para as saídas de execução novas sujeitas ao limite
- **AND** o grupo `egresso` traz `bytes_limitados=412000`

#### Scenario: Igualdade com o contador do limite
- **GIVEN** registros de `egress_log` de uma sessão em banco de teste
- **WHEN** o leitor de `egresso` e o leitor de egresso do `UsageTracker` leem a sessão
- **THEN** `bytes_limitados` é igual ao valor do `UsageTracker`

### Requirement: Causas da cadeia divergente
_Origem: `v18.7-benchmark-fixes` (achado 5 da bateria V18.6)._
O grupo `proveniencia` SHALL registrar em `cadeia.motivos` as contagens `cadeia`, `pares`, `arquivos_alterados`, `checkpoints_divergentes` e `conflitos_pendencia` somadas dos relatórios de `verify_session`, e `cadeia.arquivos_alterados_exemplos` com até 5 caminhos alterados.

#### Scenario: Cadeia divergente por arquivo alterado
- **GIVEN** um relatório de verificação com um arquivo `alterado` em `s1/treino/metrics.json` e nenhum outro problema
- **WHEN** o leitor `proveniencia` lê a sessão
- **THEN** `cadeia.resultado` é `divergente`, `cadeia.motivos.arquivos_alterados` é 1, as demais contagens são 0 e `cadeia.arquivos_alterados_exemplos` contém `s1/treino/metrics.json`

### Requirement: Motivo de parada por cota descrito
_Origem: `v18.7-benchmark-fixes`._
`describe_stop_reason("limite_cota_provedor")` SHALL devolver o motivo com a explicação "cota ou teto de gasto esgotado no provedor; aumente o teto ou troque o provedor e retome a sessão".

#### Scenario: Seção do relatório
- **GIVEN** `stop_reason = "limite_cota_provedor"`
- **WHEN** a seção é renderizada
- **THEN** o texto contém `limite_cota_provedor` e `cota ou teto de gasto esgotado no provedor`
