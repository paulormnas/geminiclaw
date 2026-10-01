# Delta: equipment-control

## ADDED Requirements

### Requirement: Limites de segurança verificados antes da escrita
Todo driver de equipamento SHALL verificar `safety_limits` do canal antes de qualquer
operação de escrita e SHALL levantar `SafetyLimitViolation`, registrando em log, sem tocar no
hardware quando o valor ou a frequência violarem os limites (Spec G7, Tarefa 1).

#### Scenario: Valor fora da faixa
- **GIVEN** o canal `nivel` do `FakeDriver` com `safety_limits` `{min: 0, max: 1}`
- **WHEN** `write("nivel", 5)` é chamado
- **THEN** `SafetyLimitViolation` é levantada e o valor do canal não muda

#### Scenario: Frequência excedida
- **GIVEN** `taxa_max_por_min: 2` e duas escritas no último minuto
- **WHEN** uma terceira escrita é pedida
- **THEN** `SafetyLimitViolation` é levantada

### Requirement: Somente leitura por padrão
O sistema SHALL oferecer apenas leitura para todo dispositivo autorizado e SHALL liberar
escrita somente nos canais declarados em `canais_escrita`, com `safety_limits`, e liberados
pelo pesquisador no início da sessão (ADR 019 §10).

#### Scenario: Nenhum canal liberado
- **GIVEN** o pesquisador autorizou o acesso aos dispositivos, mas não liberou canais de escrita
- **WHEN** o agente chama `equipment_write("led_status", "nivel", 1, "teste")`
- **THEN** a chamada falha com `PermissionDeniedError` e nenhum pedido de confirmação é exibido

#### Scenario: Canal de escrita sem limites
- **GIVEN** um `equipment.yaml` com canal em `canais_escrita` e sem `safety_limits`
- **WHEN** a configuração é carregada
- **THEN** a carga falha citando o dispositivo e o canal

#### Scenario: Execução não interativa
- **GIVEN** a autorização inicial sem resposta do pesquisador
- **WHEN** a sessão começa
- **THEN** nenhum dispositivo fica autorizado e as ferramentas de equipamento não são oferecidas

### Requirement: Confirmação humana para toda escrita em qualquer modo
O sistema SHALL pedir ao pesquisador a confirmação de cada comando de escrita que passou pela
lista e pelos limites, em `assisted`, `semi` e `auto`, SHALL negar a escrita quando a confirmação
for recusada ou não vier em `EQUIPMENT_WRITE_CONFIRM_TIMEOUT_SECONDS`, e MUST NOT aceitar a
confirmação de um agente, inclusive do Researcher consultor (ADR 019 §10).

#### Scenario: Modo auto confirmado
- **GIVEN** uma sessão `auto`, canal `nivel` liberado e o pesquisador responde "s"
- **WHEN** o agente pede `equipment_write("led_status", "nivel", 1, "acender para teste")`
- **THEN** a confirmação exibe dispositivo, canal, valor atual, valor novo e a justificativa
- **AND** a escrita é executada depois da resposta

#### Scenario: Prazo expirado
- **GIVEN** `EQUIPMENT_WRITE_CONFIRM_TIMEOUT_SECONDS=1` e nenhuma resposta
- **WHEN** a escrita é pedida
- **THEN** a chamada falha com `ConfirmationDenied` e o hardware não é tocado

#### Scenario: Consultor não confirma
- **GIVEN** uma sessão `auto` com o Researcher consultor habilitado
- **WHEN** uma escrita é pedida
- **THEN** o consultor não é chamado para a confirmação

### Requirement: Escrita registrada antes de executar
O sistema SHALL registrar no log de equipamentos e na telemetria a intenção de escrita, a
decisão e o resultado, com a intenção gravada antes de o comando chegar ao driver (Spec G7,
Tarefa 2).

#### Scenario: Ordem do registro
- **WHEN** uma escrita confirmada é executada com o `FakeDriver`
- **THEN** o evento `equipment_write_requested` tem carimbo de tempo anterior à chamada do driver
- **AND** existem os eventos `equipment_write_decision` e `equipment_write_done`

