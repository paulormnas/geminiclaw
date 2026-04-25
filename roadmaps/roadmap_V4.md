# Roadmap V4 — Inteligência Local (Ollama + Modelo Único)
**Versão melhorada com base na análise do código existente e benchmarks reais no Pi 5**

Este roadmap descreve a transição do GeminiClaw de um framework dependente de nuvem para uma
solução auto-hospedada, utilizando um único modelo local via Ollama no Raspberry Pi 5.

> **Contexto:** O desenvolvimento está bloqueado na etapa S8 por erros 429 e 503 da API do
> Google Gemini. Todas as etapas dos Roadmaps v1–v3 estão concluídas, exceto a validação S8.
> O foco deste roadmap é eliminar a dependência de rede para inferência, mantendo a
> compatibilidade com a arquitetura MAS e Docker existente.

---

## Avaliação do Estado Atual (v3.x)

### Pontos fortes a preservar

- Arquitetura MAS com DAG de subtarefas e retry por subtarefa (S7)
- Skills Framework modular com `BaseSkill` e `SkillRegistry`
- IPC via Unix Sockets com protocolo JSON length-prefix robusto
- Monitoramento de saúde do Pi 5 (`PiHealthMonitor`, etapa V15)
- Loop Autônomo com Planner → Validator → Execução e re-planejamento

### Problemas que motivam este roadmap

| # | Problema | Impacto | Localização no código |
|---|---|---|---|
| 1 | `GEMINI_API_KEY` obrigatório em `config.py` | Falha ao iniciar sem chave | `src/config.py:23` |
| 2 | `google-adk` e `google-genai` hardcoded como dependências diretas | Impossível rodar sem SDK do Google | `pyproject.toml`, `agents/*/agent.py` |
| 3 | `google.adk.agents.Agent` instanciado diretamente nos agentes | Sem ponto de extensão para outros backends | `agents/base/agent.py:9` |
| 4 | Rate limit 429 bloqueia S8 | Desenvolvimento completamente travado | `src/config.py: GEMINI_REQUESTS_PER_MINUTE` |
| 5 | Variáveis de ambiente nomeadas como `GEMINI_*` | Confusão quando houver múltiplos backends | `.env.example`, `src/config.py` |

---

## Decisão de Arquitetura: Modelo Único no Pi 5

### Por que modelo único?

O Raspberry Pi 5 (8 GB RAM) não tem memória suficiente para carregar dois modelos
simultaneamente. Tentar isso causaria swap intenso de disco, degradando o throughput
para valores inutilizáveis. A arquitetura correta é:

```
Um único modelo em memória → Ollama serializa as requisições dos agentes
```

O `asyncio.Semaphore(3)` do `ContainerRunner` garante que no máximo 3 agentes
rodem ao mesmo tempo, mas todos compartilham **o mesmo processo Ollama** e o
**mesmo modelo carregado**.

### Comparativo de modelos para Pi 5 (CPU-only, 8 GB RAM)

Dados baseados em benchmarks reais no Raspberry Pi 5 e especificações oficiais (Abril 2026):

| Modelo | Lançamento | Ollama tag | RAM (Q4_K_M) | Tok/s Pi 5 (CPU) | Tool Calling | Recomendação |
|---|---|---|---|---|---|---|
| **Qwen3.5-4B** | Mar/2026 | `qwen3.5:4b` | ~2,5 GB | ~10–14 t/s | ⭐⭐⭐ Excelente | ✅ **Escolhido** |
| Gemma 4 E2B | Abr/2026 | `gemma4:e2b` | ~1,5 GB | ~3–8 t/s | ⭐⭐ Bom | ⚠️ Alternativa rápida |
| Qwen3.5-2B | Mar/2026 | `qwen3.5:2b` | ~1,3 GB | ~18–25 t/s | ⭐⭐ Regular | ⚠️ Rápido, mas insuficiente |
| Gemma 4 E4B | Abr/2026 | `gemma4:e4b` | ~5,0 GB | ~3–5 t/s | ⭐⭐ Bom | ❌ Causa swap no Pi 5 |
| Gemma 4 26B A4B | Abr/2026 | `gemma4` | ~9,6 GB | N/A | ⭐⭐⭐ Excelente | ❌ Ultrapassa 8 GB |

