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
`AdaptiveRateLimiter.report_429` SHALL limitar o resfriamento a `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS` (padrão 300). O orquestrador SHALL NOT chamar `report_429` para um resultado de agente com `error_category="cota_provedor"`.

#### Scenario: Teto do resfriamento
- **GIVEN** `LLM_RATE_LIMIT_COOLDOWN_SECONDS=30` e `LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS=300`
- **WHEN** `report_429` é chamado 9 vezes seguidas
- **THEN** o resfriamento aplicado na nona chamada é 300 segundos

#### Scenario: Cota não aciona o limitador
- **GIVEN** um `AgentResult` com `status="error"`, `error="429 RESOURCE_EXHAUSTED ... spending cap"` e `error_category="cota_provedor"`
- **WHEN** o orquestrador processa o resultado
- **THEN** `report_429` não é chamado
