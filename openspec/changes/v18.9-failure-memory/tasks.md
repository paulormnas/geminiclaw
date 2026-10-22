# Tarefas: v18.9-failure-memory

**Estado (2026-10-21):** especificada; aguarda aprovação do pesquisador.

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada; worktree `.worktrees/feat-v18.9-failure-memory`; spec confrontada com o código.

## 1. Implementação
- [ ] 1.1 `src/knowledge/failure_memory.py` (itens, escopos e correção conhecida).
- [ ] 1.2 `FAILURE_MEMORY_MAX_CHARS` em `src/config.py` e `.env.example`.
- [ ] 1.3 Bloco no prompt do Developer e evento `memoria_falhas_aplicada`.
- [ ] 1.4 Testes dos quatro cenários.

## 2. Fechamento
- [ ] 2.1 `ruff`, `lint-imports` e `pytest -m "unit or integration"`; `tasks.md` com **Estado**.
