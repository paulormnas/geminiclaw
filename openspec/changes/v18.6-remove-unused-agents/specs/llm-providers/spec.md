# Delta: llm-providers

## MODIFIED Requirements

### Requirement: Catálogo versionado e validado
O sistema SHALL carregar `src/llm/catalog.yaml` com `yaml.safe_load` e validá-lo por esquema
estrito antes de qualquer chamada de LLM, e SHALL interromper a inicialização, com mensagem
que cita o arquivo, o campo e o `id`, quando houver chave desconhecida, provedor não
registrado, `id` duplicado, valor fora do enum ou papel sem modelo na preferência
(ADR 017 §1, §9). Um papel removido (`reviewer`) SHALL ser rejeitado com mensagem que o identifica
como removido.
(Antes: seis papéis obrigatórios, incluindo `reviewer`.)

#### Scenario: Catálogo versionado válido
- **WHEN** o teste carrega o `src/llm/catalog.yaml` do repositório
- **THEN** a validação passa
- **AND** os cinco papéis (`researcher`, `developer`, `summarizer`, `validator`, `base`) têm ao menos um modelo na preferência

#### Scenario: Catálogo local com papel removido
- **GIVEN** um `catalog.local.yaml` com `papeis.reviewer`
- **WHEN** o catálogo é carregado
- **THEN** a inicialização para com erro que cita `reviewer` como papel removido

## ADDED Requirements

### Requirement: Variável de modelo obsoleta
Com `REVIEWER_MODEL` definida no ambiente, o sistema SHALL registrar `WARNING` na inicialização
informando que o papel foi removido, e SHALL seguir sem usá-la.

#### Scenario: `REVIEWER_MODEL` definida
- **GIVEN** `REVIEWER_MODEL=anthropic/claude-haiku-5-5`
- **WHEN** a sessão inicia
- **THEN** o log tem um `WARNING` que cita `REVIEWER_MODEL` e o papel removido

### Requirement: Rótulo da revisão de subtarefa
A chamada LLM e o evento da revisão de subtarefa SHALL ser registrados com o papel `validator` e
`funcao = "revisao_subtarefa"`.

#### Scenario: Telemetria da revisão
- **WHEN** `review_result` chama o modelo
- **THEN** o registro da chamada e o evento `subtask_review` têm papel `validator`