> **Por que Qwen3.5-4B?**
>
> - **Geração mais recente:** lançado em 2 de Março de 2026 (série small), supera o Qwen3 original
>   em todas as métricas — incluindo IFBench (76,5, melhor que GPT-5.2) e Tau2-Bench (86,7
>   em tarefas agênticas, segundo melhor entre todos os modelos testados).
> - **Tool calling de ponta no seu tamanho:** o Qwen3.5-4B rivaliza com modelos muito
>   maiores em uso de ferramentas e geração de JSON estruturado — crítico para o Planner
>   (JSON de subtarefas) e o Validator (análise de planos com formato fixo).
> - **Throughput adequado no Pi 5:** ~10–14 tok/s em CPU-only com Q4_K_M. Mais lento que
>   a API do Google, mas suficiente para sessões de trabalho assíncronas.
> - **Memória segura:** ~2,5 GB deixa margem confortável para SO (~1,5 GB), Docker e
>   agentes (~0,75 GB), Qdrant (~0,5 GB) e KV cache (~0,5 GB), totalizando ~1,25 GB
>   de margem de segurança nos 8 GB do Pi 5.
> - **Modo não-thinking:** suporta alternância entre raciocínio (chain-of-thought) e modo
>   direto. Para Planner e Validator, desabilitar o thinking reduz tokens e acelera
>   a geração de planos JSON.
> - **Licença Apache 2.0:** sem restrições para uso comercial ou redistribuição.
>
> **Por que não Gemma 4?**
>
> O **E4B** (~5 GB) causa swap intenso no Pi 5 e cai para 3–5 tok/s em benchmarks reais —
> inviável para um sistema multi-agente. O **E2B** (~1,5 GB) cabe com folga, mas rende
> apenas 3–8 tok/s e tem raciocínio inferior ao Qwen3.5-4B em tarefas estruturadas como
> geração de planos JSON. O **26B A4B** (o padrão `gemma4` no Ollama) exige ~9,6 GB e
> ultrapassa a RAM disponível do Pi 5. O Qwen3.5-4B é o único modelo atual que equilibra
> RAM, velocidade e qualidade de tool calling neste hardware.
>
> **Alternativa futura:** se o projeto migrar para um Pi 5 com armazenamento NVMe e
> um co-processador de inferência (ex: Hailo-8L via HAT+), o `gemma4:e4b` pode se tornar
> viável com aceleração de hardware dedicada.

### Budget de memória no Pi 5 (8 GB)

| Componente | RAM estimada |
|---|---|
| Raspberry Pi OS (64-bit) + processos base | ~1,5 GB |
| Ollama + Qwen3.5-4B (Q4_K_M carregado) | ~2,5 GB |
| Orquestrador GeminiClaw + Docker daemon | ~0,8 GB |
| Containers de agentes (máx. 3 × 256 MB) | ~0,75 GB |
| Qdrant (DeepSearch) | ~0,5 GB |
| KV cache Ollama (contexto de 4096 tokens) | ~0,5 GB |
| **Margem de segurança** | **~1,45 GB** |
| **Total** | **8,0 GB** |

---

## Análise de Impacto: o que muda e o que NÃO muda

### O que **NÃO muda** (preservado integralmente)

- `src/skills/` — Skills Framework completo (QuickSearch, DeepSearch, Code, Memory)
- `src/ipc.py` — Protocolo IPC via sockets
- `src/session.py` — Persistência SQLite
- `src/autonomous_loop.py` — Lógica de DAG, Planner, Validator
- `src/runner.py` — ContainerRunner e PiHealthMonitor (apenas adições)
- `docker-compose.yml` — Infraestrutura de serviços (apenas adições)
- `tests/` — Suite de testes unit existente

### O que **muda**

