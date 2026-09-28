# Tarefas: v16-provider-registry

## 1. Registro
- [x] 1.1 Criar `src/llm/registry.py` com `ProviderSettings`, `register_provider`, `create_provider`, `available_providers`.
- [x] 1.2 Registrar `ollama` (alias `local`) e `google` em `src/llm/providers/__init__.py` com imports preguiçosos.
- [x] 1.3 Testes unitários: registro, alias, nome desconhecido, provedor com pacote opcional ausente.

## 2. Consumidores
- [x] 2.1 Reescrever `src/llm/factory.py::get_provider` sobre o registro (mantendo singleton).
- [x] 2.2 Reescrever `ModelRouter.get_provider` sobre o registro (mantendo cache).
- [x] 2.3 Ajustar testes existentes que fazem patch dos imports antigos.

## 3. Provedor OpenAI-compatível
- [x] 3.1 Criar `src/llm/providers/openai_compatible.py` (`generate`, `generate_stream`, `health_check`, `model_name`).
- [x] 3.2 Adicionar `OPENAI_BASE_URL` e `OPENAI_API_KEY` em `src/config.py` e `.env.example` (mapeamento explícito para o provedor `openai_compatible`, ver `design.md`).
- [x] 3.3 Testes com `respx`: texto simples, tool call, argumentos inválidos, 429 com retentativa, streaming SSE, health check.

## 4. Remoção do ADK
- [x] 4.1 Remover `google-adk` do `pyproject.toml`; `uv lock`.
- [x] 4.2 Atualizar docstrings e `.agents/rules/architect.md` ("Agentes ADK" → "Agentes").
- [x] 4.3 Verificar que nenhum import de `google.adk` existe (`grep`).

## 5. Fechamento
- [x] 5.1 `uv run ruff check .` e `uv run pytest -m "unit or integration"`.
- [ ] 5.2 Revisão nos 7 eixos; PR para `dev`.
