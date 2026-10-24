# Tarefas: v18.9-cross-project-context

**Estado (2026-10-21):** especificada; aguarda aprovação do pesquisador (propriedade `Oportunidade.origem` e atualização da `similarity_queue`).

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada; `v18.9-result-records` e `v18.9-memory-evaluation` (seção 1) mergeadas; worktree própria.

## 1. Experiência relacionada
- [ ] 1.1 Semelhança de Problemas (texto + dados) e `related_experience` sobre registros.
- [ ] 1.2 Bloco `experiencia_de_problemas_semelhantes` no primeiro plano (`project_session`) e no ciclo (`exploration.py`).
- [ ] 1.3 Testes de `knowledge-semantics`.

## 2. Candidatos no ciclo
- [ ] 2.1 Integração de `structural_candidates.generate`, sugestões e `Oportunidade` com `origem = "grafo"`.
- [ ] 2.2 Testes de "Candidatos estruturais no ciclo".

## 3. Fila
- [ ] 3.1 Varredura só de duplicatas; `UPDATE` dos pendentes `relacionado` para `descartado`.
- [ ] 3.2 Testes de "Faixas de similaridade".

## 4. Fechamento
- [ ] 4.1 `ruff`, `lint-imports` e `pytest -m "unit or integration"`; `tasks.md` com **Estado**.