| Arquivo | Tipo de mudança |
|---|---|
| `src/config.py` | Renomear `GEMINI_*` → `LLM_*`; tornar `GEMINI_API_KEY` opcional |
| `.env.example` | Adicionar variáveis `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `LLM_MODEL` |
| `agents/*/agent.py` | Substituir `google.adk.agents.Agent` por wrapper abstrato |
| `pyproject.toml` | Mover `google-adk` e `google-genai` para dependências opcionais |
| `src/runner.py` | Passar `LLM_PROVIDER` e `LLM_MODEL` como env vars para containers |

### O que é **criado do zero**

```
src/llm/
├── __init__.py          # Exporta LLMProvider, LLMResponse, get_provider()
├── base.py              # LLMProvider (ABC) — contrato público
├── factory.py           # Instancia o provedor correto com base em LLM_PROVIDER
├── agent_loop.py        # Loop de inferência + tool calling independente do ADK
├── context_compression.py  # Truncagem inteligente de histórico
└── providers/
    ├── __init__.py
    ├── google.py        # GoogleProvider — encapsula google-adk (legado/fallback)
    └── ollama.py        # OllamaProvider — API OpenAI-compatível do Ollama
```

---

## Etapa V17 — Abstração do Provedor LLM

**Objetivo:** Criar a interface `LLMProvider` e a factory que desacoplam completamente o
backend de inferência do restante do código.

**Critério de aceite:** `from src.llm import get_provider` funciona e retorna um objeto
com os métodos definidos na interface, independentemente do valor de `LLM_PROVIDER`.

### V17.1 — Definir a interface `LLMProvider`

Criar `src/llm/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length"
    usage: dict = field(default_factory=dict)

class LLMProvider(ABC):
    """Interface contratual para qualquer backend de inferência."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Gera uma resposta. `tools` no formato OpenAI Tool Calling."""
        ...

    @abstractmethod
    async def generate_stream(self, messages: list[dict], system: str | None = None):
        """Gera resposta em streaming. Yield de chunks de texto."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Retorna True se o backend está acessível e operacional."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nome do modelo em uso (ex: 'qwen3.5:4b', 'gemini-2.0-flash')."""
        ...
```

> **Nota sobre Tool Calling:** O Google ADK usa seu próprio formato de ferramentas.
> O Ollama usa o formato OpenAI (`{"type": "function", "function": {...}}`). A abstração
> usa o formato OpenAI como padrão. O `GoogleProvider` converte internamente.

### V17.2 — Implementar `OllamaProvider`

Criar `src/llm/providers/ollama.py`. Pontos críticos de implementação:

```python
import asyncio, json, os, time
import httpx
from src.llm.base import LLMProvider, LLMResponse, ToolCall

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model
        # Reutilizar cliente HTTP — evita overhead de conexão no Pi 5
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(300.0),  # timeout alto: CPU-only é lento
        )
        # Throttling interno para não sobrecarregar o Pi 5
        self._rpm_limit = int(os.getenv("LLM_REQUESTS_PER_MINUTE", "15"))
        self._request_times: list[float] = []
        self._lock = asyncio.Lock()

    async def _throttle(self):
        """Controla a taxa de requisições para proteger o Pi 5."""
        async with self._lock:
            now = time.monotonic()
            self._request_times = [t for t in self._request_times if now - t < 60]
            if len(self._request_times) >= self._rpm_limit:
                wait = 60 - (now - self._request_times[0])
                if wait > 0:
                    await asyncio.sleep(wait)
            self._request_times.append(time.monotonic())

    async def generate(self, messages, tools=None, system=None, **kwargs) -> LLMResponse:
        await self._throttle()

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 4096),
                # Limitar contexto para proteger RAM do Pi 5
                "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096")),
            }
        }
        # Desabilitar thinking mode do Qwen3.5.5 para respostas mais rápidas
        # (pode ser habilitado por agente via variável de ambiente)
        if os.getenv("OLLAMA_ENABLE_THINKING", "false").lower() == "false":
            # O Qwen3.5 respeita a instrução no system prompt para desabilitar thinking
            no_think_suffix = "\n/no_think"
            if system:
                system = system + no_think_suffix
            else:
                system = no_think_suffix

        if tools:
            payload["tools"] = tools
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + list(messages)

        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()

        message = data.get("message", {})
        tool_calls = []
        for tc in message.get("tool_calls", []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(ToolCall(
                id=tc.get("id", fn.get("name", "")),
                name=fn.get("name", ""),
                arguments=args,
            ))

        return LLMResponse(
            text=message.get("content"),
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=data.get("eval_count", {}),
        )

    async def health_check(self) -> bool:
        try:
            r = await self._client.get("/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self._model
```

### V17.3 — Encapsular Google ADK em `GoogleProvider`

Criar `src/llm/providers/google.py` movendo a lógica atual de inferência.
Este provider é mantido como fallback opcional.

### V17.4 — Implementar `factory.py`

```python
# src/llm/factory.py
import os
from src.llm.base import LLMProvider

_provider_instance: LLMProvider | None = None

def get_provider() -> LLMProvider:
    """Retorna uma instância singleton do provedor configurado."""
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    provider_type = os.getenv("LLM_PROVIDER", "google")

    if provider_type in ("local", "ollama"):
        from src.llm.providers.ollama import OllamaProvider
        _provider_instance = OllamaProvider(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("LLM_MODEL", "qwen3.5:4b"),
        )
    elif provider_type == "google":
        from src.llm.providers.google import GoogleProvider
        _provider_instance = GoogleProvider()
    else:
        raise ValueError(
            f"LLM_PROVIDER inválido: '{provider_type}'. Use: google | ollama | local"
        )

    return _provider_instance
```

> **Singleton:** A factory retorna sempre a mesma instância, garantindo que o cliente
> HTTP do Ollama seja reutilizado entre chamadas (importante para performance no Pi 5).

### Tarefas desta etapa

- [x] Criar `src/llm/__init__.py`, `base.py`
- [x] Implementar `src/llm/providers/ollama.py` com throttling integrado
- [x] Implementar `src/llm/providers/google.py` (wrapper do ADK existente)
- [x] Implementar `src/llm/factory.py` como singleton
- [x] Adicionar testes unitários em `tests/unit/test_llm_factory.py` com mock HTTP
- [x] Commit: `feat(llm): introduz abstração LLMProvider com suporte a Ollama e Google`

---

## Etapa V18 — Migração de Config e `.env`

**Objetivo:** Renomear variáveis `GEMINI_*` para `LLM_*` e tornar a API key do Google
opcional, sem quebrar instalações existentes.

**Critério de aceite:** O projeto inicia sem `GEMINI_API_KEY` quando `LLM_PROVIDER=ollama`.

### V18.1 — Atualizar `src/config.py`

```python
# Provedor e modelo — novos
LLM_PROVIDER = get_env("LLM_PROVIDER", default="google")
LLM_MODEL = get_env("LLM_MODEL", default="qwen3.5:4b")
OLLAMA_BASE_URL = get_env("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_NUM_CTX = int(get_env("OLLAMA_NUM_CTX", default="4096"))
OLLAMA_ENABLE_THINKING = get_env("OLLAMA_ENABLE_THINKING", default="false")

# Google API key: obrigatória APENAS quando provider for google
GEMINI_API_KEY = get_env(
    "GEMINI_API_KEY",
    required=(LLM_PROVIDER == "google"),
)

# Rate limiting — ler nova variável com fallback para a antiga (retrocompatibilidade)
LLM_REQUESTS_PER_MINUTE = int(
    get_env("LLM_REQUESTS_PER_MINUTE")
    or get_env("GEMINI_REQUESTS_PER_MINUTE", default="15")
)
LLM_RATE_LIMIT_COOLDOWN_SECONDS = int(
    get_env("LLM_RATE_LIMIT_COOLDOWN_SECONDS")
    or get_env("GEMINI_RATE_LIMIT_COOLDOWN_SECONDS", default="30")
)

# Perfil de deployment (ajusta limites automaticamente)
DEPLOYMENT_PROFILE = get_env("DEPLOYMENT_PROFILE", default="default")
if DEPLOYMENT_PROFILE == "pi5":
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="5"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="2"))
    AGENT_TIMEOUT_SECONDS = int(get_env("AGENT_TIMEOUT_SECONDS", default="300"))
else:
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="10"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="3"))
    AGENT_TIMEOUT_SECONDS = int(get_env("AGENT_TIMEOUT_SECONDS", default="120"))
```

### V18.2 — Atualizar `.env.example`

```dotenv
# ============================================================
# CONFIGURAÇÃO DO PROVEDOR LLM (Roadmap V4)
# ============================================================

# Provedor ativo: google | ollama | local
# Use 'ollama' para inferência local no Raspberry Pi 5
LLM_PROVIDER=google

# Modelo a usar (depende do provedor)
# Para Ollama no Pi 5: qwen3.5:4b (recomendado — melhor tool calling no Pi 5)
# Para Google: gemini-2.0-flash, gemini-2.5-pro
LLM_MODEL=qwen3.5:4b

# URL do servidor Ollama (quando LLM_PROVIDER=ollama)
OLLAMA_BASE_URL=http://localhost:11434

# Tamanho do contexto em tokens (Ollama)
# 4096 é seguro para 8 GB. Reduzir para 2048 se houver OOM.
# NÃO exceder 8192 sem monitorar o uso de RAM.
OLLAMA_NUM_CTX=4096

# Modo thinking do Qwen3.5 (true = raciocínio step-by-step, false = resposta direta)
# false é recomendado para o Pi 5: economiza tokens e acelera respostas.
# Habilitar apenas para tarefas que exigem raciocínio profundo.
OLLAMA_ENABLE_THINKING=false

# Chave da API do Google (obrigatória apenas quando LLM_PROVIDER=google)
GEMINI_API_KEY=your_api_key_here

# Rate limiting (substitui GEMINI_REQUESTS_PER_MINUTE)
# Para Ollama local, controla a taxa de requisições ao Pi 5
LLM_REQUESTS_PER_MINUTE=10
LLM_RATE_LIMIT_COOLDOWN_SECONDS=5

# ============================================================
# PERFIL DE DEPLOYMENT
# ============================================================
# Valores: default | pi5
# pi5: ajusta automaticamente timeouts, concorrência e limites de subtarefas
DEPLOYMENT_PROFILE=pi5
```

### V18.3 — Atualizar `pyproject.toml`

Mover `google-adk` e `google-genai` para dependências opcionais:

```toml
[project]
dependencies = [
    # Core — sem dependência do Google
    "beautifulsoup4>=4.14.3",
    "docker>=7.1.0",
    "httpx>=0.28.1",
    "lxml>=6.0.2",
    "python-dotenv>=1.2.2",
    "qdrant-client>=1.17.1",
    "sqlite-utils>=3.39",
]

[project.optional-dependencies]
google = [
    "google-adk>=1.27.2",
    "google-genai>=1.3.0",
]
deep_search = [
    "fastembed>=0.7.4",
    "qdrant-client>=1.17.1",
]
# Instalar tudo: uv sync --all-extras
# Instalar apenas local (Pi 5): uv sync
# Instalar com Google: uv sync --extra google
```

### Tarefas desta etapa

- [x] Atualizar `src/config.py` com as novas variáveis, retrocompatibilidade e `DEPLOYMENT_PROFILE`
- [x] Atualizar `.env.example` com bloco de configuração LLM
- [x] Mover `google-adk` e `google-genai` para extras em `pyproject.toml`
- [x] Atualizar `scripts/build_images.sh` para instalar extras corretos por modo
- [x] Atualizar `README.md` com tabela de modos de instalação e exemplo Pi 5
- [x] Commit: `feat(config): migra GEMINI_* para LLM_*; adiciona DEPLOYMENT_PROFILE=pi5`

---

## Etapa V19 — Adaptação dos Agentes ao Novo Backend

**Objetivo:** Substituir o uso direto do `google.adk.agents.Agent` nos agentes por um
wrapper que usa `LLMProvider`, mantendo as skills e o protocolo IPC intactos.

**Critério de aceite:** O agente base executa uma tarefa completa (incluindo uso de skills)
com `LLM_PROVIDER=ollama` e `LLM_MODEL=qwen3.5:4b`.

### V19.1 — Criar `src/llm/agent_loop.py`

O novo fluxo substitui o runner do ADK por um loop próprio de tool calling:

```python
# src/llm/agent_loop.py
import json
from src.llm.base import LLMProvider, LLMResponse

MAX_TOOL_ITERATIONS = 10  # Evitar loops infinitos

async def run_agent_loop(
    provider: LLMProvider,
    messages: list[dict],
    tools: list[dict],
    tool_executor,  # callable(name: str, arguments: dict) -> str
    system: str | None = None,
) -> str:
    """Loop de inferência + tool calling, independente do ADK.

    O Qwen3.5 com tool calling funciona assim:
    1. Modelo recebe mensagens + definição de ferramentas
    2. Se decidir usar uma ferramenta, retorna tool_calls (sem texto final)
    3. Executor roda a ferramenta e adiciona resultado ao histórico
    4. Modelo recebe o resultado e decide: mais ferramentas ou resposta final
    """
    history = list(messages)

    for _ in range(MAX_TOOL_ITERATIONS):
        response: LLMResponse = await provider.generate(
            messages=history,
            tools=tools or [],
            system=system,
        )

        if not response.tool_calls:
            return response.text or ""

        # Adicionar turno do assistente com as tool calls ao histórico
        history.append({
            "role": "assistant",
            "content": response.text,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ],
        })

        # Executar cada ferramenta e adicionar resultado
        for tc in response.tool_calls:
            result = await tool_executor(tc.name, tc.arguments)
            history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result),
            })

    return "[Limite de iterações de ferramentas atingido]"
```

### V19.2 — Adicionar `to_openai_tools()` ao `SkillRegistry`

```python
# src/skills/__init__.py — adicionar ao SkillRegistry
def to_openai_tools(self) -> list[dict]:
    """Exporta skills no formato OpenAI Tool Calling (compatível com Ollama/Qwen3.5)."""
    return [
        {
            "type": "function",
            "function": {
                "name": skill.name,
                "description": skill.description,
                "parameters": skill.parameters_schema,  # JSON Schema
            },
        }
        for skill in self._skills.values()
        if skill.enabled
    ]

async def execute(self, name: str, arguments: dict) -> str:
    """Executa uma skill pelo nome. Retorna resultado como string."""
    skill = self._skills.get(name)
    if not skill:
        return f"[Erro: skill '{name}' não encontrada]"
    result = await skill.run(**arguments)
    return result.output if hasattr(result, "output") else str(result)
```

### V19.3 — Refatorar os agentes

Cada `agents/*/agent.py` deixa de importar `google.adk` e passa a usar:

```python
# agents/base/agent.py — estrutura após refatoração
from src.llm.factory import get_provider
from src.llm.agent_loop import run_agent_loop
from src.skills import registry

