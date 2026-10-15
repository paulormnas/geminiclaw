# Delta: llm-providers

## MODIFIED Requirements

### Requirement: Recusa e falhas explícitas
_Origem: [`v16-anthropic-provider`](../../../archive/v16-anthropic-provider/proposal.md); modificado por `v18.7-benchmark-fixes` (achado 4 da bateria V18.6)._
O provedor SHALL levantar `ProviderRefusalError` com a categoria quando a resposta for uma recusa, SHALL levantar `ProviderQuotaExhausted` sem retentativa quando o erro for classificado como esgotamento de cota ou gasto, e SHALL retentar apenas erros de conexão, 429 não classificado como cota e 5xx, emitindo `connection_retry` a cada retentativa.

#### Scenario: Recusa por classificador de segurança
- **WHEN** a resposta tem `stop_reason == "refusal"` com categoria `bio`
- **THEN** `ProviderRefusalError` é levantado informando o modelo e a categoria

#### Scenario: Erro de cliente
- **WHEN** a API retorna 400 sem marcador de cota
- **THEN** o erro é propagado sem retentativa

#### Scenario: Saldo esgotado na Anthropic
- **GIVEN** um cliente Anthropic simulado que responde 400 com a mensagem `Your credit balance is too low to access the Anthropic API`
- **WHEN** `generate` é chamado
- **THEN** `ProviderQuotaExhausted` é levantado com `provider="anthropic"`, o modelo e `status_code=400`
- **AND** o cliente foi chamado uma única vez e nenhum `connection_retry` foi emitido

### Requirement: Mudança de versão dentro da sessão
_Origem: [`v18.5-model-catalog-locality`](../../../archive/v18.5-model-catalog-locality/proposal.md); modificado por `v18.7-benchmark-fixes` (decisão do pesquisador de 2026-10-15)._
O sistema SHALL, quando a versão efetiva de um `provedor/modelo` mudar dentro da sessão, gravar o evento `versao_modelo_alterada` (provedor, modelo, versão anterior e nova), acrescentá-lo a `payload["eventos_versao_modelo"]` e emitir `WARNING`. A política `ON_MODEL_VERSION_CHANGE` (`src/config.py`; variável de ambiente de mesmo nome; `retomar` padrão | `parar`; outro valor falha na inicialização) SHALL valer somente com `LLM_ROUTING=strict`; no modo flexível a sessão apenas registra, avisa e continua.

Com `LLM_ROUTING=strict` e `ON_MODEL_VERSION_CHANGE=retomar`, versão alterada ou `desconhecida`, ou modelo indisponível, após a primeira chamada do papel SHALL, no próximo ponto de verificação de limites, gravar um checkpoint e continuar a sessão:

- versão nova informada: a sessão continua com o mesmo modelo e a nova versão fica registrada na proveniência;
- versão `desconhecida` ou modelo indisponível: o papel passa ao próximo modelo elegível da lista `preferencia` do papel no catálogo (`src/llm/catalog.yaml`), respeitando a elegibilidade do ADR 017, a família do Validator diferente da do Developer (ADR 020) e a localidade (ADR 019), e o evento `modelo_substituido` (papel, modelo anterior, modelo novo, motivo) é gravado;
- sem modelo elegível: a sessão fecha com `motivo_parada="versao_modelo"` e checkpoint, retomável.

Com `LLM_ROUTING=strict` e `ON_MODEL_VERSION_CHANGE=parar`, versão alterada ou `desconhecida` após a primeira chamada do papel SHALL encerrar a execução no próximo ponto de verificação de limites, com fechamento e `motivo_parada="versao_modelo"`, mantendo a sessão retomável (comportamento anterior; usado pela bateria do benchmark).
(Antes: o modo `strict` sempre fechava com `versao_modelo`.)

#### Scenario: Troca de versão em modo flexível
- **GIVEN** `LLM_ROUTING` diferente de `strict`
- **WHEN** duas chamadas ao mesmo modelo retornam versões diferentes
- **THEN** o evento é gravado e a sessão continua, qualquer que seja `ON_MODEL_VERSION_CHANGE`

