# Delta: llm-providers

## ADDED Requirements

### Requirement: Modo de independência do julgamento
O sistema SHALL ler `LLM_JUDGE_INDEPENDENCE` (`required`, `preferred`, `off`). Sem valor, o modo
SHALL ser `required` com `LLM_DATA_POLICY=third_party_allowed` e `preferred` com
`self_hosted_only`. Valor inválido MUST impedir a inicialização (ADR 020, item 5).

#### Scenario: Padrão em política de terceiros
- **GIVEN** `LLM_DATA_POLICY=third_party_allowed` e a variável ausente
- **WHEN** a sessão resolve o mapa
- **THEN** o modo é `required` com `origem_modo = "padrao_politica"`

#### Scenario: Padrão só local
- **GIVEN** `LLM_DATA_POLICY=self_hosted_only` e a variável ausente
- **WHEN** a sessão resolve o mapa
- **THEN** o modo é `preferred`

#### Scenario: Valor inválido
- **GIVEN** `LLM_JUDGE_INDEPENDENCE=sim`
- **WHEN** a sessão inicia
- **THEN** a inicialização falha com mensagem que lista `required`, `preferred` e `off`

### Requirement: Família do Validator diferente da do Developer
Com modo `required` ou `preferred`, o roteador SHALL resolver o `validator` para um modelo de
`familia_modelo` diferente da do modelo resolvido para o `developer`, descartando os demais com o
motivo `mesma_familia_julgamento`, inclusive quando o modelo de outra família está num grupo de
preferência inferior (ADR 020, itens 1 e 4).

#### Scenario: Preferido da mesma família
- **GIVEN** `developer` resolvido para `anthropic/claude-sonnet-5-5` e a preferência do `validator`
  `[anthropic/claude-sonnet-5-5, google/gemini-3.8-flash]`, ambos disponíveis
- **WHEN** o mapa é resolvido
- **THEN** o `validator` é `google/gemini-3.8-flash`
- **AND** `anthropic/claude-sonnet-5-5` aparece em `descartados` com `mesma_familia_julgamento`

#### Scenario: Sem modelo elegível em `required`
- **GIVEN** só modelos da família `claude` disponíveis e modo `required`
- **WHEN** o mapa é resolvido
- **THEN** a sessão falha com `NoEligibleModelError`
- **AND** a sugestão cita `LLM_JUDGE_INDEPENDENCE=preferred`

#### Scenario: Sem modelo elegível em `preferred`
- **GIVEN** só modelos da família `qwen` e modo `preferred`
- **WHEN** o mapa é resolvido
- **THEN** o `validator` é o preferido do catálogo
- **AND** o registro tem `atendida = false` e o banner mostra o aviso

#### Scenario: Modo `off`
- **GIVEN** modo `off` e o mesmo modelo preferido para `developer` e `validator`
- **WHEN** o mapa é resolvido
- **THEN** os dois papéis usam o mesmo modelo, como antes desta mudança

### Requirement: Pins na regra de independência
O roteador SHALL resolver primeiro os papéis com pin, SHALL fazer os papéis julgados sem pin
descartarem as famílias dos juízes com pin e SHALL tratar dois pins em conflito pela tabela do
design §3.

#### Scenario: Só o juiz com pin
- **GIVEN** `VALIDATOR_MODEL=anthropic/claude-sonnet-5-5`, `developer` sem pin, preferência do
  `developer` `[anthropic/claude-sonnet-5-5, google/gemini-3.8-flash]`, modo `required`
- **WHEN** o mapa é resolvido
- **THEN** o `validator` é `anthropic/claude-sonnet-5-5` e o `developer` é `google/gemini-3.8-flash`

#### Scenario: Dois pins em conflito, `strict`
- **GIVEN** `VALIDATOR_MODEL` e `DEVELOPER_MODEL` da família `claude`, `LLM_ROUTING=strict`, modo `required`
- **WHEN** o mapa é resolvido
- **THEN** a sessão falha com `PinError`

#### Scenario: Dois pins em conflito, `flexible`
- **GIVEN** o mesmo caso com `LLM_ROUTING=flexible`
- **WHEN** o mapa é resolvido
- **THEN** o pin do `developer` é mantido, o pin do `validator` é ignorado com `WARNING`
- **AND** o `validator` vem da preferência, de outra família