provider = get_provider()

async def run(prompt: str, session_id: str, context: dict | None = None) -> str:
    memory_context = _load_long_term_memory(session_id)
    system = AGENT_INSTRUCTION + "\n\n" + memory_context

    messages = [{"role": "user", "content": prompt}]
    result = await run_agent_loop(
        provider=provider,
        messages=messages,
        tools=registry.to_openai_tools(),
        tool_executor=registry.execute,
        system=system,
    )
    _save_discoveries_to_memory(session_id, result)
    return result
```

> **Atenção aos callbacks ADK:** O `before_agent_callback` atual (que carrega contexto
> de sessão) precisa ser convertido para lógica Python pura, chamada explicitamente
> antes do `run_agent_loop`. Não há equivalente no novo fluxo — a chamada é direta.

### Tarefas desta etapa

- [x] Criar `src/llm/agent_loop.py`
- [x] Adicionar `to_openai_tools()`, `execute()` e `parameters_schema` ao `SkillRegistry`/`BaseSkill`
- [x] Refatorar `agents/base/agent.py`
- [x] Refatorar `agents/planner/agent.py`
- [x] Refatorar `agents/validator/agent.py`
- [x] Refatorar `agents/researcher/agent.py`
- [x] Converter callbacks ADK para funções Python puras
- [x] Adicionar testes de integração: `tests/integration/test_agent_with_ollama.py`
- [x] Commit: `refactor(agents): substitui google-adk por LLMProvider + agent_loop genérico`

---

## Etapa V20 — Infraestrutura Ollama no Raspberry Pi 5

**Objetivo:** Instalar, configurar e validar o Ollama com Qwen3.5-4B no Pi 5.

**Critério de aceite:** `ollama run qwen3.5:4b "teste de tool calling"` responde em menos
de 60 segundos no Pi 5 sem usar swap.

### V20.1 — Instalação do Ollama e download do modelo

Criar `scripts/setup_ollama_pi5.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Instalando Ollama no Raspberry Pi 5 ==="
curl -fsSL https://ollama.com/install.sh | sh

