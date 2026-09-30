# Tarefas: v16-anthropic-provider

## 1. Contrato e configuração
- [x] 1.1 `LLMResponse.provider_data` e sua inclusão em `to_message()` só quando presente.
- [x] 1.2 `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_EFFORT` e `ANTHROPIC_REFUSAL_FALLBACK` em `src/config.py` e `.env.example`.
- [x] 1.3 Extra opcional `anthropic` no `pyproject.toml` e `uv.lock`.

## 2. Provedor
- [x] 2.1 `AnthropicProvider` (`generate`, `generate_stream`, `health_check`, `model_name`).
- [x] 2.2 Conversão de histórico e de ferramentas (tool_result primeiro, `system` extraído).
- [x] 2.3 Blocos de pensamento em `provider_data`, com descarte quando a mensagem foi editada.
- [x] 2.4 Retentativa própria com telemetria `connection_retry`.
- [x] 2.5 Recusa como `ProviderRefusalError`.
- [x] 2.6 Registro em `src/llm/providers/__init__.py`.

## 3. Testes (SDK simulado, sem rede)
- [x] 3.1 Não envia `temperature`, `tool_choice` nem `thinking`; piso de `max_tokens`; `effort` e fallback.
- [x] 3.2 Conversão de mensagens e ferramentas; ida e volta dos blocos de pensamento.
- [x] 3.3 Retentativas (429, 529, conexão), erro de cliente sem retentativa, esgotamento.
- [x] 3.4 Recusa, fallback do servidor, uso de tokens com cache, `health_check` e streaming.

## 4. Validação com a API real (pesquisador)
- [ ] 4.1 Definir `ANTHROPIC_API_KEY` no `.env` do Pi.
- [ ] 4.2 Sessão de referência com Developer no Google e Researcher/Validator/Reviewer no Claude; registrar tempo, RAM e tokens.
