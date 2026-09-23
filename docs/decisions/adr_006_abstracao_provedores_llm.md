# ADR 006 — Abstração de Provedores LLM: Ollama + Google Gemini

**Status:** Aceito
**Data:** 2026-09-22
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V9_advanced_observability.md` (V9 — Abstração LLM)

---

## Contexto

O GeminiClaw é projetado para rodar em um Raspberry Pi 5 — um dispositivo de hardware limitado sem garantia de conectividade permanente com a internet. Ao mesmo tempo, modelos locais (Ollama) têm capacidade limitada comparados a modelos remotos (Google Gemini) para tarefas complexas como planejamento e geração de código científico.

Era necessário suportar ambos os modos de operação de forma transparente para o restante do sistema.

---

## Decisão

Adotar uma **camada de abstração de provedores LLM** com interface comum (`BaseLLMProvider`) e implementações específicas para cada provider.

### Interface Base

```python
# src/llm/base.py
class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict], tools: list[dict] | None) -> LLMResponse:
        """Envia mensagens e retorna a resposta do LLM."""

    @abstractmethod
    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Streaming de resposta token a token."""
```

### Provedores Implementados

| Provider | Classe | Ativação | Modelo padrão |
|---|---|---|---|
| Ollama (local) | `OllamaProvider` | `LLM_PROVIDER=ollama` | `qwen3.5:4b` |
| Google Gemini | `GeminiProvider` | `LLM_PROVIDER=google` | `gemini-2.0-flash` |

### Factory

```python
# src/llm/factory.py
def create_provider(provider_name: str, model: str) -> BaseLLMProvider:
    match provider_name:
        case "ollama": return OllamaProvider(model=model)
        case "google": return GeminiProvider(model=model)
        case _: raise ValueError(f"Provider desconhecido: {provider_name}")
```

### Variáveis de Ambiente

```bash
LLM_PROVIDER=ollama          # ou "google"
LLM_MODEL=qwen3.5:4b         # ou "gemini-2.0-flash"
OLLAMA_BASE_URL=http://localhost:11434
GEMINI_API_KEY=<chave>       # apenas para provider google
```

### Injeção no Agent Loop

O `agent_loop.py` recebe o provider via injeção de dependência — não importa diretamente de variáveis globais. Isso facilita testes unitários com provider mock.

---

## Limitação Atual: Variável Global DEFAULT_MODEL

> [!WARNING]
> Atualmente todos os agentes consomem `DEFAULT_MODEL` de `src/config.py` — uma única configuração global. Isso força um tradeoff impossível: um modelo local pequeno é inadequado para planejamento e geração de código; um modelo remoto pesado é desperdício para validação estruturada.
>
> O **ADR 007** e o **roadmap V14.1** abordam este problema com o Model Router.

---

## Alternativas Consideradas

### Alternativa A: Usar exclusivamente Google Gemini API

Usar apenas a API do Google Gemini — mais simples, sem necessidade de abstração.

**Descartado porque:**
- Sem fallback offline para o Pi 5
- Dependência de conectividade e chave de API para toda operação
- Custo de API para sessões longas pode ser proibitivo

### Alternativa B: Usar exclusivamente Ollama (local)

Usar apenas modelos locais — sem custo de API e funciona offline.

**Descartado porque:**
- Modelos locais de 4B-8B parâmetros têm qualidade insuficiente para planejamento de pesquisa científica e geração de código complexo
- Para tarefas críticas (Researcher, Developer), um modelo mais capaz é necessário

### Alternativa C: LangChain como camada de abstração

Usar LangChain para abstrair providers de forma padronizada.

**Descartado porque:**
- Dependência pesada — LangChain adicionaria ~50+ sub-dependências
- Overhead de abstração desnecessário para apenas 2 providers
- Dificulta debugging quando a abstração oculta erros de API
- Incompatível com o princípio de footprint mínimo no Pi 5

---

## Consequências

### Positivas

- **Flexibilidade:** O pesquisador pode escolher entre modo offline (Ollama) e modo cloud (Gemini) conforme necessidade e conectividade.
- **Testabilidade:** O `BaseLLMProvider` pode ser mockado nos testes sem chamar APIs reais.
- **Extensibilidade:** Novos providers (ex: Anthropic Claude, local llama.cpp) podem ser adicionados implementando `BaseLLMProvider` e registrando na factory.

### Negativas / Trade-offs

- **Variável global DEFAULT_MODEL:** A limitação atual de um único modelo para todos os agentes é o principal débito técnico desta ADR, endereçado no V14.
- **Paridade de features:** Ollama e Gemini têm schemas de tool call ligeiramente diferentes — a camada de abstração precisa normalizar essas diferenças.

---

## Revisão

Este ADR deve ser revisado quando:
- V14.1 (Model Router) for implementado — esta ADR será atualizada para refletir seleção de provider por papel
- Um novo provider for adicionado ao projeto
- A API do Google Gemini ou o protocolo do Ollama tiver breaking changes
