# Delta: llm-providers

## ADDED Requirements

### Requirement: Localidade e aceitação de dados brutos declaradas no catálogo
O sistema SHALL aceitar em cada entrada do catálogo os campos `localidade` (`no_no` ou
`fora_do_no`, padrão `fora_do_no`) e `aceita_dados_brutos` (padrão `false`), e SHALL tratar
toda entrada `no_no` como `aceita_dados_brutos: true`. O sistema MUST NOT inferir esses valores
a partir da URL do endpoint.

#### Scenario: Padrões seguros
- **GIVEN** uma entrada `google/gemini-2.5-pro` sem `localidade` nem `aceita_dados_brutos`
- **WHEN** o catálogo é carregado
- **THEN** a entrada tem `localidade=fora_do_no` e `aceita_dados_brutos=false`

#### Scenario: Modelo no nó
- **GIVEN** uma entrada `ollama/qwen3:8b` com `localidade: no_no` e sem `aceita_dados_brutos`
- **WHEN** o catálogo é carregado
- **THEN** o valor efetivo de `aceita_dados_brutos` é `true`

#### Scenario: Endpoint em loopback não muda a declaração
- **GIVEN** uma entrada `openai_compatible` com `localidade: fora_do_no` e endpoint `http://127.0.0.1:8080`
- **WHEN** o catálogo é carregado
- **THEN** a localidade continua `fora_do_no`
- **AND** um `WARNING` informa que o endpoint está em loopback e pode ser túnel ou proxy

#### Scenario: Declaração no nó com endpoint remoto
- **GIVEN** uma entrada com `localidade: no_no` e endpoint `https://gpu.exemplo.org`
- **WHEN** o catálogo é carregado
- **THEN** um `WARNING` cita o `id` e o host, e a declaração é mantida

### Requirement: Coerência entre trust, localidade e dados brutos
O sistema SHALL recusar na inicialização, com mensagem que cita o arquivo e o `id`, qualquer
entrada com `aceita_dados_brutos: true` e `trust: third_party`, com `localidade: no_no` e
`trust: third_party`, ou com `localidade: no_no` e `aceita_dados_brutos: false` explícito.

#### Scenario: Terceiro declarando dados brutos
- **WHEN** o catálogo contém uma entrada `trust: third_party` com `aceita_dados_brutos: true`
- **THEN** a inicialização para com erro que cita a entrada

#### Scenario: Catálogo local que aceita dados brutos
- **GIVEN** um `catalog.local.yaml` que acrescenta uma entrada `self_hosted` com `aceita_dados_brutos: true`
- **WHEN** o catálogo é carregado
- **THEN** a entrada é aceita e um `WARNING` específico cita seu `id`

### Requirement: Família do modelo
O sistema SHALL exigir em cada entrada do catálogo o campo `familia_modelo`, texto minúsculo
não vazio, usado apenas para orientar preferência.

#### Scenario: Família ausente
- **WHEN** uma entrada do catálogo não declara `familia_modelo`
- **THEN** a inicialização para com erro que cita a entrada

### Requirement: Desempate por família no Validator
O sistema SHALL resolver o Validator depois dos papéis que escrevem afirmações verificadas
(Researcher, Developer, Summarizer e Curator) e, entre elegíveis da **mesma posição** de
preferência, SHALL preferir modelo de `familia_modelo` diferente das famílias desses papéis. Um modelo de posição inferior MUST NOT substituir o da
primeira posição com elegível. A escolha SHALL ser registrada no perfil de alocação.

#### Scenario: Empate resolvido por família
- **GIVEN** Researcher, Developer, Summarizer e Curator resolvidos para modelos da família `qwen`
- **AND** a primeira posição de preferência do Validator com `ollama/qwen3:8b` e `ollama/gemma3:12b`, ambos elegíveis
- **WHEN** o roteador resolve o Validator
- **THEN** o escolhido é `ollama/gemma3:12b`
- **AND** `allocation_profile.papeis.validator.desempate.aplicado` é `true`

