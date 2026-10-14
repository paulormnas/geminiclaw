# Tarefas: v18.6-remove-unused-agents

**Estado (2026-10-13):** Concluída e arquivada — código mergeado em `dev` (#155). Validação no Pi 5 (`uv run pytest -m "unit or integration"`): 3549 passed, 0 falhas. Nenhum item aberto.
**Estado anterior (2026-10-13):** Implementada na branch `feat/v18.6-remove-unused-agents`: itens 1 a 4, testes por cenário (`tests/unit/test_remove_unused_agents.py`) e documentação (6.1 a 6.4). `ruff` e `pytest -m unit` verdes; a bateria de integração (5.3) ficava para o Pi.

## 0. Pré-requisitos
- [x] 0.1 Proposta aprovada; questões 5.1 e 5.2 do design decididas.
- [x] 0.2 Worktree `.worktrees/feat-v18.6-remove-unused-agents`.

## 1. Agente `reviewer`
- [x] 1.1 Remover `agents/reviewer/` e a entrada em `src/agent_runtime/definitions.py`.
- [x] 1.2 Remover `reviewer` de `AGENT_IDS`, `REQUIRED_ROLES`, `catalog.yaml`, `plan_normalizer.py`, `.env.example` e `comm_judge.POOL_ROLES`.
- [x] 1.3 `WARNING` para `REVIEWER_MODEL` definida; erro de catálogo para `papeis.reviewer` em `catalog.local.yaml` (design §3).
- [x] 1.4 Ajustar docstrings que listam papéis (`src/model_router.py:61`, `src/agent_runtime/context.py:41`).

## 2. Papéis de subtarefa
- [x] 2.1 `AGENT_IDS = ("developer", "researcher")`.
- [x] 2.2 `plan_normalizer.py`: `base` → `developer`; `reviewer`/`summarizer` não recuperáveis (design §2).
- [x] 2.3 Remover o ramo `base` de `_dispatch_subtask`.
- [x] 2.4 `src/llm/independence.py`: remover `check_dispatch`, `_UNUSED_UNTIL_DISPATCH` e a conferência de despacho de `reviewer`/`base` (e o código de `SessionRouting.dispatch_model` que só serve a eles); `JUDGE_ROLES = ("validator",)`, `JUDGED_ROLES = ("developer",)`; ajustar os testes de `tests/unit/llm/test_judge_independence.py`.

## 3. Telemetria e benchmark
- [x] 3.1 `review_result` com papel `validator` e `funcao = "revisao_subtarefa"`; evento `subtask_review` com `agent_id = "validator"`.
- [x] 3.2 `communication.py` e `report.py`: chave `revisao_subtarefa`, leitura dos dois rótulos.

## 4. Código morto
- [x] 4.1 Remover o atalho `agent_tasks` de `Orchestrator.handle_request` e os testes dele.
- [x] 4.2 Remover o valor `end_only` de `REVIEW_MODE` (valor inválido falha na inicialização).

## 5. Testes
- [x] 5.1 Um teste por cenário da spec.
- [x] 5.2 Ajustar os testes que citam `reviewer` e `agent_tasks`.
- [x] 5.3 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes. `ruff` e a suíte unitária (3448 testes) na branch; `unit or integration` no Pi 5 após o merge: 3549 passed, 0 falhas.

## 6. Documentação
- [x] 6.1 ADR 020 §1 e §4: juízes = `validator`, julgados = `developer`; remover os pontos de `reviewer`/`base`.
- [x] 6.2 Mudança arquivada `v18.6-validator-independence` e `openspec/specs/llm-providers/spec.md`: retirar as referências a `reviewer`/`base` dos requisitos (pontos de conferência de despacho, `JudgeIndependenceGuard.check_dispatch`, `_UNUSED_UNTIL_DISPATCH`).
- [x] 6.3 Nota no ADR 007: o papel `reviewer` foi removido do código.
- [x] 6.4 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
