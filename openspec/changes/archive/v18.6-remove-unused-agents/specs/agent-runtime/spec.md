# Delta: agent-runtime

## ADDED Requirements

### Requirement: Papéis de subtarefa do plano
Uma subtarefa do plano SHALL ser atribuída só a `developer` ou `researcher`. O normalizador do plano
SHALL reparar `base` para `developer` e SHALL tratar `reviewer` e `summarizer` (e sinônimos) como não
recuperáveis, com mensagem que lista os papéis válidos.

#### Scenario: `base` no plano
- **GIVEN** um plano com uma subtarefa `agent_id: "base"`
- **WHEN** o plano é normalizado
- **THEN** a subtarefa fica com `agent_id = "developer"`
- **AND** o reparo `normalize_agent_id` é registrado

#### Scenario: `reviewer` no plano
- **GIVEN** um plano com uma subtarefa `agent_id: "reviewer"`
- **WHEN** o plano é normalizado
- **THEN** o plano tem um problema não recuperável que cita `developer` e `researcher`

#### Scenario: Papéis internos continuam executáveis
- **WHEN** o runtime em processo monta `AGENT_DEFINITIONS`
- **THEN** o registro contém `developer`, `researcher`, `summarizer`, `base` e `curator`
- **AND** não contém `reviewer`

## REMOVED Requirements

### Requirement: Agente Reviewer
O agente `reviewer` (`agents/reviewer/`) foi removido: a revisão de subtarefa é feita pelo
`validator` (ADR 007).