echo "=== Configurando serviço systemd ==="
# Cria override para configurações específicas do Pi 5
sudo mkdir -p /etc/systemd/system/ollama.service.d
cat <<EOF | sudo tee /etc/systemd/system/ollama.service.d/pi5.conf
[Service]
# Um request por vez (CPU-only — paralelismo causa thrashing)
Environment="OLLAMA_NUM_PARALLEL=1"
# Apenas 1 modelo na RAM — não trocar de modelo entre agentes
Environment="OLLAMA_MAX_LOADED_MODELS=1"
# Flash Attention reduz uso de memória
Environment="OLLAMA_FLASH_ATTENTION=1"
# Aceitar conexões dos containers Docker
Environment="OLLAMA_HOST=0.0.0.0:11434"
# Keep-alive: manter modelo na RAM entre requests (evita reload lento)
Environment="OLLAMA_KEEP_ALIVE=10m"
EOF

sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama

echo "=== Baixando Qwen3.5-4B (aguarde ~2 GB de download) ==="
ollama pull qwen3.5:4b

echo "=== Testando inferência ==="
ollama run qwen3.5:4b "Responda apenas: OK" --nowordwrap

echo "=== Ollama configurado com sucesso! ==="
echo "Modelo ativo: qwen3.5:4b"
echo "Endpoint: http://localhost:11434"
```

> **Por que `OLLAMA_NUM_PARALLEL=1` é crítico?**
> O GeminiClaw pode ter até 3 agentes rodando simultaneamente (semaphore). Se o Ollama
> tentasse processar 3 requests em paralelo numa CPU ARM sem GPU, causaria OOM ou
> thrashing severo. Com `NUM_PARALLEL=1`, o Ollama enfileira os requests — o throttling
> do `OllamaProvider` (`LLM_REQUESTS_PER_MINUTE`) complementa essa proteção no nível
> da aplicação.

### V20.2 — Adicionar Ollama ao `docker-compose.yml` (opcional, para dev em x86)

```yaml
# docker-compose.yml — adicionar serviço opcional para desenvolvimento
  ollama:
    image: ollama/ollama:latest
    profiles: ["local-llm"]  # Ativado apenas com: docker compose --profile local-llm up
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    networks:
      - geminiclaw-net
    # Para Pi 5, use Ollama nativo (não Docker) — melhor performance
    # Este serviço é apenas para desenvolvimento em x86/Mac

