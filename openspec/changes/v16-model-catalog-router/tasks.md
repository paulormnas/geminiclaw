# Tarefas: v16-model-catalog-router

## 0. Pré-requisitos
- [x] 0.1 Obter do pesquisador a aprovação da remoção de `LLM_PROVIDER`/`LLM_MODEL`/`DEFAULT_MODEL`, do padrão `self_hosted_only` e as respostas às questões em aberto do design §10. (Aprovação dada pelo usuário ao mandar iniciar a tarefa em 2026-10-06; as questões do §10 foram adiadas e o PR adota o default proposto em cada uma.)
- [x] 0.2 `uv add pyyaml` (dependência direta; hoje só transitiva).

## 1. Catálogo
- [x] 1.1 `src/llm/catalog.py`: carga com `yaml.safe_load`, esquema estrito (design §1), `catalog_hash`.
- [x] 1.2 `catalog.local.yaml`: só `modelos`, sem `id` repetido, `WARNING` com caminho e sha256; entrada no `.gitignore`.
- [x] 1.3 Regra de `https` para `openai_compatible` fora de loopback e de faixas privadas.
- [x] 1.4 `src/llm/catalog.yaml` com os modelos usados hoje (preços em `pricing.py` como referência de nomes) e as preferências aprovadas na tarefa 0.1.

## 2. Disponibilidade
- [x] 2.1 `src/llm/availability.py`: credencial/endpoint, `LLM_PROVIDER_PRIORITY` por perfil, checks em paralelo com timeout, cache por sessão.
- [x] 2.2 Health check do Google sem geração (`models.get`); Ollama confere o modelo em `/api/tags`; `openai_compatible` confere `/models` quando houver lista.
- [x] 2.3 Sanitização dos erros do health check.

## 3. Roteador
- [x] 3.1 `src/llm/routing.py`: `RoleResolution`, `resolve`, `resolve_session`, `NoEligibleModelError` com sugestão acionável.
- [x] 3.2 Pins (`provedor/modelo`), pins legados com `WARNING`, `LLM_ROUTING=strict`.
- [x] 3.3 Dica `preferred_model` validada (`src/orchestrator.py:584-585` e o despacho em `src/autonomous_loop.py`).

## 4. Integração
- [x] 4.1 Resolver no início da sessão (antes do banner) e gravar `payload["llm_routing"]`.
- [x] 4.2 `ModelRouter.get_provider(papel)` lendo o mapa da sessão; `get_provider()` → `researcher`; remover o singleton de `src/llm/factory.py` e ajustar `agent_loop.py` e `autonomous_loop.py`.
- [x] 4.3 Remover leituras de modelo em `agents/researcher`, `agents/developer`, `agents/reviewer`.
- [x] 4.4 `src/config.py`: remover `LLM_PROVIDER`, `LLM_MODEL`, `DEFAULT_MODEL`, `{PAPEL}_PROVIDER/_MODEL` fixos e a obrigatoriedade de `GEMINI_API_KEY`; novas variáveis do design §6; `WARNING` único para variáveis removidas.
- [x] 4.5 `src/cli.py`: `--model` como pin `provedor/modelo` do `researcher`; bloco do mapa no banner.
- [x] 4.6 Fallback do Google no 429 conforme decisão da questão 2 do design.
- [x] 4.7 `src/model_config.py`: remover ou reduzir a adaptador sem padrões próprios.

## 5. Testes
- [x] 5.1 Catálogo versionado válido; campo extra; provedor não registrado; duplicata; local que redeclara `id`.
- [x] 5.2 `https` obrigatório (host público) e aceito em rede privada.
- [x] 5.3 Política: chave de nuvem não basta; nenhum modelo sob a política (mensagem com sugestão).
- [x] 5.4 Disponibilidade: modelo Ollama não instalado; lista de permissão; Google sem `generate_content`; erro sanitizado.
- [x] 5.5 Roteador: requisito não atendido, alias `planner`, Validator `third_party` permitido.
- [x] 5.6 Pins: flexível com `WARNING`, estrito fatal, legados com `origem="pin_legado"`.
- [x] 5.7 Dica do plano: sem provedor (ignorada) e válida (usada).
- [x] 5.8 Payload `llm_routing` e banner sem segredos.
- [x] 5.9 Teste de política: nenhuma leitura direta de `AGENT_MODEL`/`LLM_MODEL`/`DEFAULT_MODEL`.
- [x] 5.10 Ajustar os testes existentes que patcham `LLM_PROVIDER`/`{PAPEL}_PROVIDER` (`tests/unit/test_model_router.py`, `test_llm_factory.py`, `test_config.py`, `test_v11_agent_loop.py`, `test_agent_runtime_*.py`) para usar catálogo e disponibilidade de teste.

## 6. Fechamento
- [x] 6.1 `.env.example`: novas variáveis, bloco de transição comentado, exemplo de `third_party_allowed`.
- [x] 6.2 Atualizar `openspec/changes/v18.5-model-catalog-locality` se algum nome de campo mudar na implementação.
- [x] 6.3 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 6.4 Sessão real no Pi 5 com o `.env` atualizado (mapa resolvido no banner e no payload).
- [ ] 6.5 Revisão do Analista de Segurança (design §8); revisão nos 7 eixos; PR para `dev`; ADR 017 → Aceito após o merge.
