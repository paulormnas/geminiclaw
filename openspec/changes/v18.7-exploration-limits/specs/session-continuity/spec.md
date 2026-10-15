# Delta: session-continuity

## ADDED Requirements

### Requirement: Retomada conforme os motivos de parada da exploração longa
`evaluate_resumability` SHALL tratar `limite_custo` como os demais `limite_*` (retomável sem perguntar), SHALL pedir confirmação para `saturacao`, com a mensagem que cita `saturacao` e explica que a melhora possível ficou abaixo do erro da medida, e SHALL continuar aceitando sem perguntar `limite_ciclos` e `limite_execucoes` de sessões anteriores a esta mudança. `limite_cota_provedor` (`v18.7-benchmark-fixes`) SHALL continuar retomável sem perguntar (ADR 021 §5, "Mudanças OpenSpec exigidas"; `src/continuity.py:64-70`).

#### Scenario: Limite de custo
- **GIVEN** uma sessão fechada com `motivo_parada = "limite_custo"` no banco e no checkpoint
- **WHEN** o pesquisador executa `geminiclaw resume --session <id>`
- **THEN** a avaliação devolve `RESUME_OK` e a nova sessão recebe orçamento novo

#### Scenario: Saturação pede confirmação
- **GIVEN** uma sessão fechada com `motivo_parada = "saturacao"`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a avaliação devolve `RESUME_CONFIRM` com mensagem que contém `saturacao`

#### Scenario: Sessão antiga com teto de ciclos
- **GIVEN** uma sessão fechada antes desta mudança com `motivo_parada = "limite_ciclos"`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a avaliação devolve `RESUME_OK`

### Requirement: Estado da exploração restaurado na retomada
O checkpoint SHALL levar `exploracao_estado` (ciclos sem avanço, intervenções feitas, melhor valor e EP, desfecho, janela de novidade, objetivo atingido na sessão e política efetiva), validado como dado não confiável (tipos, faixas e tamanho), e a retomada SHALL restaurá-lo na `ExplorationSession`; valor inválido SHALL ser descartado com aviso, começando do zero, sem recusar a retomada.

#### Scenario: Estado inválido
- **GIVEN** um checkpoint com `exploracao_estado.intervencoes = -4`
- **WHEN** a sessão é retomada
- **THEN** a retomada segue com `intervencoes = 0` e o evento `exploracao_estado_descartado` é registrado
