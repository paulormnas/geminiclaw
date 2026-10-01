# Delta: federation-transport

## ADDED Requirements

### Requirement: Transporte atrás de interface
O sistema SHALL publicar e receber registros federados somente pela interface
`FederationTransport`, que entrega envelopes de registro, e SHALL validar esquema e assinatura
fora do transporte (ADR 013 §1).

#### Scenario: Troca de transporte
- **GIVEN** um transporte falso em memória que implementa a interface
- **WHEN** a sincronização roda com ele
- **THEN** os registros recebidos passam pela mesma validação que os do transporte real

### Requirement: Somente conexões de saída com TLS
O nó SHALL conectar-se aos relays apenas por `wss://` (exceto `ws://localhost` em testes) e MUST
NOT abrir porta de entrada para a federação.

#### Scenario: Relay sem TLS
- **GIVEN** `FEDERATION_RELAYS=ws://relay.exemplo.org`
- **WHEN** a sincronização inicia
- **THEN** o relay é recusado com mensagem que pede `wss://`

#### Scenario: Nenhuma porta aberta
- **WHEN** `federation sync --loop` está rodando
- **THEN** o processo não tem nenhum socket em estado de escuta

### Requirement: Entrada plug-and-play com lista assinada
O sistema SHALL obter os relays iniciais de `bootstrap_relays.json` somente se a assinatura da
chave de partida do projeto for válida, SHALL acrescentar `FEDERATION_RELAYS`, e SHALL publicar
o `perfil_no` na primeira sincronização (ADR 013 §1).

#### Scenario: Primeira sincronização
- **GIVEN** a federação ligada, sem configuração além de `FEDERATION_ENABLED=true`
- **WHEN** `federation sync` roda contra relays falsos da lista de partida de teste
- **THEN** o `perfil_no` do nó é publicado e o cursor de cada relay é gravado

#### Scenario: Lista adulterada
- **GIVEN** `bootstrap_relays.json` com um relay a mais e a assinatura original
- **WHEN** a lista é carregada
- **THEN** a lista é recusada e só `FEDERATION_RELAYS` é usado, com `WARNING`

### Requirement: Sincronização incremental e deduplicada
O sistema SHALL buscar registros de cada relay a partir do cursor salvo menos a sobreposição,
SHALL descartar `cid` já conhecidos antes de processar, e SHALL respeitar
`FEDERATION_FETCH_MAX_PER_RELAY`, `FEDERATION_INBOX_MAX_MB` e
`FEDERATION_MAX_RECORDS_PER_AUTHOR_DAY`.

#### Scenario: Mesmo registro em dois relays
- **GIVEN** o mesmo registro disponível em dois relays
- **WHEN** a sincronização roda
- **THEN** existe uma única linha com aquele `cid` em `federation_records`

#### Scenario: Autor inundando a rede
- **GIVEN** `FEDERATION_MAX_RECORDS_PER_AUTHOR_DAY=100` e 150 registros de um autor no dia
- **WHEN** a sincronização roda
- **THEN** 100 registros são aceitos para validação e 50 são descartados e contados no evento `federation_sync`

#### Scenario: Caixa de entrada cheia
- **GIVEN** a caixa de entrada no limite de `FEDERATION_INBOX_MAX_MB`
- **WHEN** a sincronização roda
- **THEN** nenhuma busca nova é feita e um `WARNING` informa o limite

### Requirement: Publicação em vários relays
O sistema SHALL enviar registros `aprovado` a todos os relays saudáveis, SHALL marcar o
registro como `enviado` com ao menos `FEDERATION_PUBLISH_MIN_ACKS` confirmações, e SHALL
reenviar aos relays que falharam com recuo exponencial.

#### Scenario: Um relay fora do ar
- **GIVEN** três relays, um deles fora do ar, e `FEDERATION_PUBLISH_MIN_ACKS=2`
- **WHEN** um registro aprovado é publicado
- **THEN** o estado passa a `enviado` e o relay fora do ar fica com reenvio agendado

### Requirement: Sincronização fora das sessões de pesquisa
O sistema SHALL executar a sincronização somente pelo comando `federation sync` e MUST NOT
sincronizar durante uma sessão de pesquisa.

#### Scenario: Sessão em andamento
- **GIVEN** uma sessão de pesquisa ativa
- **WHEN** `federation sync --loop` chega ao próximo intervalo
- **THEN** a rodada é adiada e registrada como `adiada_sessao_ativa`
