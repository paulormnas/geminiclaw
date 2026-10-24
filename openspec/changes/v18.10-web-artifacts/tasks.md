# Tarefas: v18.10-web-artifacts

**Estado (2026-10-24):** especificada; aguarda aprovação do pesquisador.

## 0. Pré-requisitos
- [ ] 0.1 `v18.10-web-skeleton` mergeada; conferir `resolve_session_dir` e a ligação `Sessao`↔pasta nas sessões do `geminiclaw_bench` e de `outputs/` do Mac (só leitura).

## 1. Backend
- [ ] 1.1 `artifact_files.py` (resolução confinada, tabela de tipos, listagem limitada, pré-visualização) e variáveis `WEB_ARTIFACT_*` em `src/config.py` e `.env.example`.
- [ ] 1.2 `routes/artifacts.py`. Testes de unidade de todos os cenários (pasta temporária, links simbólicos reais, `InMemoryGraphStore`); regenerar o OpenAPI.

## 2. Frontend
- [ ] 2.1 `pnpm --dir frontend add react-markdown`; páginas de sessões, árvore e visualizador. Testes dos cenários com MSW.

## 3. Validação final
- [ ] 3.1 `ruff`, `lint-imports`, `pytest -m "unit or integration"`; `pnpm --dir frontend lint typecheck test build`.
- [ ] 3.2 Manual no Mac: abrir relatório, figura, CSV e HTML de uma sessão de `outputs/`.
- [ ] 3.3 Parecer do Analista de Segurança no PR; revisão nos 7 eixos; PR pelo GitHub App; linha **Estado**.
