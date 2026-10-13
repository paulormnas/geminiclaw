# Tarefas: v18.6-remove-unused-agents

**Estado (2026-10-13):** Proposta, aguardando aprovação do pesquisador (exclusão de `agents/reviewer/` e questões do design §5).

## 0. Pré-requisitos
- [ ] 0.1 Proposta aprovada; questões 5.1 e 5.2 do design decididas.
- [ ] 0.2 Worktree `.worktrees/feat-v18.6-remove-unused-agents`.

## 1. Agente `reviewer`
- [ ] 1.1 Remover `agents/reviewer/` e a entrada em `src/agent_runtime/definitions.py`.
- [ ] 1.2 Remover `reviewer` de `AGENT_IDS`, `REQUIRED_ROLES`, `catalog.yaml`, `plan_normalizer.py`, `.env.example` e `comm_judge.POOL_ROLES`.
- [ ] 1.3 `WARNING` para `REVIEWER_MODEL` definida; erro de catálogo para `papeis.reviewer` em `catalog.local.yaml` (design §3).
- [ ] 1.4 Ajustar docstrings que listam papéis (`src/model_router.py:61`, `src/agent_runtime/context.py:41`).

## 2. Papéis de subtarefa
- [ ] 2.1 `AGENT_IDS = ("developer", "researcher")`.
- [ ] 2.2 `plan_normalizer.py`: `base` → `developer`; `reviewer`/`summarizer` não recuperáveis (design §2).
- [ ] 2.3 Remover o ramo `base` de `_dispatch_subtask`.

## 3. Telemetria e benchmark
- [ ] 3.1 `review_result` com papel `validator` e `funcao = "revisao_subtarefa"`; evento `subtask_review` com `agent_id = "validator"`.
- [ ] 3.2 `communication.py` e `report.py`: chave `revisao_subtarefa`, leitura dos dois rótulos.

## 4. Código morto
- [ ] 4.1 Remover o atalho `agent_tasks` de `Orchestrator.handle_request` e os testes dele.
- [ ] 4.2 Remover o valor `end_only` de `REVIEW_MODE` (valor inválido falha na inicialização).

## 5. Testes
- [ ] 5.1 Um teste por cenário da spec.
- [ ] 5.2 Ajustar os testes que citam `reviewer` e `agent_tasks`.
- [ ] 5.3 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes (integração no Pi).

## 6. Documentação
- [ ] 6.1 ADR 020 §1 e §4: juízes = `validator`, julgados = `developer`; remover os pontos de `reviewer`/`base`.
- [ ] 6.2 `v18.6-validator-independence`: retirar as tarefas 6.1/6.2 (movidas para cá) e as referências a `reviewer`/`base`.
- [ ] 6.3 Nota no ADR 007: o papel `reviewer` foi removido do código.
- [ ] 6.4 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
