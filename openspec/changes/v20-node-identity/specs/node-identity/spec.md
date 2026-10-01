# Delta: node-identity

## ADDED Requirements

### Requirement: Par de chaves do nó
Com `FEDERATION_ENABLED=true`, o sistema SHALL carregar ou gerar um par de chaves Ed25519 do nó,
SHALL gravá-lo atomicamente com permissão `0600` em diretório `0700`, e SHALL derivar o
`id_federado` da chave pública (ADR 013 §2).

#### Scenario: Primeira ativação
- **GIVEN** um diretório de configuração vazio
- **WHEN** `geminiclaw federation identity init` roda
- **THEN** o arquivo de chave existe com modo `0600`
- **AND** o `id_federado` exibido começa com `ed25519:` e tem 40 caracteres

#### Scenario: Identidade estável
- **GIVEN** uma chave já criada
- **WHEN** o processo reinicia e carrega a identidade
- **THEN** o `id_federado` é o mesmo

#### Scenario: Federação desligada
- **GIVEN** `FEDERATION_ENABLED=false`
- **WHEN** uma sessão roda
- **THEN** nenhum arquivo de chave é criado

### Requirement: Sem identidade efêmera
Com a federação ligada, o sistema SHALL interromper a inicialização com erro que cita o
caminho quando a chave não puder ser lida ou gravada, e MUST NOT gerar identidade temporária.

#### Scenario: Diretório sem permissão de escrita
- **GIVEN** o diretório da chave sem permissão de escrita e nenhuma chave existente
- **WHEN** a federação é inicializada
- **THEN** a inicialização para com erro que cita o caminho

#### Scenario: Chave corrompida
- **GIVEN** um arquivo de chave com conteúdo inválido
- **WHEN** a federação é inicializada
- **THEN** a inicialização para e o arquivo não é sobrescrito

### Requirement: Assinatura e verificação
O sistema SHALL assinar bytes canônicos com a chave do nó e SHALL verificar assinaturas de
outros nós pela chave pública, retornando falso para qualquer alteração de um único byte.

#### Scenario: Assinatura válida
- **WHEN** um payload é assinado e verificado com a chave pública do mesmo nó
- **THEN** a verificação é verdadeira

#### Scenario: Payload alterado
- **WHEN** um byte do payload assinado é trocado
- **THEN** a verificação é falsa

### Requirement: Chave privada nunca exposta
O sistema MUST NOT incluir a chave privada em logs, `repr`, telemetria, mensagens de erro ou
registros publicados; `export-public` SHALL exportar só a chave pública.

#### Scenario: Busca nos logs
- **GIVEN** uma sessão com a federação ligada e log em nível `DEBUG`
- **WHEN** os logs e a telemetria são varridos pelos bytes da chave privada (em PEM e em base64)
- **THEN** nenhuma ocorrência é encontrada

### Requirement: Rotação e revogação assinadas
O sistema SHALL produzir um registro `rotacao_chave` assinado pela chave antiga e pela nova, e
um registro `revogacao_chave` assinado pela chave revogada, com a data a partir da qual a
chave deixa de valer.

#### Scenario: Rotação
- **WHEN** `identity rotate` roda
- **THEN** o registro `rotacao_chave` verifica com as duas chaves públicas
- **AND** o arquivo de chave passa a conter a chave nova

#### Scenario: Revogação
- **WHEN** `identity revoke --desde 2027-01-01` roda
- **THEN** o registro `revogacao_chave` é assinado pela chave revogada e contém a data
