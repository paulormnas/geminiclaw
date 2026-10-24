# Tarefas: v18.9-cross-project-context

**Estado (2026-10-24):** aprovada pelo pesquisador (esquema e `similarity_queue` incluídos). Implementada no PR `feat/v18.9-cross-project-context`: semelhança de Problemas, `related_experience` sobre registros, bloco no plano, candidatos no ciclo (`CROSS_PROJECT_CANDIDATES=false`, porque a regra do E0 não foi cumprida) e fila só de duplicatas. Falta aplicar `scripts/migrate_v18_9_similarity_queue.py` nos bancos (com a confirmação do pesquisador) e a confirmação do Arquiteto.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada; `v18.9-result-records` e `v18.9-memory-evaluation` (seção 1) mergeadas; worktree própria.

## 1. Experiência relacionada
- [x] 1.1 Semelhança de Problemas (texto + dados) e `related_experience` sobre registros.
- [x] 1.2 Bloco `experiencia_de_problemas_semelhantes` no primeiro plano (`project_session`) e no ciclo (`exploration.py`).
- [x] 1.3 Testes de `knowledge-semantics`.

## 2. Candidatos no ciclo
- [x] 2.1 Integração de `structural_candidates.generate`, sugestões e `Oportunidade` com `origem = "grafo"`.
- [x] 2.2 Testes de "Candidatos estruturais no ciclo".

## 3. Fila
- [x] 3.1 Varredura só de duplicatas; `UPDATE` dos pendentes `relacionado` para `descartado`.
- [x] 3.2 Testes de "Faixas de similaridade".

## 4. Fechamento
- [x] 4.1 `ruff`, `lint-imports` e `pytest -m "unit or integration"`; `tasks.md` com **Estado**.
