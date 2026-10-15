# Delta: session-continuity

## ADDED Requirements

### Requirement: Retomada após cota ou gasto esgotado
_Origem: `v18.7-benchmark-fixes`._
Uma sessão fechada com `motivo_parada="limite_cota_provedor"` SHALL ser retomável sem confirmação, como os demais `limite_*`, e o valor SHALL constar da enumeração `Sessao.motivo_parada` do grafo. A retomada SHALL NOT conferir saldo no provedor; se a cota continuar esgotada, a nova sessão SHALL fechar de novo com o mesmo motivo.

#### Scenario: Retomada aceita
- **GIVEN** um checkpoint e o banco de sessões com `motivo_parada="limite_cota_provedor"`
- **WHEN** a retomabilidade é avaliada
- **THEN** o resultado é `RESUME_OK`

#### Scenario: Nó Sessao com o motivo novo
- **WHEN** um nó `Sessao` é gravado com `motivo_parada="limite_cota_provedor"`
- **THEN** a validação do schema aceita o valor
