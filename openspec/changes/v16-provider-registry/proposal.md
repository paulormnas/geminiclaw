# Proposta: Registro Único de Provedores LLM

**ID:** `v16-provider-registry` · **Versão:** V16 · **Capacidade:** `llm-providers`
**ADRs de origem:** [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) §1, §2, §4, §5

## Por quê

A seleção de provedor LLM está duplicada em dois blocos `if/elif` independentes
(`src/llm/factory.py::get_provider` e `src/model_router.py::ModelRouter.get_provider`), e só
existem dois provedores (Google e Ollama). Adicionar um provedor exige editar os dois pontos.
O pacote `google-adk` está declarado no extra `google` do `pyproject.toml`, mas nenhum arquivo
o importa. O projeto deve ser agnóstico a provedor.

## O que muda

- **Novo:** registro único de provedores (`src/llm/registry.py`), em que cada provedor se
  registra por nome com uma fábrica.
- **Modificado:** `get_provider()` e `ModelRouter.get_provider()` passam a consultar o
  registro; os blocos `if/elif` são removidos.
- **Novo:** provedor `openai_compatible` (`src/llm/providers/openai_compatible.py`), que fala o
  protocolo `/v1/chat/completions` com tool calling — cobre llama.cpp server, vLLM, LM Studio e
  serviços hospedados compatíveis.
- **Removido:** `google-adk` do `pyproject.toml` (o extra `google` mantém só `google-genai`).
- **Modificado:** referências textuais a "Google ADK" em docstrings e na regra
  `.agents/rules/architect.md` passam a "camada de provedores própria".
- **Fora do escopo:** provedor nativo Anthropic (pode ser acrescentado depois pelo mesmo
  registro); embeddings (mudança `v16-local-embeddings`); remoção do Gemini CLI na busca do
  Researcher (mudança `v16-in-process-agents`).

## Impacto

- **Código:** `src/llm/factory.py`, `src/model_router.py`, `src/model_config.py`,
  `src/llm/providers/`, `src/config.py`, `pyproject.toml`, `uv.lock`, `.env.example`.
- **Contratos:** nenhum contrato de IPC muda. A interface `LLMProvider` permanece.
- **Compatibilidade:** valores atuais de `LLM_PROVIDER` (`google`, `ollama`, `local`) continuam
  válidos. `local` vira alias de `ollama` no registro.
- **Testes afetados:** testes que fazem patch dos imports internos de `factory`/`model_router`.

## Aprovações necessárias

Nenhuma alteração de schema, Dockerfile ou `docker-compose.yml`. A remoção de dependência do
`pyproject.toml` é coberta por esta proposta aprovada.
