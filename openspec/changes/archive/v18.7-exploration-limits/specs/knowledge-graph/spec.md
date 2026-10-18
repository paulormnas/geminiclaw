# Delta: knowledge-graph

Alteração de schema aditiva (aprovação do pesquisador exigida, `proposal.md`). Testes com o grafo em memória e, para a migração, PostgreSQL com AGE do ambiente de integração.

## MODIFIED Requirements

### Requirement: Schema único e declarativo
O sistema SHALL validar toda escrita no grafo contra `src/knowledge/schema.py`, que define os tipos de nó do ADR 015 mais `Restricao` (ADR 021 §5.5), suas propriedades, enumerações e as relações permitidas. A validação SHALL incluir a estrutura de `Problema.criterio_sucesso` por tipo de objetivo (ADR 021 §5.2).

#### Scenario: Rótulo desconhecido
- **WHEN** `create_node("Pessoa", ...)` é chamado
- **THEN** a escrita é recusada com erro de validação

#### Scenario: Tipo de objetivo inválido
- **WHEN** um `Problema` é gravado com `criterio_sucesso = {tipo: "maximo"}`
- **THEN** a escrita é recusada listando `limiar`, `discriminacao`, `cobertura` e `fronteira`

#### Scenario: Campo proibido pelo tipo
- **WHEN** um `Problema` é gravado com `criterio_sucesso = {tipo: "discriminacao", alvo: 0.9, hipoteses_concorrentes: [...]}`
- **THEN** a escrita é recusada citando `alvo`

#### Scenario: Política inválida
- **WHEN** um `Problema` é gravado com `criterio_sucesso.ao_atingir_objetivo = "talvez"`
- **THEN** a escrita é recusada listando `parar`, `perguntar` e `continuar`

#### Scenario: Problema antigo continua válido
- **GIVEN** um `Problema` existente com `criterio_sucesso` sem `tipo`
- **WHEN** outra propriedade dele é atualizada
- **THEN** a escrita é aceita

## ADDED Requirements

### Requirement: Campos do pesquisador no objetivo protegidos no grafo
A validação do grafo (`src/knowledge/validation.py`, pelo mesmo mecanismo de `HUMAN_ONLY_TRANSITIONS`) SHALL aceitar a gravação ou a alteração de `Problema.criterio_sucesso.ao_atingir_objetivo` e de `criterio_sucesso.definido_por = "pesquisador"` somente pelo `Actor` pesquisador: no processo do terminal (confirmação do `Problema`, `geminiclaw project objective`) ou no processo da sessão depois de `consume_authorized` de um pedido `confirmar_problema` respondido pelo terminal. Escrita desses campos por qualquer outro `Actor`, inclusive o orquestrador e os agentes, MUST ser recusada, e o orquestrador MUST NOT substituir um `criterio_sucesso` com `definido_por = "pesquisador"` (ADR 021 §5.2, §5.3; parecer de segurança, item 1).

#### Scenario: Orquestrador grava a política
- **WHEN** o `Actor` orquestrador atualiza um `Problema` com `criterio_sucesso.ao_atingir_objetivo = "continuar"`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Agente se declara pesquisador
- **WHEN** o `Actor` agente `Researcher` grava `criterio_sucesso` com `definido_por = "pesquisador"`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Orquestrador substitui o objetivo do pesquisador
- **GIVEN** um `Problema` com `criterio_sucesso.definido_por = "pesquisador"`
- **WHEN** o `Actor` orquestrador grava um `criterio_sucesso` aprovado no plano com `definido_por = "agente"`
- **THEN** a escrita é recusada e o critério do pesquisador continua gravado

#### Scenario: Objetivo do agente no auto
- **GIVEN** um `Problema` sem objetivo válido
- **WHEN** o `Actor` orquestrador grava `criterio_sucesso` com `definido_por = "agente"` e sem `ao_atingir_objetivo`
- **THEN** a escrita é aceita

#### Scenario: Pesquisador define a política
- **WHEN** o `Actor` pesquisador executa `geminiclaw project objective p1 --ao-atingir continuar`
- **THEN** a escrita é aceita e a trilha de auditoria registra o pesquisador

### Requirement: Abandono por restrição com autoridade da restrição
A retirada de hipótese por restrição de direção SHALL gravar `abandonada_por = "pesquisador"` e `motivo_abandono = "direcao_restrita:<restricao_id>"` com o `Actor` pesquisador derivado da `Restricao` (o ator cita o `restricao_id`). A validação do grafo SHALL aceitar essa escrita só quando a `Restricao` citada existe, tem `decidida_por = "pesquisador"` e `status = "ativa"`, e SHALL recusar a derivação em qualquer outra escrita, de modo que a regra de autoridade de `v18.7-graph-exploration-relations` (design §2.3) continue fechada a outros caminhos (parecer de segurança, item 3).

#### Scenario: Retirada com restrição ativa
- **GIVEN** a `Restricao(r1, status="ativa", decidida_por="pesquisador")`
- **WHEN** a sessão grava `status = "abandonada"`, `abandonada_por = "pesquisador"` e `motivo_abandono = "direcao_restrita:r1"` com o ator derivado de `r1`
- **THEN** a escrita é aceita e a trilha de auditoria registra `r1`

#### Scenario: Restrição revogada não autoriza
- **GIVEN** a `Restricao(r1, status="revogada")`
- **WHEN** a sessão tenta a mesma escrita com o ator derivado de `r1`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Restrição inexistente
- **WHEN** a sessão tenta a escrita com o ator derivado de `r_inexistente`
- **THEN** a escrita é recusada