volumes:
  ollama_data:  # Adicionar ao bloco de volumes existente
```

### V20.3 — Passar configuração de backend para os containers de agentes

```python
# src/runner.py — ao criar o container de agente, adicionar env vars do LLM
environment = {
    # ... env vars existentes ...
    "LLM_PROVIDER": config.LLM_PROVIDER,
    "LLM_MODEL": config.LLM_MODEL,
    "OLLAMA_BASE_URL": config.OLLAMA_BASE_URL,
    "OLLAMA_NUM_CTX": str(config.OLLAMA_NUM_CTX),
    "OLLAMA_ENABLE_THINKING": config.OLLAMA_ENABLE_THINKING,
    "LLM_REQUESTS_PER_MINUTE": str(config.LLM_REQUESTS_PER_MINUTE),
}
```

### Tarefas desta etapa

- [x] Criar `scripts/setup_ollama_pi5.sh` com instalação e configuração systemd
- [x] Documentar instalação do Ollama no Pi 5 em `SETUP.md`
- [x] Adicionar serviço `ollama` com profile `local-llm` ao `docker-compose.yml`
- [x] Adicionar propagação de env vars LLM ao `runner.py`
- [x] Testar o boot completo do sistema no Pi 5 com `DEPLOYMENT_PROFILE=pi5`
- [x] Commit: `feat(infra): configura Ollama + Qwen3.5-4B para Pi 5 com instalação automatizada`

---

## Etapa V21 — Compressão de Contexto

**Objetivo:** Garantir que nenhuma requisição exceda `OLLAMA_NUM_CTX` tokens, evitando
OOM silencioso ou truncagem inesperada pelo Ollama.

**Critério de aceite:** Conversas longas são truncadas de forma inteligente sem perder
o contexto mais recente nem as instruções do sistema.

### V21.1 — Criar `src/llm/context_compression.py`

```python
# src/llm/context_compression.py

