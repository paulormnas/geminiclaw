# Delta: research-project

Testes com o Researcher simulado (rascunho gravado) e CLI com entrada simulada.

## MODIFIED Requirements

### Requirement: Problema redigido pelo Researcher e confirmado pelo pesquisador
O sistema SHALL, na primeira sessão de um projeto, obter do Researcher um rascunho do `Problema` em alto nível, com o objetivo tipado (`tipo` e os campos do tipo, spec `hypothesis-loop`), e exigir a confirmação do pesquisador antes de qualquer planejamento ou experimento, em todos os modos de sessão. `delta_min` SHALL ser exigido só no tipo `limiar`; `hipoteses_concorrentes` com ao menos 2 itens e predição SHALL ser exigidas no `discriminacao`; `fronteira` SHALL ser recusado nesta etapa. No `assisted` e no `semi`, o objetivo SHALL estar completo na confirmação; no `auto`, o pesquisador MAY confirmar o `Problema` sem objetivo, que o Researcher então propõe no primeiro plano para o Validator aprovar. O pesquisador MAY definir `ao_atingir_objetivo` na confirmação (ADR 021 §5.2, §5.3).

#### Scenario: Confirmação
- **WHEN** o pesquisador confirma o rascunho
- **THEN** o `Problema` é gravado com `status="confirmado"`, ligado ao projeto por `INVESTIGA` e aos domínios por `NO_DOMINIO`
- **AND** a confirmação é auditada com autor `pesquisador`

#### Scenario: Edição de campo
- **WHEN** o pesquisador altera `delta_min` de 0,05 para 0,02 num rascunho `limiar` antes de confirmar
- **THEN** o problema confirmado tem `criterio_sucesso.delta_min = 0,02`

#### Scenario: Modo autônomo
- **GIVEN** modo `auto` e projeto sem problema confirmado
- **WHEN** a sessão começa em terminal interativo
- **THEN** a confirmação é pedida uma única vez antes da execução autônoma

#### Scenario: delta_min ausente no limiar
- **GIVEN** um rascunho `tipo = "limiar"` com `delta_min = null`
- **WHEN** o pesquisador tenta confirmar
- **THEN** a CLI exige o valor antes de gravar

#### Scenario: Discriminação sem delta_min
- **GIVEN** um rascunho `tipo = "discriminacao"` com duas hipóteses concorrentes, cada uma com predição, e sem `delta_min`
- **WHEN** o pesquisador confirma em modo `semi`
- **THEN** o `Problema` é gravado e as duas hipóteses existem com `concorrente = true`, `predicao` e `origem = "pesquisador"`

#### Scenario: Discriminação com uma só concorrente
- **GIVEN** um rascunho `tipo = "discriminacao"` com uma hipótese concorrente
- **WHEN** o pesquisador tenta confirmar
- **THEN** a CLI exige ao menos duas concorrentes com predição

#### Scenario: Objetivo ausente no modo automático
- **GIVEN** modo `auto` e um rascunho sem `tipo` nem campos de objetivo
- **WHEN** o pesquisador confirma
- **THEN** o `Problema` é gravado e o primeiro plano exige a chave `objetivo`

#### Scenario: Objetivo ausente no modo assistido
- **GIVEN** modo `assisted` e o mesmo rascunho
- **WHEN** o pesquisador tenta confirmar
- **THEN** a CLI pede o tipo de objetivo antes de gravar

#### Scenario: Política definida pelo pesquisador
- **WHEN** o pesquisador escolhe `continuar` em `ao_atingir_objetivo` na confirmação
- **THEN** `criterio_sucesso.ao_atingir_objetivo` é `continuar`

#### Scenario: Sessão não interativa
- **GIVEN** projeto sem problema confirmado e execução sem TTY
- **WHEN** a sessão começa
- **THEN** a execução é recusada com orientação para confirmar o problema

#### Scenario: Sessões seguintes
- **GIVEN** um projeto com problema confirmado
- **WHEN** uma nova sessão começa
- **THEN** nenhuma confirmação é pedida e o problema é injetado no contexto do Researcher

## ADDED Requirements

### Requirement: Objetivo e restrições pela CLI do projeto
O sistema SHALL oferecer, no processo do terminal, `geminiclaw project objective <projeto> --ao-atingir parar|perguntar|continuar` (muda a política), `geminiclaw project objective <projeto> --atingido` (declara atingido um objetivo `cobertura`), `geminiclaw project restrict`, `geminiclaw project restrictions` e `geminiclaw project unrestrict` (spec `knowledge-graph`). Cada ação SHALL ser auditada com autor `pesquisador` (ADR 021 §5.3, §5.5).

#### Scenario: Mudar a política
- **GIVEN** um `Problema` sem `ao_atingir_objetivo`
- **WHEN** o pesquisador executa `geminiclaw project objective p1 --ao-atingir perguntar`
- **THEN** `criterio_sucesso.ao_atingir_objetivo` é `perguntar` e a auditoria registra o pesquisador

#### Scenario: Atingido em tipo errado
- **GIVEN** um `Problema` `limiar`
- **WHEN** o pesquisador executa `geminiclaw project objective p1 --atingido`
- **THEN** a CLI recusa, explicando que só a `cobertura` é declarada atingida pelo pesquisador
