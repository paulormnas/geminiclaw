# Delta: agent-prompts

## ADDED Requirements

### Requirement: Memória de falhas no prompt do Developer
Antes de cada subtarefa de código, o sistema SHALL incluir no prompt do Developer o bloco `memoria_de_falhas`, montado de forma determinística a partir dos `Experimento` do projeto com causa `abordagem` ou `infraestrutura`. O bloco SHALL separar o escopo `ambiente` do escopo da abordagem, SHALL usar o modelo de texto do design §3 e SHALL respeitar `FAILURE_MEMORY_MAX_CHARS`. Com `FAILURE_MEMORY_MAX_CHARS=0`, o bloco SHALL ser omitido.

#### Scenario: Falha de pacote repetida
- **GIVEN** dois experimentos do projeto com `assinatura_falha = instalacao_pacotes`
- **WHEN** a próxima subtarefa de código é enviada ao Developer
- **THEN** o prompt contém `NÃO: instalacao_pacotes em ambiente (2 vezes)`

#### Scenario: Correção conhecida
- **GIVEN** uma falha `oom` na abordagem `svm_rbf` seguida de um experimento da mesma abordagem, com métrica válida e `config_normalizada` com `amostra_max=5000`
- **WHEN** a memória é montada
- **THEN** o item de `oom` tem `USE:` com a diferença `amostra_max=5000`

#### Scenario: Critério não atendido não entra
- **GIVEN** apenas experimentos com `criterio_nao_atendido`
- **WHEN** a memória é montada
- **THEN** o bloco está vazio e é omitido

#### Scenario: Desligada
- **GIVEN** `FAILURE_MEMORY_MAX_CHARS=0`
- **WHEN** a subtarefa é enviada
- **THEN** o prompt não contém `memoria_de_falhas` e o evento `memoria_falhas_aplicada` tem `itens = 0`
