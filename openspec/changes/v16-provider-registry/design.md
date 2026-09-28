# Design: Registro Único de Provedores LLM

## Estado atual

- `src/llm/base.py` define `LLMProvider` (ABC) com `generate`, `generate_stream`,
  `health_check`, `model_name`; `LLMResponse` e `ToolCall` já usam formato OpenAI.
- `src/llm/factory.py::get_provider()` — singleton global a partir de `config.LLM_PROVIDER`.
- `src/model_router.py::ModelRouter.get_provider(role)` — cache por `(provider, model)` a
  partir de `src/model_config.py::get_role_model_config(role)` (`{ROLE}_PROVIDER`,
  `{ROLE}_MODEL`).
- Provedores: `src/llm/providers/google.py` (`GoogleProvider`, usa `google.genai`) e
  `src/llm/providers/ollama.py` (`OllamaProvider`).

## Decisões

### 1. Registro

```python
# src/llm/registry.py
ProviderFactory = Callable[[ProviderSettings], LLMProvider]

@dataclass(frozen=True)
class ProviderSettings:
    name: str            # nome canônico do provedor
    model: str
    base_url: str | None
    api_key: str | None  # resolvido de config; nunca logado

def register_provider(name: str, factory: ProviderFactory, aliases: tuple[str, ...] = ()) -> None
def create_provider(name: str, model: str) -> LLMProvider
def available_providers() -> list[str]
```

- Registro em módulo (dicionário), preenchido por `src/llm/providers/__init__.py` com
  **import preguiçoso** dentro de cada fábrica — um provedor cujo pacote opcional não está
  instalado (ex.: `google-genai`) não quebra os demais; a falha só ocorre ao pedir aquele
  provedor, com mensagem indicando o extra a instalar (`uv sync --extra google`).
- `create_provider` resolve `base_url` e `api_key` a partir de `config` por convenção de
  nome: `<PROVIDER>_BASE_URL`, `<PROVIDER>_API_KEY`. Nomes existentes que fogem à convenção
  literal são mantidos como mapeamento explícito, quando o nome do ecossistema já é outro:
  `OLLAMA_BASE_URL` (compatibilidade), `GEMINI_API_KEY` (provedor `google`, nome do
  ecossistema Gemini) e `OPENAI_BASE_URL`/`OPENAI_API_KEY` (provedor `openai_compatible`,
  mesmo nome que vLLM, LM Studio e litellm já usam para apontar para um servidor compatível
  — evita o sufixo redundante `_COMPATIBLE_` na variável de ambiente sem abrir mão do nome
  `openai_compatible` no registro, que evita colidir com um futuro provedor nativo `openai`).
- Nome desconhecido → `ValueError` listando `available_providers()`.

### 2. Consumidores

- `get_provider()` → `create_provider(config.LLM_PROVIDER, config.LLM_MODEL)`, mantendo o
  singleton.
- `ModelRouter.get_provider(role)` → `create_provider(role_cfg.provider, role_cfg.model)`,
  mantendo o cache `(provider, model)`.
- O comentário "V18/retrocompatibilidade" em `model_router.py` é corrigido.

### 3. Provedor `openai_compatible`

- Usa `httpx.AsyncClient` (já é dependência) — **sem** o SDK `openai`, para não acrescentar
  dependências.
- `generate`: POST `{base_url}/chat/completions` com `model`, `messages` (system prepended
  como mensagem `system`), `tools`, `temperature`, `max_tokens`. Converte
  `choices[0].message.tool_calls` em `ToolCall` (argumentos JSON → `dict`; JSON inválido →
  `ToolCall` com `arguments={"_raw": ...}` e log de aviso). `usage` →
  `{"prompt_tokens", "completion_tokens", "total_tokens"}`.
- `generate_stream`: `stream=true`, parse de SSE `data:` até `[DONE]`.
- `health_check`: GET `{base_url}/models` com timeout curto.
- Timeouts e retentativas: reaproveitar o mesmo padrão de retentativa com backoff do
  `OllamaProvider` (erros 429/5xx e de conexão). Retentativas de conexão são contabilizadas
  por telemetria (insumo para `v18-usage-limits`).

### 4. Remoção do ADK

- `pyproject.toml`: remover `google-adk>=1.27.2`; rodar `uv lock`.
- `grep -ri "google.adk\|google-adk\|agentes ADK"` deve retornar apenas documentos históricos
  (roadmaps antigos e ADRs).

## Análise de impacto (6 eixos — `architect.md`)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Nenhum; continua pedindo provedor ao `ModelRouter`. |
| Agentes & Prompts | Nenhum. |
| Sandboxes & Containers | Nenhum. Imagens ficam menores sem `google-adk`. |
| Persistência | Nenhuma migração. |
| Segurança | Novas chaves de API via `.env`; `ProviderSettings.api_key` nunca aparece em log nem em `repr` (`field(repr=False)`). Base URL arbitrária é configuração do operador, não do LLM. |
| Testes & Telemetria | Testes de contrato por provedor; telemetria de tokens inalterada (`usage`). |

## Riscos

- **Divergência de tool calling entre servidores OpenAI-compatíveis** — mitigação: testes com
  respostas gravadas (fixtures) de ao menos dois formatos (llama.cpp e vLLM).
- **Quebra de patches em testes** — mitigação: tarefa explícita de ajuste.
