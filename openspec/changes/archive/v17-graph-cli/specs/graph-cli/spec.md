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

### Requirement: Saída segura no terminal
O sistema SHALL remover da saída da CLI (`graph show`, `graph node`, proposta de `graph edit`, mensagens de erro)
os caracteres de controle de terminal vindos do conteúdo do grafo, do pedido ou do LLM, e SHALL limitar tamanhos.

#### Scenario: Sequências de escape no conteúdo
- **WHEN** um nó contém ESC, ANSI/OSC, caracteres de controle C0/C1, marcas bidi ou de largura zero
- **THEN** nenhum deles chega ao terminal em nenhum formato (`text`, `table`, `json`, `mermaid`)

#### Scenario: Mermaid com entidades e diretivas
- **WHEN** um texto do grafo contém `#lt;`, `"`, `]`, `click`, `%%{init}` ou quebra de linha
- **THEN** `#` e os demais delimitadores saem como entidades e nenhuma linha extra ou diretiva é criada

### Requirement: Escopo do projeto e visibilidade
O sistema SHALL restringir a visualização ao projeto ativo e aos nós compartilháveis, e a alteração ao projeto ativo.

#### Scenario: Nó de outro projeto
- **WHEN** o pesquisador consulta ou tenta alterar um nó privado de outro projeto
- **THEN** a resposta é "não encontrado" (idêntica à de nó inexistente) e nada é alterado

#### Scenario: Relações com outros projetos
- **WHEN** um nó compartilhável tem relações com nós de outros projetos
- **THEN** a saída não mostra nem conta essas relações

### Requirement: Confirmação humana interativa e exata
O sistema SHALL aplicar uma alteração somente depois de o pesquisador digitar a palavra exata `aplicar` em terminal
interativo, para a proposta exibida, sem opção `--yes` e sem aceitar confirmação de LLM, arquivo ou pipe.

#### Scenario: Sem terminal interativo
- **WHEN** `graph edit` roda sem TTY em stdin ou stdout
- **THEN** a CLI recusa antes de chamar o LLM e nada é alterado

#### Scenario: Resposta que não é a palavra exata
- **WHEN** a resposta é `APLICAR`, ` aplicar`, `sim` ou vazia
- **THEN** nada é alterado

#### Scenario: Aplicação exige prova de confirmação
- **WHEN** `apply_plan` é chamado sem `HumanConfirmation` válida, ou com a de outra proposta
- **THEN** nada é escrito

### Requirement: O que é aplicado é o que foi mostrado
O sistema SHALL exibir por inteiro todo valor que será gravado e SHALL recusar a proposta que não couber na tela.

#### Scenario: Valor longo
- **WHEN** uma operação grava um texto com mais de 80 caracteres
- **THEN** a proposta exibe o texto integral e o grafo recebe exatamente esse texto

#### Scenario: Propriedades de relação
- **WHEN** `create_edge` informa `origem`, `status`, `evidencias` ou outra propriedade de proveniência/derivada
- **THEN** a proposta é recusada; a relação nasce `afirmado`, `confirmada` e sem evidências, e a proposta declara isso

#### Scenario: Plano alterado depois da exibição
- **WHEN** o conteúdo do plano muda depois da confirmação
- **THEN** a impressão digital difere e a aplicação é abortada

#### Scenario: Estado alterado depois da proposta
- **WHEN** o nó ou a relação mudou entre a exibição e a aplicação
- **THEN** a aplicação é abortada sem escrever

### Requirement: Decisões reservadas e fatos preservados
O sistema SHALL recusar em `graph edit` as alterações reservadas a outros comandos ou ao cálculo determinístico.

#### Scenario: Rótulos e relações protegidos
- **WHEN** a proposta altera ou cria relação a partir de `Problema`, `Projeto`, `Dominio`, `Metrica` ou fato estrutural
  (`Sessao`, `Insumo`, `Experimento`, `Resultado`), ou altera campos calculados ou de proveniência
- **THEN** a CLI aponta o erro e orienta o comando próprio

#### Scenario: Decisão sobre Oportunidade
- **WHEN** a proposta muda o status de uma `Oportunidade`
- **THEN** exige autorização adicional do `HumanGate`, cujo prompt identifica o alvo e o novo status, e
  `decidido_em` é o instante da aplicação

### Requirement: Referências e aplicação atômica
O sistema SHALL aceitar `$N` apenas para um `create_node` anterior da mesma proposta e SHALL reverter o que for
reversível se uma escrita falhar, reportando e auditando qualquer falha de reversão.

#### Scenario: Referência `$N`
- **WHEN** `$N` aponta para operação que não é `create_node` anterior, ou é usada em `update_node`/`set_edge_status`
- **THEN** a proposta é recusada

#### Scenario: Falha na aplicação
- **WHEN** uma escrita falha no meio da aplicação
- **THEN** as alterações reversíveis voltam ao valor anterior, a falha de reversão (se houver) é reportada ao
  pesquisador e registrada na auditoria, e os nós criados permanecem (nada é apagado)
