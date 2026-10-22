# Delta: claim-verification

## MODIFIED Requirements

### Requirement: Status não altera validação nem veredito
O `status_afirmacao` SHALL ser um atributo novo, sem alterar os valores de `validation`/`status_validacao`, e SHALL NOT ser entrada de `compute_record` nem da regra de estado da hipótese. (Antes: não era entrada de `compute_verdict`.)

#### Scenario: Registro inalterado
- **GIVEN** uma hipótese com seis tentativas
- **WHEN** as afirmações sobre ela recebem cada um dos seis status possíveis
- **THEN** `compute_record` devolve os mesmos fatos em todos os casos
