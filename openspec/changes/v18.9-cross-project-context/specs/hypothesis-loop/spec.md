# Delta: hypothesis-loop

## ADDED Requirements

### Requirement: Candidatos estruturais no ciclo
Ao fim de cada ciclo, o sistema SHALL gerar candidatos estruturais. Os candidatos do próprio projeto SHALL entrar no bloco de sugestões do Researcher. Com `CROSS_PROJECT_CANDIDATES=true`, os candidatos vindos de outro projeto SHALL virar `Oportunidade` com `origem = "grafo"`, aguardando o pesquisador, e SHALL NOT virar hipótese sem aprovação.

#### Scenario: Candidato do mesmo projeto
- **GIVEN** duas variações do mesmo pai com `delta_pai > 0`, ainda não combinadas
- **WHEN** o ciclo termina
- **THEN** a próxima chamada ao Researcher contém uma sugestão `composicao` com as duas abordagens

#### Scenario: Candidato de outro projeto desligado
- **GIVEN** `CROSS_PROJECT_CANDIDATES=false` e um candidato `transferencia` vindo de outro projeto
- **WHEN** o ciclo termina
- **THEN** nenhuma `Oportunidade` é criada

#### Scenario: Candidato de outro projeto ligado
- **GIVEN** `CROSS_PROJECT_CANDIDATES=true` e o mesmo candidato
- **WHEN** o ciclo termina
- **THEN** existe uma `Oportunidade` com `origem = "grafo"` e status `documentada` (aguarda o pesquisador), e nenhuma hipótese nova
