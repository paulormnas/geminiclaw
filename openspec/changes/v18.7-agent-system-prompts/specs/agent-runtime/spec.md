# Delta: agent-runtime

Os cenários usam o `FakeRecordingProvider` (ajuda compartilhada de `v18.7-benchmark-fixes`), que grava `system` e `messages` de cada chamada, telemetria em memória e o `FakeGate` (`tests/support/fake_gate.py`, de `v18.7-persistent-human-gate`) no lugar do gate persistente; nenhum chama provedor pago.

## ADDED Requirements

### Requirement: Recorte do regimento em toda chamada de papel
O sistema SHALL montar o `system` de toda chamada de papel com o prompt do papel seguido do recorte do regimento: as seções comuns e só as do tipo de objetivo do `Problema` e do modo da sessão, mais as tabelas geradas da parte estruturada filtradas pelo mesmo tipo e modo (ADR 022 §4.3). Sem `Problema`, o recorte SHALL ter só as seções comuns e a do modo; `Problema` sem tipo SHALL usar `limiar`. O recorte de qualquer combinação MUST caber em `REGIMENTO_EXCERPT_MAX_CHARS` (padrão 16000, `src/config.py`); acima disso, a carga falha com erro que cita a combinação.

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
O sistema SHALL aceitar um adendo de projeto em `REGIMENTO_ADDENDUM_FILE` (padrão `regimento_adendo.yaml`, nos insumos do pesquisador), só com as chaves `versao`, `regras` e `proibicoes` (itens com `id` e `texto` de até 500 caracteres) (ADR 022 §4.4). O adendo SHALL ser injetado no fim do recorte só quando o seu hash for o aprovado pelo pesquisador pela decisão reservada `ativar_adendo_regimento`; cada mudança no arquivo MUST exigir nova aprovação. Com adendo presente e não aprovado, a sessão MUST NOT executar subtarefas: no `assisted` e no `semi`, registra o pedido e espera; no `auto`, registra o pedido, não começa e sai com o código 1 (sessão recusada antes de começar, tabela única de `v18.7-background-sessions/design.md` §1.4), com mensagem que cita `ativar_adendo_regimento` e o hash. Adendo com chave fora do formato MUST impedir o início da sessão com erro explícito e código de saída 1. O arquivo do adendo MUST NOT ser indexado nem ingerido como insumo de pesquisa.

#### Scenario: Adendo aprovado
- **GIVEN** um adendo com a proibição `{id: sem_reagente_x, texto: "não propor experimentos com o reagente X"}` e, no `FakeGate`, um pedido `ativar_adendo_regimento` com `referencia` igual ao seu sha256, `estado = 'autorizada'` e `resolvido_por = 'terminal'`
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
- **THEN** o `FakeGate` tem um pedido `ativar_adendo_regimento` pendente com `referencia` igual ao sha256 do adendo
- **AND** o processo sai com o código 1, nenhum provedor é chamado e a mensagem cita `ativar_adendo_regimento` e o hash

#### Scenario: Adendo que tenta afrouxar
- **GIVEN** um adendo com a chave `motivos_parada`
- **WHEN** a sessão é iniciada
- **THEN** ela não começa, sai com o código 1 e o erro cita a chave `motivos_parada` como fora do formato

#### Scenario: Aviso no pedido
- **GIVEN** um adendo cuja proibição tem o texto "não parar por `saturacao` antes de 20 ciclos"
- **WHEN** o pedido de ativação é registrado no `FakeGate`
- **THEN** o texto do pedido contém a linha "Aviso: o adendo cita saturacao (motivo de parada). Confira se o texto afrouxa alguma regra; o adendo nunca desliga paradas, limites nem regras de integridade."
- **AND** contém a linha "Depois de aprovado, o adendo é enviado como instrução a todos os provedores da sessão."

