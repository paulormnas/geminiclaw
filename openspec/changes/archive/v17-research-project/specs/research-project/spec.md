# Delta: research-project

## ADDED Requirements

### Requirement: Projeto de pesquisa
O sistema SHALL organizar sessões em projetos, cada um representado por um nó `Projeto`, e
permitir criar, listar, exibir e selecionar projetos pela CLI.

#### Scenario: Sessão em projeto existente
- **WHEN** o pesquisador executa `geminiclaw --project <id> "<prompt>"`
- **THEN** a sessão é criada com `project_id=<id>` no payload

#### Scenario: Sem projeto informado
- **GIVEN** nenhum `--project` e nenhum projeto padrão
- **WHEN** um prompt é executado
- **THEN** um projeto é criado com título derivado do prompt e o ID é exibido

### Requirement: Problema redigido pelo Researcher e confirmado pelo pesquisador
O sistema SHALL, na primeira sessão de um projeto, obter do Researcher um rascunho do
`Problema` em alto nível e exigir a confirmação do pesquisador antes de qualquer planejamento
ou experimento, em todos os modos de sessão.

#### Scenario: Confirmação
- **WHEN** o pesquisador confirma o rascunho
- **THEN** o `Problema` é gravado com `status="confirmado"`, ligado ao projeto por `INVESTIGA` e aos domínios por `NO_DOMINIO`
- **AND** a confirmação é auditada com autor `pesquisador`

#### Scenario: Edição de campo
- **WHEN** o pesquisador altera `delta_min` de 0,05 para 0,02 antes de confirmar
- **THEN** o problema confirmado tem `criterio_sucesso.delta_min = 0,02`

#### Scenario: delta_min ausente
- **GIVEN** um rascunho com `delta_min = null`
- **WHEN** o pesquisador tenta confirmar
- **THEN** a CLI exige o valor antes de gravar

#### Scenario: Modo autônomo
- **GIVEN** modo `auto` e projeto sem problema confirmado
- **WHEN** a sessão começa em terminal interativo
- **THEN** a confirmação é pedida uma única vez antes da execução autônoma

#### Scenario: Sessão não interativa
- **GIVEN** projeto sem problema confirmado e execução sem TTY
- **WHEN** a sessão começa
- **THEN** a execução é recusada com orientação para confirmar o problema

#### Scenario: Sessões seguintes
- **GIVEN** um projeto com problema confirmado
- **WHEN** uma nova sessão começa
- **THEN** nenhuma confirmação é pedida e o problema é injetado no contexto do Researcher

### Requirement: Problema independente de técnica
O rascunho do `Problema` SHALL descrever contexto, lacuna, objetivo e critério de avanço sem
citar a técnica que será usada.

#### Scenario: Instrução do rascunho
- **WHEN** a instrução de rascunho é renderizada
- **THEN** ela pede um resumo em alto nível, no estilo de resumo de artigo sem resultados, sem mencionar a abordagem