#### Scenario: Versão nova informada com a política retomar
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=retomar` e um provedor simulado que informa `v1` na primeira chamada e `v2` na segunda
- **WHEN** o próximo ponto de verificação de limites é alcançado
- **THEN** o checkpoint é gravado, o evento `versao_modelo_alterada` registra provedor, modelo, `anterior="v1"` e `nova="v2"`, e novas subtarefas continuam sendo despachadas
- **AND** os registros de proveniência posteriores ao evento trazem a versão `v2` e a sessão não fecha

#### Scenario: Versão desconhecida com substituição de modelo
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=retomar`, um catálogo de teste em que o papel Researcher tem `preferencia` com os modelos `m1` e `m2` (ambos elegíveis), e um provedor simulado que deixa de informar a versão de `m1`
- **WHEN** o próximo ponto de verificação de limites é alcançado
- **THEN** o papel Researcher passa a usar `m2` e o evento `modelo_substituido` registra `papel="researcher"`, `anterior="m1"`, `novo="m2"` e `motivo="versao_desconhecida"`
- **AND** a sessão não fecha

#### Scenario: Substituição respeita a família do Validator
- **GIVEN** as condições do cenário anterior para o papel Validator, em que o próximo modelo da `preferencia` é da mesma família do Developer e o seguinte é de família diferente
- **WHEN** o ponto de verificação é alcançado
- **THEN** o Validator passa ao modelo de família diferente e `modelo_substituido` registra esse modelo

#### Scenario: Substituição respeita a localidade
- **GIVEN** as condições do cenário "Versão desconhecida com substituição de modelo", com dados de pesquisa contaminados e o próximo modelo da `preferencia` na nuvem sem `aceita_dados_brutos`
- **WHEN** o ponto de verificação é alcançado
- **THEN** esse modelo é descartado e o seguinte elegível pela localidade é escolhido

