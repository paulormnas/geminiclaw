# Delta: vocabulary

## ADDED Requirements

### Requirement: Métrica definida e aprovada por agente
Uma `Metrica` definida pelo Researcher e validada pelo Validator SHALL ser gravada com `status = "aprovado"`,
`origem_definicao = "agente"`, `aprovada_por = "validator"` e `justificativa_definicao`. As três propriedades são
opcionais; a ausência de `origem_definicao` e de `aprovada_por` equivale a `pesquisador`. A aprovação SHALL ser escrita pelo orquestrador somente depois do parecer favorável do Validator; nenhum agente SHALL poder aprovar `Metrica`. O sistema SHALL NOT alterar
uma `Metrica` aprovada pelo pesquisador nem aprovar uma `Metrica` rejeitada por ele por esse caminho.

#### Scenario: Gravação com origem do agente
- **GIVEN** uma `Metrica` candidata `f1_macro`
- **WHEN** a definição do agente é aplicada após a validação
- **THEN** o nó tem `status = "aprovado"`, `origem_definicao = "agente"`, `aprovada_por = "validator"`
- **AND** a trilha de auditoria registra o ator `orquestrador` (a barreira que impede agentes de aprovar `Metrica` continua valendo)

#### Scenario: Nó antigo sem as propriedades
- **GIVEN** uma `Metrica` aprovada semeada, sem `origem_definicao` nem `aprovada_por`
- **WHEN** o schema é validado
- **THEN** o nó continua válido e é tratado como aprovado pelo pesquisador