def estimate_tokens(text: str) -> int:
    """Estimativa rápida de tokens sem tokenizer. Aproximação: 1 token ≈ 4 chars."""
    return len(text) // 4

def compress_messages(
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
) -> list[dict]:
    """Trunca o histórico preservando: primeira mensagem do user + mensagens recentes.

    Estratégia:
    1. Sempre preservar: system prompt + última mensagem do usuário
    2. Preservar mensagens recentes até o limite
    3. Descartar mensagens antigas do meio da conversa
    """
    system_tokens = estimate_tokens(system or "")
    budget = max_tokens - system_tokens - 200  # margem de segurança

    # Sempre incluir a última mensagem do usuário
    must_keep = [messages[-1]] if messages else []
    must_keep_tokens = sum(estimate_tokens(str(m)) for m in must_keep)

    remaining_budget = budget - must_keep_tokens
    kept = []

    # Adicionar mensagens mais recentes primeiro (exceto a última, já incluída)
    for msg in reversed(messages[:-1]):
        tokens = estimate_tokens(str(msg))
        if remaining_budget - tokens > 0:
            kept.insert(0, msg)
            remaining_budget -= tokens
        else:
            break  # Histórico antigo descartado

    return kept + must_keep
```

### V21.2 — Integrar compressão ao `agent_loop.py`

```python
# src/llm/agent_loop.py — adicionar antes de cada chamada ao provider
from src.llm.context_compression import compress_messages
import os

MAX_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))

# Dentro do loop:
compressed_history = compress_messages(history, max_tokens=MAX_CTX, system=system)
response = await provider.generate(messages=compressed_history, ...)
```

### Tarefas desta etapa

- [ ] Criar `src/llm/context_compression.py`
- [ ] Integrar ao `agent_loop.py`
- [ ] Adicionar testes unitários para diferentes cenários de truncagem
- [ ] Commit: `feat(llm): compressão de contexto para modelos com janela limitada`

---

## Etapa V22 — Validação S8 com Modelo Local

**Objetivo:** Executar o cenário S8 completamente com `LLM_PROVIDER=ollama` e
`LLM_MODEL=qwen3.5:4b`, sem dependência de internet para inferência.

**Critério de aceite:** Uma tarefa complexa (pesquisa + código + relatório) é executada
end-to-end no Pi 5 com resultado coerente e sem erros de runtime.

### V22.1 — Ajustar prompts para modelos menores

Modelos de 4B parâmetros têm menor aderência a instruções complexas que o Gemini.
Pode ser necessário:

- Adicionar exemplos few-shot no JSON esperado pelo Planner
- Reduzir campos obrigatórios no schema de saída do Validator
- Simplificar critérios de aprovação do Validator para modelos locais

Adicionar variável `STRICT_VALIDATION=false` (desativa checagens mais rígidas
quando usando modelos locais com capacidade reduzida).

### V22.2 — Criar teste e2e para S8 local

```python
# tests/e2e/test_s8_local.py
"""
Valida o cenário S8 com inferência local (Ollama + Qwen3.5-4B).
Requer: Ollama rodando em localhost:11434 com qwen3.5:4b disponível.
"""
import pytest

