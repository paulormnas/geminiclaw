# Tarefas: v18.9-result-records

**Estado (2026-10-22):** aprovada pelo pesquisador (#242, com `HYPOTHESIS_MIN_REPLICAS` e `HYPOTHESIS_MIN_REFUTATIONS` em 2 e 2); implementada no PR `feat/v18.9-result-records` (seções 0 a 4). Falta aplicar a migração aos bancos (com backup) e a confirmação do Arquiteto para os ADRs 015, 025 e 026 depois do merge. O `.env` do Mac e o do Pi precisam perder as linhas `VERDICT_*`, `KNOWLEDGE_SHORTCUT_MIN_VERDICT`, `DECISION_EVAL_MIN_VERDICT` e `SIM_CROSS_PROJECT_MIN_CONFIDENCE` antes de subir o código novo (a carga da configuração as recusa).

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador, com as aprovações de schema, migração e exclusão.
- [x] 0.2 Worktree `.worktrees/feat-v18.9-result-records`; spec confrontada com o código (design §1).

## 1. Registros
- [x] 1.1 `src/knowledge/result_records.py`: `compute_record` puro e tentativa válida (design §2 e §3.1).
- [x] 1.2 Schema `RegistroResultado` e arestas; porta do grafo recusa fatos escritos por agente.
- [x] 1.3 Recálculo na ingestão (`ingestion.py`), no ponto do antigo recálculo do veredito.
- [x] 1.4 Testes de "Registro de resultado mantido pelo orquestrador", "Tentativa válida" e "Nó RegistroResultado".

## 2. Regra de estado e atalhos
- [x] 2.1 `HYPOTHESIS_MIN_REPLICAS` e `HYPOTHESIS_MIN_REFUTATIONS` em `src/config.py`; erro de remoção para as variáveis antigas.
- [x] 2.2 `HypothesisCycle.sync_statuses`, `evaluate_decisions`, `_prior_support` e evento `hipotese_transicao`.
- [x] 2.3 Atalhos derivados de registros; `suggestions._variation_candidates` e `related_experience` leem registros.
- [x] 2.4 Evento `metrica_indisponivel`.
- [x] 2.5 Testes de `hypothesis-loop` e "Atalhos derivados de registros".

## 3. Curator
- [x] 3.1 Ferramentas `result_records` e `qualify_record`; remoção de `verdict_breakdown`; prompts.
- [x] 3.2 Portão de `Descoberta` por registro.
- [x] 3.3 Testes de `curator`.

## 4. Remoções e migração
- [x] 4.1 Remover `verdict.py`, `verdict_for_*`, CLI de veredito em `terminal_consult` e `scripts/verdict_lab/` (exceto `controlled/`).
- [x] 4.2 `scripts/migrate_v18_9_result_records.py` (simulação por padrão, backup e idempotência) e testes (unitário e AGE).
- [x] 4.3 `uv run ruff check`, `uv run lint-imports` e `uv run pytest -m "unit or integration"`.

## 5. Fechamento
- [~] 5.1 `tasks.md` com caixas e linha **Estado**; ADRs 015, 025 e 026 confirmados pelo Arquiteto depois do merge.
