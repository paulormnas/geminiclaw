# Tarefas: v18.10-web-settings

**Estado (2026-10-24):** especificada; aguarda aprovação do pesquisador.

## 0. Pré-requisitos
- [ ] 0.1 `v18.10-web-skeleton` mergeada; aprovação da lista fechada e da gravação de chaves pela web; conferir nomes e validações contra `src/config.py`.

## 1. Backend
- [ ] 1.1 Carga da sobreposição em `src/config.py` (lista fechada, falha com nome proibido, antes do filtro de `SESSION_ENV_DENYLIST`); `RESEARCHER_ENV_FILE` em `.env.example`; `.gitignore`. Testes: sobreposição vale, nome proibido.
- [ ] 1.2 `src/web/settings.py` (validação reutilizando `src/config.py`, gravação atômica `0600` sob trava) e `routes/settings.py`. Testes de todos os cenários; regenerar o OpenAPI.
- [ ] 1.3 `src/llm/model_discovery.py` (um adaptador por provedor, cache, cruzamento com o catálogo), `GET /api/models`, `geminiclaw models list`, `MODEL_DISCOVERY_CACHE_SECONDS`. Testes com provedores simulados (sem rede): cruzamento, provedor sem chave, cache, Validator.

## 2. Frontend
- [ ] 2.1 Página de configurações (seletor de modelo com a lista do provedor e o estado de cada modelo), diálogo de senha, chaves mascaradas. Testes com MSW.

## 3. Validação final
- [ ] 3.1 `ruff`, `lint-imports`, `pytest -m "unit or integration"`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 3.2 Manual no Mac: mudar `SESSION_MAX_MINUTES`, iniciar pesquisa pela CLI e conferir o limite novo.
- [ ] 3.3 Parecer do Analista de Segurança no PR; revisão nos 7 eixos; PR pelo GitHub App; linha **Estado**.