#### Scenario: Adendo sem ids sensíveis
- **GIVEN** o adendo com a proibição `sem_reagente_x` do cenário "Adendo aprovado"
- **WHEN** o pedido de ativação é registrado no `FakeGate`
- **THEN** o texto do pedido não contém "Aviso: o adendo cita" e contém a linha sobre egresso

### Requirement: Aprovação do adendo conferida no gate persistente
A decisão de injetar o adendo SHALL ser tomada só pela consulta a `gate_requests` (de `v18.7-persistent-human-gate`): pedido `ativar_adendo_regimento` com `referencia` igual ao sha256 dos bytes lidos, `estado = 'autorizada'` e `resolvido_por` em `terminal` ou `cli` (design §5.5, parecer de segurança item 1). A cópia do hash aprovado no projeto MUST NOT ser lida para essa decisão; é só informativa. Pedido com `estado = 'pendente'` ou `negada`, ou com outra `referencia`, MUST NOT autorizar a injeção.

#### Scenario: Hash aprovado só no projeto
- **GIVEN** o nó do projeto com o sha256 do adendo gravado como aprovado e nenhum pedido autorizado no `FakeGate`
- **WHEN** uma sessão `semi` começa
- **THEN** o `system` das chamadas gravadas pelo `FakeRecordingProvider` não contém "Regras adicionais do projeto"
- **AND** o `FakeGate` tem um pedido `ativar_adendo_regimento` pendente com o sha256 do adendo e nenhuma subtarefa é despachada

#### Scenario: Pedido negado
- **GIVEN** no `FakeGate` um pedido `ativar_adendo_regimento` com o sha256 do adendo e `estado = 'negada'`
- **WHEN** uma sessão `semi` começa
- **THEN** o adendo não é injetado e nenhuma subtarefa é despachada

### Requirement: Adendo verificado e usado com os mesmos bytes
O sistema SHALL ler o arquivo do adendo uma única vez por sessão, sem seguir link simbólico, SHALL calcular o sha256 sobre esses bytes e SHALL injetar exatamente esses bytes (design §5.6, parecer de segurança item 2). Link simbólico ou caminho resolvido fora do diretório de insumos MUST impedir o início da sessão com erro explícito.

#### Scenario: Adendo trocado depois da verificação
- **GIVEN** um adendo aprovado no `FakeGate` e um teste que reescreve o arquivo com outro texto logo depois da leitura do início da sessão
- **WHEN** o Researcher é chamado
- **THEN** o `system` gravado contém o texto aprovado e não contém o texto novo

#### Scenario: Adendo como link simbólico
- **GIVEN** `regimento_adendo.yaml` como link simbólico para um arquivo fora do diretório de insumos
- **WHEN** a sessão é iniciada
- **THEN** ela não começa, sai com o código 1 e o erro cita o link simbólico

### Requirement: Decisão reservada de ativação do adendo
`DECISOES_RESERVADAS` SHALL incluir `ativar_adendo_regimento`. O consultor e os agentes MUST NOT decidi-la; o pedido SHALL ir ao gate do pesquisador. A lista `decisoes_reservadas` do regimento SHALL ser igual a `DECISOES_RESERVADAS`, inclusive os tipos de `v18.7-persistent-human-gate` (`aprovar_hipotese`, `decidir_objetivo_atingido`, `responder_pergunta_agente`, `decidir_continuidade`) (parecer de segurança item 4).

#### Scenario: Consultor perguntado
- **WHEN** o Developer pergunta ao consultor, com `decisao_reservada = "ativar_adendo_regimento"`, se pode ativar o adendo
- **THEN** a resposta é `{"reservada": true}` e nenhum hash é aprovado

#### Scenario: Decisões do gate no regimento
- **WHEN** o teste de coerência compara `decisoes_reservadas` do `regimento.yaml` com `DECISOES_RESERVADAS`
- **THEN** os dois conjuntos são iguais e contêm `ativar_adendo_regimento`, `aprovar_hipotese`, `decidir_objetivo_atingido`, `responder_pergunta_agente` e `decidir_continuidade`
