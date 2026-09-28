# Delta: llm-providers

## ADDED Requirements

### Requirement: Registro único de provedores
O sistema SHALL resolver todo provedor LLM a partir de um único registro, consultado tanto
pela seleção global (`get_provider`) quanto pelo roteamento por papel (`ModelRouter`).

#### Scenario: Seleção global usa o registro
- **GIVEN** `LLM_PROVIDER=ollama` e `LLM_MODEL=qwen3:8b`
- **WHEN** `get_provider()` é chamado
- **THEN** retorna a instância criada pela fábrica registrada como `ollama`
- **AND** chamadas seguintes retornam a mesma instância

#### Scenario: Roteamento por papel usa o registro
- **GIVEN** `RESEARCHER_PROVIDER=openai_compatible` e `RESEARCHER_MODEL=llama-3.1-8b`
- **WHEN** `ModelRouter.get_provider("researcher")` é chamado
- **THEN** retorna um provedor `openai_compatible` com `model_name == "llama-3.1-8b"`

#### Scenario: Alias legado
- **WHEN** um provedor é pedido pelo nome `local`
- **THEN** o registro resolve para o provedor `ollama`

#### Scenario: Provedor desconhecido
- **WHEN** um provedor é pedido pelo nome `inexistente`
- **THEN** o sistema levanta `ValueError` cuja mensagem lista os provedores disponíveis

### Requirement: Adicionar provedor sem editar código central
O sistema SHALL permitir adicionar um provedor apenas implementando `LLMProvider` e
registrando uma fábrica, sem alterar `factory.py` nem `model_router.py`.

#### Scenario: Provedor de teste registrado
- **GIVEN** um provedor fictício registrado com `register_provider("fake", ...)` em um teste
- **WHEN** `ModelRouter.get_provider` é chamado para um papel configurado com `fake`
- **THEN** o provedor fictício é retornado

### Requirement: Dependência opcional ausente não quebra outros provedores
O sistema SHALL importar o pacote de cada provedor somente quando aquele provedor for
instanciado.

#### Scenario: Pacote google-genai não instalado
- **GIVEN** que `google.genai` não pode ser importado
- **WHEN** o provedor `ollama` é pedido
- **THEN** a instância é criada normalmente
- **AND** pedir o provedor `google` levanta erro indicando `uv sync --extra google`

### Requirement: Provedor compatível com a API da OpenAI
O sistema SHALL oferecer o provedor `openai_compatible`, que conversa com qualquer servidor que
implemente `/v1/chat/completions`, com suporte a tool calling e streaming, usando `httpx`.

#### Scenario: Resposta com tool call
- **GIVEN** um servidor que responde `choices[0].message.tool_calls` com uma chamada
- **WHEN** `generate` é chamado com `tools`
- **THEN** o `LLMResponse` contém um `ToolCall` com `name` e `arguments` como `dict`
- **AND** `finish_reason == "tool_calls"`

#### Scenario: Argumentos de tool call inválidos
- **GIVEN** um tool call cujos argumentos não são JSON válido
- **WHEN** a resposta é convertida
- **THEN** o `ToolCall` traz `arguments == {"_raw": <texto original>}` e um aviso é registrado

#### Scenario: Uso de tokens
- **WHEN** a resposta inclui `usage`
- **THEN** `LLMResponse.usage` contém `prompt_tokens`, `completion_tokens` e `total_tokens`

#### Scenario: Limite de taxa
- **GIVEN** o servidor responde 429 e depois 200
- **WHEN** `generate` é chamado
- **THEN** a chamada é repetida com backoff e retorna a resposta de sucesso
- **AND** a retentativa é registrada na telemetria

#### Scenario: Chave de API não vaza
- **WHEN** as configurações de um provedor são registradas em log ou convertidas em texto
- **THEN** o valor de `api_key` não aparece

## REMOVED Requirements

### Requirement: Dependência do Google Agent Development Kit
**Motivo:** nenhum módulo importa `google.adk`; o projeto deve ser agnóstico a provedor
(ADR 011 §4).

#### Scenario: Dependência removida
- **WHEN** o `pyproject.toml` é inspecionado
- **THEN** não há `google-adk` em nenhuma lista de dependências