### Requirement: Conferência no despacho
O sistema SHALL conferir, a cada dica de plano aceita, despacho para `base` ou `reviewer` e troca
para o modelo de reserva no 429, que nenhum juiz (`validator`, `reviewer`) e nenhum julgado
(`developer`, `base`) em uso compartilham família, e SHALL registrar o evento
`independencia_julgamento` com a decisão.

#### Scenario: Dica do Developer na família do juiz
- **GIVEN** `validator` da família `claude`, modo `required` e uma subtarefa do `developer` com
  `preferred_model: anthropic/claude-sonnet-5-5`
- **WHEN** a dica é avaliada
- **THEN** a dica é rejeitada e a subtarefa usa o modelo resolvido do `developer`
- **AND** o evento registra `decisao = "rejeitado"` e `motivo = "mesma_familia_julgamento"`

#### Scenario: Dica do reviewer na família do Developer
- **GIVEN** `developer` da família `gemini` e uma subtarefa do `reviewer` com dica `google/gemini-3.8-flash`
- **WHEN** a dica é avaliada
- **THEN** a dica é rejeitada

#### Scenario: Modo `off` não confere a reserva
- **GIVEN** modo `off`, `developer` e `validator` da família `gemini` e uma reserva `gemini`
- **WHEN** ocorre 429 no `developer`
- **THEN** a reserva é usada

#### Scenario: `base` em conflito com alternativa
- **GIVEN** `validator` da família `gemini`, preferência do `base` `[google/gemini-3.8-flash, anthropic/claude-haiku-5-5]`, modo `required`
- **WHEN** uma subtarefa é despachada para `base`
- **THEN** ela roda com `anthropic/claude-haiku-5-5` e o evento registra `decisao = "substituido"`

#### Scenario: `base` em conflito sem alternativa
- **GIVEN** o mesmo caso com só `google/gemini-3.8-flash` disponível para `base`
- **WHEN** a subtarefa é despachada
- **THEN** só essa subtarefa falha com `mesma_familia_julgamento` e a sessão continua

#### Scenario: Reserva do 429 na família do juiz em `required`
- **GIVEN** `validator` da família `gemini`, `developer` de outra família e uma reserva do `developer` da família `gemini`
- **WHEN** ocorre 429 no `developer`
- **THEN** a reserva não é usada e o 429 segue o cooldown e as retentativas

### Requirement: Registro da independência
O payload da sessão SHALL conter `independencia_julgamento` com modo, origem do modo, modelo, família
e origem da família de `validator` e `developer`, e `atendida`. O banner e o relatório final SHALL
mostrar a linha de julgamento.

#### Scenario: Registro na inicialização
- **WHEN** a sessão inicia com `validator` `gemini` e `developer` `claude`
- **THEN** o payload tem `independencia_julgamento.atendida = true` e as duas famílias
- **AND** o banner contém "gemini (validator)" e "claude (developer)"

### Requirement: Conferência na retomada
Ao retomar uma sessão, o sistema SHALL carregar as famílias julgadas registradas na sessão original
e SHALL aplicar a conferência e o modo ao juiz resolvido na retomada antes de reverificar
afirmações pendentes.

#### Scenario: Catálogo mudou entre as execuções
- **GIVEN** uma sessão original com `developer` `claude` e uma retomada em que o `validator` resolve
  para `claude`, modo `required`
- **WHEN** a sessão é retomada
- **THEN** a retomada falha com `NoEligibleModelError` antes de reverificar afirmações

### Requirement: Preferência dos juízes no catálogo
O catálogo versionado SHALL listar, na preferência de `validator` e `reviewer`, ao menos um modelo de
nuvem de cada família do catálogo antes de qualquer modelo local.

#### Scenario: Teste do catálogo
- **WHEN** o catálogo versionado é carregado no teste
- **THEN** as preferências de `validator` e `reviewer` contêm `claude`, `gemini` e `gpt` antes de `qwen`

## MODIFIED Requirements

### Requirement: Rótulo de papel da revisão de subtarefa
A chamada LLM da revisão de subtarefa SHALL ser registrada com o papel `validator` e
`funcao = "revisao_subtarefa"`.
(Antes: registrada como `reviewer`, embora usasse o modelo do `validator`.)

#### Scenario: Telemetria da revisão
- **WHEN** `review_result` chama o modelo
- **THEN** o registro da chamada tem papel `validator` e `funcao = "revisao_subtarefa"`