#### Scenario: Sem modelo elegível
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=retomar` e um papel cujos modelos restantes na `preferencia` são todos inelegíveis
- **WHEN** a versão do modelo atual deixa de ser informada e o ponto de verificação é alcançado
- **THEN** a sessão fecha com `motivo_parada="versao_modelo"` com checkpoint e continua retomável, e nenhum evento `modelo_substituido` é gravado

#### Scenario: Troca de versão em modo strict com a política parar
- **GIVEN** `LLM_ROUTING=strict` e `ON_MODEL_VERSION_CHANGE=parar`
- **WHEN** a versão de um modelo muda durante a sessão
- **THEN** nenhuma nova subtarefa é despachada
- **AND** o fechamento é executado com `motivo_parada="versao_modelo"`

#### Scenario: Versão desconhecida em modo strict com a política parar
- **GIVEN** `LLM_ROUTING=strict`, `ON_MODEL_VERSION_CHANGE=parar` e um servidor compatível que não informa versão
- **WHEN** a primeira chamada desse papel termina
- **THEN** a sessão entra em fechamento no próximo ponto de verificação com `motivo_parada="versao_modelo"`

#### Scenario: Valor inválido de ON_MODEL_VERSION_CHANGE
- **GIVEN** `ON_MODEL_VERSION_CHANGE=talvez`
- **WHEN** `src/config.py` é importado
- **THEN** a inicialização falha com `ConfigurationError` que cita `ON_MODEL_VERSION_CHANGE` e os valores `retomar` e `parar`

## ADDED Requirements

### Requirement: Esgotamento de cota distinto de limite de taxa
_Origem: `v18.7-benchmark-fixes` (achado 4 da bateria V18.6); relacionado ao ADR 011 e ao ADR 017._
Os provedores de nuvem (`google`, `anthropic`, `openai`, `openai_compatible`) SHALL classificar como esgotamento de cota ou gasto o erro com status 429, 400, 402 ou 403 cuja mensagem contenha, sem diferenciar maiúsculas, um dos marcadores do provedor (`LLM_QUOTA_MARKERS_GOOGLE`, padrão `spending cap`; `LLM_QUOTA_MARKERS_ANTHROPIC`, padrão `credit balance is too low`; `LLM_QUOTA_MARKERS_OPENAI`, padrão `insufficient_quota`; `LLM_QUOTA_MARKERS_OPENAI_COMPATIBLE`, padrão vazio). Nesse caso o provedor SHALL levantar `ProviderQuotaExhausted` (provedor, modelo, status, detalhe truncado em 300 caracteres) sem retentar e sem trocar para o modelo de reserva, e SHALL registrar o esgotamento para a sessão corrente. Um 429 sem marcador SHALL continuar retentado como hoje. `is_retryable_error` SHALL devolver `False` para `ProviderQuotaExhausted`.

#### Scenario: Teto de gasto do Google
- **GIVEN** um `genai.Client` simulado cujo `generate_content` levanta erro 429 `RESOURCE_EXHAUSTED` com mensagem contendo `spending cap`, e `GOOGLE_FALLBACK_MODEL` diferente do modelo principal
- **WHEN** `GoogleProvider.generate` é chamado
- **THEN** `ProviderQuotaExhausted` é levantado com `provider="google"` e `status_code=429`
- **AND** `generate_content` foi chamado uma única vez e nunca com o modelo de reserva

#### Scenario: Limite por minuto do Google continua transitório
- **GIVEN** um `genai.Client` simulado que levanta 429 `RESOURCE_EXHAUSTED` com a mensagem `You exceeded your current quota, please check your plan and billing details` uma vez e depois responde com sucesso
- **WHEN** `GoogleProvider.generate` é chamado
- **THEN** a chamada é repetida e devolve a resposta de sucesso
- **AND** nenhum `ProviderQuotaExhausted` é levantado

#### Scenario: Cota da OpenAI lida no corpo do 429
- **GIVEN** um `httpx.MockTransport` que responde 429 com corpo `{"error": {"code": "insufficient_quota"}}`
- **WHEN** `OpenAIProvider.generate` é chamado
- **THEN** `ProviderQuotaExhausted` é levantado com `provider="openai"` sem retentativa

#### Scenario: Limite de taxa da OpenAI continua transitório
- **GIVEN** um `httpx.MockTransport` que responde 429 com corpo `{"error": {"code": "rate_limit_exceeded"}}` e depois 200
- **WHEN** `OpenAIProvider.generate` é chamado
- **THEN** a resposta de sucesso é devolvida após uma retentativa

#### Scenario: Marcadores configuráveis
- **GIVEN** `LLM_QUOTA_MARKERS_GOOGLE="monthly budget,spending cap"`
- **WHEN** a mensagem de um 429 do Google contém `Monthly Budget`
- **THEN** o erro é classificado como esgotamento de cota

### Requirement: Retentativa de conexão atribuída à sessão
_Origem: `v18.7-benchmark-fixes`; corrige a contagem exigida por `v18-usage-limits` ("Contabilização completa")._
`emit_connection_retry` SHALL gravar o evento com o `execution_id` resolvido na ordem: `AgentContext` corrente (`execution_id`, ou `session_id` na falta dele), `bound_execution_id()`, `EXECUTION_ID`/`SESSION_ID` do ambiente e, por fim, `"unknown"`. A resolução SHALL ser a mesma usada por `_task_env` do laço de agente.

#### Scenario: Agente em processo
- **GIVEN** um `AgentContext` vinculado com `execution_id="sessao-mestra-1"` e nenhuma variável `EXECUTION_ID` no ambiente
- **WHEN** um provedor emite `connection_retry`
- **THEN** o evento é gravado com `execution_id="sessao-mestra-1"`

#### Scenario: Planejamento fora do AgentContext
- **GIVEN** nenhum `AgentContext` e `bound_execution_id()` igual a `sessao-mestra-2`
- **WHEN** um provedor emite `connection_retry`
- **THEN** o evento é gravado com `execution_id="sessao-mestra-2"`

### Requirement: Resfriamento do limitador de taxa com teto
_Origem: `v18.7-benchmark-fixes` (achado 4 da bateria V18.6)._
`AdaptiveRateLimiter.report_429` SHALL manter o crescimento exponencial atual do resfriamento (`src/rate_limiter.py:86`), resfriamento da n-ésima chamada consecutiva igual a `LLM_RATE_LIMIT_COOLDOWN_SECONDS * 2^(n-1)`, e SHALL limitá-lo a `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` (padrão 300), isto é, `min(LLM_RATE_LIMIT_COOLDOWN_SECONDS * 2^(n-1), LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS)`. O orquestrador SHALL NOT chamar `report_429` para um resultado de agente com `error_category="cota_provedor"`.

#### Scenario: Teto do resfriamento
- **GIVEN** `LLM_RATE_LIMIT_COOLDOWN_SECONDS=30` e `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS=300`
- **WHEN** `report_429` é chamado 6 vezes seguidas, sem requisição bem-sucedida entre as chamadas
- **THEN** os resfriamentos aplicados são 30, 60, 120, 240, 300 e 300 segundos
- **AND** nenhum resfriamento passa de 300 segundos

#### Scenario: Cota não aciona o limitador
- **GIVEN** um `AgentResult` com `status="error"`, `error="429 RESOURCE_EXHAUSTED ... spending cap"` e `error_category="cota_provedor"`
- **WHEN** o orquestrador processa o resultado
- **THEN** `report_429` não é chamado