#### Scenario: Família diferente em posição inferior
- **GIVEN** a primeira posição do Validator só com `ollama/qwen3:8b` (elegível) e a segunda com `ollama/gemma3:12b`
- **AND** o autor da família `qwen`
- **WHEN** o roteador resolve o Validator
- **THEN** o escolhido é `ollama/qwen3:8b`

#### Scenario: Pin desliga o desempate
- **WHEN** `VALIDATOR_MODEL` fixa um modelo elegível
- **THEN** o modelo fixado é usado e `desempate.aplicado` é `false`

### Requirement: Perfil de alocação da sessão
O sistema SHALL gravar em `payload["allocation_profile"]`, antes do primeiro envio a um
modelo, o `provedor/modelo`, `trust`, `localidade`, `aceita_dados_brutos` efetivo,
`familia_modelo` e `versao_efetiva` de cada papel, além da versão e do hash do catálogo, e
SHALL exibi-lo no banner da sessão.

#### Scenario: Perfil no payload e no banner
- **WHEN** uma sessão inicia com Researcher em `google/gemini-2.5-pro` e Validator em `ollama/qwen3:8b`
- **THEN** o payload contém o perfil com os dois papéis e seus campos
- **AND** o banner mostra uma linha por papel com `trust`, `localidade` e aceitação de dados brutos

### Requirement: Versão efetiva registrada por chamada
O sistema SHALL registrar em cada chamada de LLM a `versao_efetiva`, obtida de
`response.model_version` (Google), de `model` e `system_fingerprint` da resposta (OpenAI
compatível) ou do `digest` de `/api/tags` (Ollama), e SHALL registrar o valor literal
`desconhecida` quando o provedor não informar.

#### Scenario: Google informa a versão
- **GIVEN** uma resposta simulada do Google com `model_version="gemini-2.5-pro-002"`
- **WHEN** a chamada é registrada
- **THEN** `token_usage.versao_efetiva` é `gemini-2.5-pro-002`

#### Scenario: Servidor compatível sem campo de modelo
- **GIVEN** uma resposta `openai_compatible` sem `model` nem `system_fingerprint`
- **WHEN** a chamada é registrada
- **THEN** `versao_efetiva` é `desconhecida`

#### Scenario: Ollama pelo digest
- **GIVEN** `/api/tags` devolvendo `digest="sha256:abc…"` para `qwen3:8b` no início da sessão
- **WHEN** uma chamada a `ollama/qwen3:8b` é registrada
- **THEN** `versao_efetiva` é `sha256:abc…`

### Requirement: Mudança de versão dentro da sessão
O sistema SHALL, quando a versão efetiva de um `provedor/modelo` mudar dentro da sessão,
gravar o evento `versao_modelo_alterada`, acrescentá-lo a `payload["eventos_versao_modelo"]`
e emitir `WARNING`. Com `LLM_ROUTING=strict`, versão alterada ou `desconhecida` após a primeira
chamada do papel SHALL encerrar a execução no próximo ponto de verificação de limites, com
fechamento e `motivo_parada="versao_modelo"`, mantendo a sessão retomável.

#### Scenario: Troca de versão em modo flexível
- **GIVEN** `LLM_ROUTING` diferente de `strict`
- **WHEN** duas chamadas ao mesmo modelo retornam versões diferentes
- **THEN** o evento é gravado e a sessão continua

#### Scenario: Troca de versão em modo strict
- **GIVEN** `LLM_ROUTING=strict`
- **WHEN** a versão de um modelo muda durante a sessão
- **THEN** nenhuma nova subtarefa é despachada
- **AND** o fechamento é executado com `motivo_parada="versao_modelo"`

#### Scenario: Versão desconhecida em modo strict
- **GIVEN** `LLM_ROUTING=strict` e um servidor compatível que não informa versão
- **WHEN** a primeira chamada desse papel termina
- **THEN** a sessão entra em fechamento no próximo ponto de verificação com `motivo_parada="versao_modelo"`
