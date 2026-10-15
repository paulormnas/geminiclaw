# Delta: execution-provenance

## ADDED Requirements

### Requirement: Entrada reescrita pela mesma execução
_Origem: `v18.7-benchmark-fixes` (achado 5 da bateria V18.6); relacionado ao ADR 019 §4._
Na conferência de arquivos de `verify`, quando um caminho aparece em `entradas` e em `saidas` do mesmo `termino`, a entrada SHALL ser marcada `substituido` com `detalhe="consumida e reescrita pela mesma execução"` e SHALL NOT ser comparada com o disco; a saída do mesmo registro SHALL continuar conferida contra o disco. As regras de último escritor e de código gerado (`.py`) não mudam.

#### Scenario: Retentativa que reescreve metrics.json
- **GIVEN** duas execuções registradas da mesma subtarefa, a primeira gravando `metrics.json` e a segunda encontrando-o na pasta da tarefa (entrada com o hash antigo) e reescrevendo-o com outro conteúdo (saída com o hash novo), sem outra alteração no disco
- **WHEN** `verify` é executado
- **THEN** a cadeia é íntegra e o código de saída é 0
- **AND** as duas referências antigas de `metrics.json` aparecem como `substituido` e a saída da segunda execução como `ok`

#### Scenario: Edição posterior continua detectada
- **GIVEN** o mesmo par de execuções e `metrics.json` editado no disco depois do segundo `termino`
- **WHEN** `verify` é executado
- **THEN** a saída da segunda execução aparece como `alterado` e o código de saída é 1

#### Scenario: Entrada lida sem reescrita
- **GIVEN** uma execução que lê `dados.csv` da pasta da tarefa sem reescrevê-lo, e `dados.csv` editado no disco depois do `termino`
- **WHEN** `verify` é executado
- **THEN** `dados.csv` aparece como `alterado` e o código de saída é 1
