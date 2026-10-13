# Delta: knowledge-graph

## ADDED Requirements

### Requirement: Grafo de conhecimento no PostgreSQL com Apache AGE
O sistema SHALL armazenar o grafo de conhecimento com a extensão Apache AGE no PostgreSQL 16
já existente, sem novo serviço em execução.

#### Scenario: Migração idempotente
- **WHEN** a migração `v17_001` é aplicada duas vezes
- **THEN** a segunda execução não falha e não duplica grafo, rótulos, índices nem papéis

### Requirement: Schema único e declarativo
O sistema SHALL validar toda escrita no grafo contra `src/knowledge/schema.py`, que define os
13 tipos de nó do ADR 015, suas propriedades, enumerações e as relações permitidas.

#### Scenario: Rótulo desconhecido
- **WHEN** `create_node("Pessoa", ...)` é chamado
- **THEN** a escrita é recusada com erro de validação

#### Scenario: Propriedade obrigatória ausente
- **WHEN** um `Problema` é criado sem `resumo`
- **THEN** a escrita é recusada indicando o campo ausente

#### Scenario: Enumeração inválida
- **WHEN** uma `Hipotese` é criada com `status="talvez"`
- **THEN** a escrita é recusada listando os valores válidos

#### Scenario: Relação não permitida
- **WHEN** uma aresta `Resultado-FUNCIONOU_PARA->Problema` é criada
- **THEN** a escrita é recusada, pois `FUNCIONOU_PARA` só parte de `Abordagem`

### Requirement: Proveniência obrigatória
O sistema SHALL preencher em todo nó `id`, `criado_em`, `atualizado_em`, `criado_por`,
`projeto_id`, `sessao_id`, `visibilidade` (default `privado`), `origem_no` (default `local`) e
`versao_schema`, derivando `criado_por` do `Actor` da operação.

#### Scenario: Autoria não forjável
- **GIVEN** uma escrita feita pelo `Actor` agente `curator` com o modelo `qwen3:8b`
- **WHEN** as propriedades enviadas incluem `criado_por="pesquisador"`
- **THEN** o nó é gravado com `criado_por="curator/qwen3:8b"`

#### Scenario: Nó de agente sem justificativa
- **WHEN** um agente cria uma `Descoberta` sem `justificativa_criacao`
- **THEN** a escrita é recusada

### Requirement: Nada é apagado
O sistema MUST NOT oferecer operação de remoção de nós ou arestas de conhecimento; correções
são mudanças de status ou novos nós, com auditoria.

#### Scenario: Campos imutáveis
- **WHEN** `update_node` tenta alterar `id`, `criado_em`, `criado_por` ou `projeto_id`
- **THEN** a alteração é recusada

#### Scenario: Auditoria de alterações
- **WHEN** o status de uma `Descoberta` muda de `ativa` para `contestada`
- **THEN** um registro em `knowledge_audit` guarda o nó, o autor, a data e a mudança

### Requirement: Escrita sem injeção de consulta
O sistema MUST montar consultas de escrita apenas com rótulos e relações da whitelist do schema
e passar todos os valores como parâmetros.

#### Scenario: Valor malicioso
- **WHEN** um nó é criado com `titulo = "x'}) MATCH (n) DETACH DELETE n //"`
- **THEN** o título é gravado literalmente e nenhum outro nó é afetado

### Requirement: Consultas livres somente-leitura
O sistema SHALL executar consultas Cypher livres somente com o papel de banco
`knowledge_reader`, em transação somente-leitura e com timeout.

#### Scenario: Tentativa de escrita em consulta livre
- **WHEN** `read_query("CREATE (n:Projeto {titulo: 'x'})", {})` é chamado
- **THEN** a consulta é recusada e o grafo não muda

#### Scenario: Consulta lenta
- **WHEN** uma consulta excede `KNOWLEDGE_READ_TIMEOUT_MS`
- **THEN** ela é cancelada e um erro de timeout é retornado

### Requirement: Identificador do computador
O sistema SHALL gerar uma vez e persistir `NODE_ID`, registrado em sessões e experimentos.

#### Scenario: NODE_ID estável
- **WHEN** o sistema é reiniciado
- **THEN** o mesmo `NODE_ID` é usado
