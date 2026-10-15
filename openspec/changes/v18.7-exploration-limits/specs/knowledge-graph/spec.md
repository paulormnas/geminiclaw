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
O schema SHALL ter o nó `Restricao` (`direcao` obrigatória, `categoria` em `seguranca` | `etica` | `recurso`, `abordagens` lista, `status` em `ativa` | `revogada`, `decidida_por` = `pesquisador`, `decidida_em`, `pedido_id` opcional) e a relação `(Restricao)-[:RESTRINGE]->(Problema|Projeto)`. Só o ator `orquestrador`, a partir de ação do pesquisador, SHALL criar ou revogar `Restricao`; a revogação SHALL mudar `status` e nunca apagar o nó. O rótulo e a relação SHALL ser criados pela migração idempotente do grafo, a mesma usada por `v18.7-graph-exploration-relations` (ADR 021 §5.5).

#### Scenario: Criação pelo pesquisador
- **WHEN** `geminiclaw project restrict p1 --direcao "uso de reagente perigoso" --categoria seguranca --abordagem sintese_com_reagente_x` é executado
- **THEN** existe `Restricao(status="ativa", decidida_por="pesquisador")` com `RESTRINGE->Projeto(p1)` e a trilha de auditoria registra o pesquisador

#### Scenario: Agente não cria restrição
- **WHEN** o ator `Curator` tenta criar um nó `Restricao`
- **THEN** a escrita é recusada

#### Scenario: Revogação não apaga
- **WHEN** `geminiclaw project unrestrict <id>` é executado
- **THEN** o nó continua existindo com `status = "revogada"`

#### Scenario: Migração idempotente
- **WHEN** a migração do grafo é aplicada duas vezes
- **THEN** a segunda execução não falha e o rótulo `Restricao` existe uma vez