@pytest.mark.e2e
@pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama não disponível — execute: ollama serve"
)
async def test_s8_pesquisa_e_relatorio():
    """Tarefa complexa: pesquisa sobre Python async + gera relatório em markdown."""
    result = await run_task(
        "Pesquise sobre asyncio em Python e gere um relatório markdown com exemplos"
    )
    assert result is not None
    assert len(result) > 100
    assert "async" in result.lower()
```

### V22.3 — Benchmark e documentação

Executar o mesmo prompt com Google e Ollama e registrar em `docs/benchmarks.md`:

| Métrica | Google (gemini-2.0-flash) | Ollama (qwen3.5:4b) |
|---|---|---|
| Latência primeira resposta | ? s | ? s |
| Tempo total tarefa complexa | ? s | ? s |
| Qualidade do plano (1–5) | ? | ? |
| Sucesso do tool calling (%) | ? | ? |
| Uso de RAM Pi 5 | N/A | ? GB |
| Tokens/s Pi 5 | N/A | ~10–14 |

### Tarefas desta etapa

- [ ] Ajustar prompts dos agentes para melhor aderência com Qwen3.5-4B
- [ ] Implementar `STRICT_VALIDATION` em `config.py`
- [ ] Criar `tests/e2e/test_s8_local.py`
- [ ] Executar benchmark e registrar em `docs/benchmarks.md`
- [ ] Commit: `test(e2e): valida S8 com Qwen3.5-4B via Ollama no Pi 5`

---

## Resumo Técnico das Mudanças

| Componente | Mudança | Etapa |
|---|---|---|
| `src/llm/` | Criado do zero — abstração completa | V17 |
| `src/config.py` | `GEMINI_API_KEY` opcional; `LLM_*`; `DEPLOYMENT_PROFILE` | V18 |
| `.env.example` | Bloco de configuração LLM + perfil pi5 | V18 |
| `pyproject.toml` | `google-adk` move para extras opcionais | V18 |
| `agents/*/agent.py` | Substituição do ADK por `agent_loop` genérico | V19 |
| `src/skills/__init__.py` | `to_openai_tools()` e `execute()` | V19 |
| `src/runner.py` | Propagação de env vars LLM para containers | V20 |
| `docker-compose.yml` | Serviço Ollama opcional (profile `local-llm`) | V20 |
| `scripts/setup_ollama_pi5.sh` | Criado do zero | V20 |
| `src/llm/context_compression.py` | Criado do zero | V21 |
| `tests/e2e/test_s8_local.py` | Criado do zero | V22 |
| `docs/benchmarks.md` | Criado do zero | V22 |

---

## Tabela de Status das Etapas

| Etapa | Descrição | Status |
|---|---|---|
| **SI–S7** | Infraestrutura + Skills + Loop Autônomo | ✅ Concluídas |
| **S8** | Validação em cenário real | 🔴 Bloqueada por 429 |
| **V1–V16** | Melhorias de qualidade (Roadmap v3) | ✅ Concluídas |
| **V17** | Abstração `LLMProvider` + `OllamaProvider` | ⬜ Pendente |
| **V18** | Migração config `GEMINI_*` → `LLM_*` | ⬜ Pendente |
| **V19** | Adaptação dos agentes (remoção do ADK) | ⬜ Pendente |
| **V20** | Infraestrutura Ollama + Qwen3.5-4B no Pi 5 | ⬜ Pendente |
| **V21** | Compressão de contexto | ⬜ Pendente |
| **V22** | Validação S8 com modelo local | ⬜ Pendente |

---

## Ordem de Implementação Recomendada

```
V18 (config) → V17 (abstração LLM) → V20 (Ollama Pi5) → V19 (agentes) → V21 (contexto) → V22 (S8)
```

Começar pela config (V18) garante que o projeto já inicia sem `GEMINI_API_KEY` quando
`LLM_PROVIDER=ollama`, desbloqueando o desenvolvimento local mesmo antes da abstração
completa estar pronta.

Instalar Ollama e fazer o pull do Qwen3.5-4B (V20) em paralelo com V17 — o download de
~2,5 GB leva tempo e pode ser feito enquanto o código da abstração é desenvolvido.