### Requirement: Motivos de parada da exploração longa
O enum de `Sessao.motivo_parada` SHALL aceitar `limite_custo` e `saturacao`, SHALL manter `limite_ciclos` e `limite_execucoes` para os nós existentes (o código deixa de gravá-los) e SHALL manter `limite_cota_provedor` de `v18.7-benchmark-fixes` (ADR 021, cabeçalho, mudança no ADR 015 §8).

#### Scenario: Novos valores
- **WHEN** um nó `Sessao` é gravado com `motivo_parada = "saturacao"` e outro com `"limite_custo"`
- **THEN** as duas escritas são aceitas

### Requirement: Marco de objetivo atingido
O `Problema` SHALL aceitar a propriedade `objetivo_atingido`, lista de marcos `{em, sessao_id, tipo, desfecho, resultado_id, hipotese_id, valor}`, acrescentada pelo orquestrador a cada atingimento e nunca sobrescrita (ADR 021 §5.3). Agentes MUST NOT escrevê-la.

#### Scenario: Segundo marco
- **GIVEN** um `Problema` com um marco de uma sessão anterior
- **WHEN** outra sessão atinge o objetivo
- **THEN** a lista tem os dois marcos, na ordem

#### Scenario: Agente tenta escrever
- **WHEN** o ator `Researcher` tenta atualizar `objetivo_atingido`
- **THEN** a escrita é recusada pela barreira de valores permitidos a agentes

### Requirement: Predições das hipóteses concorrentes
`Hipotese` SHALL aceitar `concorrente` (booleano) e `predicao` (texto até `HYPOTHESIS_TEXT_MAX_CHARS`), e `Experimento` SHALL aceitar `conferencia_predicoes` (mapa `hipotese_id` → `confirma` | `contraria` | `inconclusiva`) (ADR 021 §5.2). Nós sem essas propriedades SHALL ser lidos como `concorrente = false` e sem conferência.

#### Scenario: Conferência inválida
- **WHEN** um `Experimento` é gravado com `conferencia_predicoes = {"h1": "talvez"}`
- **THEN** a escrita é recusada listando os três valores válidos

### Requirement: Restrição de direção como nó
O schema SHALL ter o nó `Restricao` (`direcao` obrigatória, `categoria` em `seguranca` | `etica` | `recurso`, `abordagens` lista, `status` em `ativa` | `revogada`, `decidida_por` = `pesquisador`, `decidida_em`, `pedido_id`) e a relação `(Restricao)-[:RESTRINGE]->(Problema|Projeto)`. A validação do grafo (`src/knowledge/validation.py`) SHALL aceitar a criação ou a revogação de `Restricao` só em dois caminhos: pelo `Actor` pesquisador no processo do terminal (comandos `project restrict` e `project unrestrict`, `pedido_id` vazio), ou pelo processo da sessão depois que `PersistentGate.consume_authorized("restringir_direcao", referencia, session_chain)` de `v18.7-persistent-human-gate` devolver um pedido autorizado e consumido, caso em que `pedido_id` MUST ser o id desse pedido. Qualquer outra escrita, inclusive do `Actor` orquestrador sem pedido autorizado e consumido, MUST ser recusada; a revogação SHALL mudar `status` e nunca apagar o nó. O rótulo e a relação SHALL ser criados pela migração idempotente do grafo, a mesma usada por `v18.7-graph-exploration-relations` (ADR 021 §5.5).

#### Scenario: Criação pelo pesquisador
- **WHEN** `geminiclaw project restrict p1 --direcao "uso de reagente perigoso" --categoria seguranca --abordagem sintese_com_reagente_x` é executado
- **THEN** existe `Restricao(status="ativa", decidida_por="pesquisador")` com `RESTRINGE->Projeto(p1)` e a trilha de auditoria registra o pesquisador

#### Scenario: Agente não cria restrição
- **WHEN** o ator `Curator` tenta criar um nó `Restricao`
- **THEN** a escrita é recusada

#### Scenario: Orquestrador sem pedido autorizado é recusado
- **GIVEN** uma sessão `auto` sem pedido `restringir_direcao` autorizado
- **WHEN** o `Actor` orquestrador tenta criar um nó `Restricao` com `decidida_por = "pesquisador"`
- **THEN** a escrita é recusada e nenhum nó `Restricao` existe

#### Scenario: Pedido já consumido não cria segunda restrição
- **GIVEN** um pedido `restringir_direcao` autorizado pelo terminal e já consumido por uma `Restricao`
- **WHEN** o processo da sessão tenta criar outra `Restricao` citando o mesmo `pedido_id`
- **THEN** `consume_authorized` recusa com `ja_consumida` e a escrita não ocorre

#### Scenario: Sessão sem pedido_id
- **GIVEN** um pedido `restringir_direcao` autorizado e consumido
- **WHEN** o processo da sessão grava a `Restricao` sem `pedido_id`
- **THEN** a escrita é recusada citando `pedido_id`

#### Scenario: Revogação não apaga
- **WHEN** `geminiclaw project unrestrict <id>` é executado
- **THEN** o nó continua existindo com `status = "revogada"`

#### Scenario: Migração idempotente
- **WHEN** a migração do grafo é aplicada duas vezes
- **THEN** a segunda execução não falha e o rótulo `Restricao` existe uma vez
