# Tarefas: v18.9-failure-memory

**Estado (2026-10-22):** aprovada pelo pesquisador (#242); implementada no PR `feat/v18.9-failure-memory` (seções 0 a 2). Falta a confirmação do Arquiteto para o ADR 026 depois do merge.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada; worktree `.worktrees/feat-v18.9-failure-memory`; spec confrontada com o código.

## 1. Implementação
- [x] 1.1 `src/knowledge/failure_memory.py` (itens, escopos e correção conhecida).
- [x] 1.2 `FAILURE_MEMORY_MAX_CHARS` em `src/config.py` e `.env.example`.
- [x] 1.3 Bloco no prompt do Developer e evento `memoria_falhas_aplicada`.
- [x] 1.4 Testes dos quatro cenários.

## 2. Fechamento
- [x] 2.1 `ruff`, `lint-imports` e `pytest -m "unit or integration"`; `tasks.md` com **Estado**.
