# Delta: agent-runtime

Os cenários usam um provedor falso que grava `system` e `messages` de cada chamada, telemetria em memória e um gate de teste; nenhum chama provedor pago.

## ADDED Requirements

### Requirement: Recorte do regimento em toda chamada de papel
O sistema SHALL montar o `system` de toda chamada de papel com o prompt do papel seguido do recorte do regimento: as seções comuns e só as do tipo de objetivo do `Problema` e do modo da sessão, mais as tabelas geradas da parte estruturada filtradas pelo mesmo tipo e modo (ADR 022 §4.3). Sem `Problema`, o recorte SHALL ter só as seções comuns e a do modo; `Problema` sem tipo SHALL usar `limiar`. O recorte de qualquer combinação MUST caber em `REGIMENTO_EXCERPT_MAX_CHARS` (padrão 8000, `src/config.py`); acima disso, a carga falha com erro que cita a combinação.

#### Scenario: Discriminação no auto
- **GIVEN** uma sessão `auto` cujo `Problema` tem objetivo do tipo `discriminacao`
- **WHEN** o Developer, o Validator do plano e o Researcher são chamados
- **THEN** o `system` de cada chamada contém o cabeçalho "REGIMENTO DA PESQUISA (versão 1; objetivo discriminacao; modo auto)" e o texto da seção `objetivo_discriminacao`
- **AND** não contém o texto das seções `objetivo_fronteira`, `objetivo_limiar`, `modo_assisted` nem `modo_semi`

#### Scenario: Sem projeto
- **GIVEN** uma sessão `assisted` sem projeto
- **WHEN** o Researcher é chamado
- **THEN** o recorte tem as seções comuns e `modo_assisted`, e nenhuma seção `objetivo_*`

#### Scenario: Recorte grande demais
- **GIVEN** `REGIMENTO_EXCERPT_MAX_CHARS=100`
- **WHEN** o regimento é carregado
- **THEN** a carga falha com erro que cita o tipo e o modo da primeira combinação que excede

### Requirement: Versão do regimento registrada por sessão
O sistema SHALL carregar o regimento e o adendo uma vez por sessão e SHALL registrar no evento `regimento_sessao` e no payload da sessão (`regimento`) a versão, o `regimento_sha256`, o `adendo_sha256` (vazio sem adendo) e, para cada recorte calculado, o `recorte_sha256` com tipo de objetivo e modo (ADR 022 §4.4). `AgentContext` SHALL levar `regimento_sha256` e `recorte_sha256`. Na retomada com regimento diferente do registrado, o sistema SHALL usar o do disco e gravar `regimento_alterado` com os dois hashes.

#### Scenario: Início da sessão
- **WHEN** uma sessão começa com o regimento v1 e sem adendo
- **THEN** a telemetria tem um evento `regimento_sessao` com `versao = 1`, `regimento_sha256` igual ao `sha256` do regimento carregado e `adendo_sha256` vazio
- **AND** o `AgentContext` de uma tentativa do Developer tem o mesmo `regimento_sha256`

#### Scenario: Arquivo alterado no meio da sessão
- **GIVEN** uma sessão em andamento
- **WHEN** `regimento.md` é alterado em disco e uma nova chamada de papel é feita
- **THEN** o `system` da chamada usa o recorte carregado no início da sessão

#### Scenario: Retomada com regimento novo
- **GIVEN** um checkpoint com `regimento_sha256` diferente do regimento em disco
- **WHEN** a sessão é retomada
- **THEN** o evento `regimento_alterado` registra os dois hashes e as chamadas usam o regimento do disco

### Requirement: Ferramenta de leitura do regimento
O sistema SHALL oferecer a Researcher, Developer e Curator a ferramenta `ler_regimento(secao)`, que lê só o regimento carregado na sessão: sem argumento, a lista de seções; com um id válido, o texto da seção e as tabelas geradas que ela cita; com id desconhecido, a lista de ids válidos. A ferramenta MUST NOT aceitar caminho de arquivo nem ler o adendo.

#### Scenario: Seção fora do recorte
- **GIVEN** uma sessão com objetivo `limiar`
- **WHEN** o Developer chama `ler_regimento("objetivo_discriminacao")`
- **THEN** a resposta contém o texto da seção `objetivo_discriminacao` do regimento da sessão

#### Scenario: Caminho no argumento
- **WHEN** a ferramenta recebe `../../.env`
- **THEN** a resposta é a lista de ids válidos e nenhum arquivo é aberto

### Requirement: Adendo de projeto só restringe e passa pelo gate
O sistema SHALL aceitar um adendo de projeto em `REGIMENTO_ADDENDUM_FILE` (padrão `regimento_adendo.yaml`, nos insumos do pesquisador), só com as chaves `versao`, `regras` e `proibicoes` (itens com `id` e `texto` de até 500 caracteres) (ADR 022 §4.4). O adendo SHALL ser injetado no fim do recorte só quando o seu hash for o aprovado pelo pesquisador pela decisão reservada `ativar_adendo_regimento`; cada mudança no arquivo MUST exigir nova aprovação. Com adendo presente e não aprovado, a sessão MUST NOT executar subtarefas: no `assisted` e no `semi`, registra o pedido e espera; no `auto`, não começa e informa como aprovar. Adendo com chave fora do formato MUST impedir o início da sessão com erro explícito. O arquivo do adendo MUST NOT ser indexado nem ingerido como insumo de pesquisa.

#### Scenario: Adendo aprovado
- **GIVEN** um adendo com a proibição `{id: sem_reagente_x, texto: "não propor experimentos com o reagente X"}` e o seu hash aprovado pelo gate de teste
- **WHEN** o Researcher é chamado
- **THEN** o `system` contém "Regras adicionais do projeto" e o texto da proibição
- **AND** `regimento_sessao` registra o `adendo_sha256` aprovado

#### Scenario: Adendo alterado depois da aprovação
- **GIVEN** o mesmo adendo com um caractere a mais no texto e uma sessão `semi`
- **WHEN** a sessão começa
- **THEN** o gate recebe um pedido `ativar_adendo_regimento` com o novo hash
- **AND** nenhuma subtarefa é despachada enquanto o pedido está pendente

#### Scenario: Adendo pendente no auto
- **GIVEN** um adendo não aprovado e uma sessão `auto`
- **WHEN** a sessão é iniciada
- **THEN** ela não começa e a mensagem cita `ativar_adendo_regimento`

#### Scenario: Adendo que tenta afrouxar
- **GIVEN** um adendo com a chave `motivos_parada`
- **WHEN** a sessão é iniciada
- **THEN** ela não começa e o erro cita a chave `motivos_parada` como fora do formato

#### Scenario: Aviso no pedido
- **GIVEN** um adendo cujo texto cita `saturacao`
- **WHEN** o pedido de ativação é registrado
- **THEN** o pedido contém o aviso de que o texto cita um motivo de parada

### Requirement: Decisão reservada de ativação do adendo
`DECISOES_RESERVADAS` SHALL incluir `ativar_adendo_regimento`. O consultor e os agentes MUST NOT decidi-la; o pedido SHALL ir ao gate do pesquisador.

#### Scenario: Consultor perguntado
- **WHEN** o Developer pergunta ao consultor, com `decisao_reservada = "ativar_adendo_regimento"`, se pode ativar o adendo
- **THEN** a resposta é `{"reservada": true}` e nenhum hash é aprovado
