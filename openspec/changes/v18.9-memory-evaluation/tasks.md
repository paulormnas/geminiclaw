# Tarefas: v18.9-memory-evaluation

**Estado (2026-10-21):** especificada; aguarda aprovação do pesquisador. O histórico atual não basta para o E0 (design §1).

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada; `v18.9-result-records` mergeada; worktree `.worktrees/feat-v18.9-memory-evaluation`.

## 1. Candidatos
- [ ] 1.1 `src/knowledge/candidates.py` e variáveis `CANDIDATE_*`.
- [ ] 1.2 Testes de "Candidatos estruturais sem LLM".

## 2. Replay e métricas
- [ ] 2.1 `scripts/memory_eval/replay.py` (cortes, rótulos, AUC, linhas de base, bootstrap).
- [ ] 2.2 `scripts/memory_eval/metrics.py`.
- [ ] 2.3 Testes de "Replay com AUC e linhas de base" e "Métricas do núcleo com origem declarada".
- [ ] 2.4 Teste de fumaça sobre os 8 grafos úteis de `~/bench/`, sem relatar AUC como evidência.

## 3. Famílias
- [ ] 3.1 `scripts/memory_eval/families.py` sobre `scripts/verdict_lab/controlled/`.
- [ ] 3.2 Teste de "Famílias de Problemas relacionados".

## 4. Pré-registro e rodadas (cada uma com confirmação do pesquisador)
- [ ] 4.1 Decisão do corpus do E0 (design §7).
- [ ] 4.2 Pré-registro do E0, construção do corpus e relatório.
- [ ] 4.3 Pré-registro e rodada do E1 (com `v18.9-failure-memory`).
- [ ] 4.4 Pré-registro e rodada do E2 (com `v18.9-cross-project-context`).

## 5. Fechamento
- [ ] 5.1 `tasks.md` com **Estado**; ADR 026 confirmado pelo Arquiteto.
