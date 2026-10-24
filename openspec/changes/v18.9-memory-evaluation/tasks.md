# Tarefas: v18.9-memory-evaluation

**Estado (2026-10-24):** aprovada pelo pesquisador em 2026-10-24. Implementadas as seções 1–3 (candidatos em `src/knowledge/structural_candidates.py`, porque `candidates.py` já é a fila de similaridade; replay, métricas e famílias em `scripts/memory_eval/`); pré-registro do E0 em `docs/avaliacao-memoria/`. Falta rodar o E0 e o relatório (4.2), E1 e E2 (4.3, 4.4) e o fechamento.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada; `v18.9-result-records` mergeada; worktree `.worktrees/feat-v18.9-memory-evaluation`.

## 1. Candidatos
- [x] 1.1 `src/knowledge/structural_candidates.py` e variáveis `CANDIDATE_*`.
- [x] 1.2 Testes de "Candidatos estruturais sem LLM".

## 2. Replay e métricas
- [x] 2.1 `scripts/memory_eval/replay.py` (cortes, rótulos, AUC, linhas de base, bootstrap).
- [x] 2.2 `scripts/memory_eval/metrics.py`.
- [x] 2.3 Testes de "Replay com AUC e linhas de base" e "Métricas do núcleo com origem declarada".
- [x] 2.4 Teste de fumaça: substituído pelo corpus real de 21 sessões (`geminiclaw_bench`), que o E0 usa de fato.

## 3. Famílias
- [x] 3.1 `scripts/memory_eval/families.py` sobre `scripts/verdict_lab/controlled/`.
- [x] 3.2 Teste de "Famílias de Problemas relacionados".

## 4. Pré-registro e rodadas (cada uma com confirmação do pesquisador)
- [x] 4.1 Corpus do E0: as 21 sessões reais do benchmark (opção (a), sem famílias do gerador; `families.py` fica pronto para ampliar).
- [ ] 4.2 Pré-registro do E0, construção do corpus e relatório.
- [ ] 4.3 Pré-registro e rodada do E1 (com `v18.9-failure-memory`).
- [ ] 4.4 Pré-registro e rodada do E2 (com `v18.9-cross-project-context`).

## 5. Fechamento
- [ ] 5.1 `tasks.md` com **Estado**; ADR 026 confirmado pelo Arquiteto.