### Requirement: Ferramentas tipadas no host, sem código gerado
O sistema SHALL expor o acesso a equipamentos somente pelas ferramentas `equipment_list`,
`equipment_read` e `equipment_write` executadas no processo do host, e MUST NOT dar ao sandbox
de código acesso a dispositivos de hardware (ADR 014 §3).

#### Scenario: Sandbox sem dispositivos
- **WHEN** um container do sandbox é criado com as ferramentas de equipamento ligadas
- **THEN** nenhum dispositivo `/dev/gpiochip*`, `/dev/i2c-*` ou `/dev/tty*` é repassado ao container

#### Scenario: Sem IPC
- **WHEN** o Developer chama `equipment_read`
- **THEN** a chamada é atendida no mesmo processo, sem socket

### Requirement: Leituras como dado de pesquisa
O sistema SHALL gravar cada leitura em arquivo `.jsonl` da subtarefa com dispositivo, canal,
valor, unidade e carimbo de tempo, SHALL registrar o arquivo como artefato de execução, e
SHALL devolver os valores ao agente com origem `dado_de_pesquisa`, de modo que modelos sem
`aceita_dados_brutos` recebam só metadados (ADR 019 §2, §3).

#### Scenario: Modelo sem dados brutos
- **GIVEN** o Developer resolvido para um modelo `fora_do_no` sem `aceita_dados_brutos`
- **WHEN** ele chama `equipment_read("sensor_temp_1", "temperatura", n=10)`
- **THEN** o arquivo `.jsonl` tem 10 linhas com os valores
- **AND** o texto que chega ao modelo traz o número de amostras, a unidade e o caminho do arquivo, sem os valores

#### Scenario: Modelo no nó
- **GIVEN** o Developer num modelo `no_no`
- **WHEN** a mesma leitura é feita
- **THEN** os valores chegam ao modelo

### Requirement: Estado seguro no fechamento
O sistema SHALL aplicar o `estado_seguro` dos dispositivos com escrita liberada e desconectar
todos os dispositivos ao fechar a sessão por fim normal, limite de uso, interrupção ou exceção,
e SHALL relatar falhas ao aplicar o estado seguro.

#### Scenario: Parada por limite de tempo
- **GIVEN** o LED em nível 1 e a sessão parando por `limite_tempo`
- **WHEN** a sessão fecha
- **THEN** o canal `nivel` fica em 0 e o dispositivo é desconectado

#### Scenario: Falha ao aplicar
- **GIVEN** o `FakeDriver` configurado para falhar na escrita do estado seguro
- **WHEN** a sessão fecha
- **THEN** um `ERROR` é registrado e o relatório final cita o dispositivo

### Requirement: Instrumentos no grafo e falhas de infraestrutura
O sistema SHALL registrar cada dispositivo usado numa subtarefa como
`Abordagem(tipo="instrumento")` ligada ao `Experimento` por `APLICOU`, e SHALL classificar
como `infraestrutura` a falha de subtarefa causada por erro de comunicação ou de driver
(ADR 015 §4, §9.3).

#### Scenario: Leitura numa subtarefa
- **WHEN** uma subtarefa usa `equipment_read` em `sensor_temp_1` e termina
- **THEN** existe `Experimento-APLICOU->Abordagem` com `tipo="instrumento"` para o dispositivo

#### Scenario: Sensor desconectado
- **GIVEN** o `FakeDriver` lança erro de comunicação
- **WHEN** a subtarefa falha por isso
- **THEN** o `Experimento` tem `causa_falha="infraestrutura"` e o veredito da hipótese não muda

### Requirement: Autorização não herdada
O sistema SHALL pedir a autorização de dispositivos e de canais de escrita em toda sessão,
inclusive nas que continuam uma sessão anterior, e SHALL limitar as escritas a
`EQUIPMENT_MAX_WRITES_PER_SESSION`.

#### Scenario: Sessão de continuação
- **GIVEN** uma sessão anterior com escrita liberada no LED
- **WHEN** uma sessão que a continua inicia
- **THEN** a autorização é pedida de novo e nada está liberado até a resposta

#### Scenario: Teto de escritas
- **GIVEN** `EQUIPMENT_MAX_WRITES_PER_SESSION=1` e uma escrita já feita
- **WHEN** outra escrita é pedida
- **THEN** a chamada falha com `PermissionDeniedError` sem pedir confirmação
