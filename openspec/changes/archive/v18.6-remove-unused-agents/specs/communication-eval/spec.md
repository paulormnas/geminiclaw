# Delta: communication-eval

## ADDED Requirements

### Requirement: Métricas da revisão de subtarefa com rótulo novo
O relatório de comunicação SHALL publicar as métricas da revisão de subtarefa na chave
`revisao_subtarefa` e SHALL ler eventos `subtask_review` com `agent_id` `validator` ou `reviewer`
(sessões gravadas antes da V18.6). O pool do juiz da avaliação SHALL excluir `reviewer`.

#### Scenario: Sessão antiga
- **GIVEN** uma sessão com eventos `subtask_review` de `agent_id = "reviewer"`
- **WHEN** o relatório de comunicação é gerado
- **THEN** as revisões aparecem em `revisao_subtarefa`

#### Scenario: Pool do juiz
- **WHEN** `select_judge` monta o pool
- **THEN** o pool não contém `reviewer`
