# Delta: graph-cli

## ADDED Requirements

### Requirement: Visualização sem LLM
O sistema SHALL oferecer `geminiclaw graph show` e `geminiclaw graph node`, que exibem o grafo
do projeto com consultas fixas e somente-leitura, sem chamar nenhum LLM.

#### Scenario: Visualizar o projeto
- **WHEN** o pesquisador executa `geminiclaw graph show --project P`
- **THEN** a CLI exibe os nós e relações do projeto P, com veredito e leitura nos nós que os têm
- **AND** nenhum provedor LLM é chamado

#### Scenario: Filtros e formatos
- **WHEN** o pesquisador executa `graph show --label Descoberta --status ativa --format json`
- **THEN** a saída é JSON válido contendo apenas descobertas ativas do projeto

#### Scenario: Detalhe do nó
- **WHEN** o pesquisador executa `graph node <id>` sobre uma hipótese
- **THEN** a CLI exibe propriedades, relações, histórico de alterações e os fatores q, m, d, b, w de cada tentativa

#### Scenario: Grafo grande
- **WHEN** o subgrafo excede `GRAPH_SHOW_MAX_NODES`
- **THEN** a saída é truncada com aviso e sugestão de filtros

### Requirement: Alteração somente via Curator e com confirmação
O sistema SHALL tratar pedidos de alteração do grafo por `geminiclaw graph edit`: o Curator
propõe operações tipadas sem aplicá-las, a CLI as valida e exibe, e só as aplica após
confirmação do pesquisador.

#### Scenario: Proposta aplicada
- **WHEN** o pesquisador pede para marcar uma descoberta como contestada e confirma
- **THEN** o status muda, a autoria é `pesquisador` e a auditoria guarda o pedido original

#### Scenario: Proposta cancelada
- **WHEN** o pesquisador cancela a proposta
- **THEN** o grafo não é alterado

#### Scenario: Operação inválida
- **WHEN** a proposta contém uma relação não permitida pelo schema
- **THEN** a CLI aponta o erro antes de pedir confirmação

#### Scenario: Curator sem escrita no modo de edição
- **WHEN** o Curator é executado em modo de edição
- **THEN** ele dispõe apenas de ferramentas de leitura e de `propose_changes`

### Requirement: Nada é apagado por pedido do pesquisador
O sistema SHALL converter pedidos de remoção em mudanças de status.

#### Scenario: Pedido de remoção
- **WHEN** o pesquisador pede "apague a oportunidade Y"
- **THEN** a proposta muda o status de Y para `rejeitada` e explica que nada é apagado

### Requirement: Sem acesso direto ao banco
A CLI MUST NOT aceitar consultas Cypher ou SQL digitadas pelo pesquisador para escrita.

#### Scenario: Inventário de comandos
- **WHEN** os comandos `graph` são inspecionados
- **THEN** nenhum executa consulta de escrita fornecida pelo usuário
