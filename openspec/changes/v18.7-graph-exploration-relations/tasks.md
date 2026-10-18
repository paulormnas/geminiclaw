# Tarefas: v18.7-graph-exploration-relations

**Estado (2026-10-17):** implementada e mergeada em `dev` (#170). A tarefa 4.3 (roteiro do Pi) foi coberta pelas suítes de integração rodadas no Pi nas etapas seguintes (4405 passed na V18.7). Falta só o arquivamento.

**Registros da implementação:**
- Questão 3 do design §9 (ciclos em `DERIVADA_DE`): adotada a proposta (só se recusa o laço para o próprio nó).
- Leitores de `Hipotese.origem` (2.4): `hypothesis_cycle.py` (compara com `pesquisador` e repassa o valor) não assume quatro valores; nenhum precisa de mudança.
- O planejador do `graph edit` (`change_proposals._plan_update_node`) deixou de aplicar a regra "como agente" a `Hipotese`: sem isso o pesquisador não conseguiria reabrir, pela CLI confirmada, uma hipótese que ele abandonou.
- Nenhuma ferramenta de escrita do Curator altera `Hipotese.status`; o cenário "Ferramenta do Curator" é coberto com o ator de agente do Curator no grafo.

## 0. Pré-requisitos
- [x] 0.1 Aprovação explícita do pesquisador para a mudança de schema do grafo (proposal, "Aprovações necessárias").
- [x] 0.2 Questões do design §9 respondidas pelo pesquisador (ou propostas adotadas e listadas no PR).
- [x] 0.3 Revisar esta mudança contra o código atual (`src/knowledge/schema.py`, `src/knowledge/validation.py`) e registrar divergências no PR.
- [x] 0.4 Worktree `.worktrees/feat-v18.7-graph-exploration-relations`.

## 1. Papel do experimento
- [x] 1.1 `Experimento.papel` com enum e constante `PAPEIS_EXPERIMENTO` em `src/knowledge/schema.py`.
- [x] 1.2 `experiment_role` em `src/knowledge/exploration_reads.py`.
- [x] 1.3 Testes: "Papel válido", "Papel inválido", "Experimento antigo sem papel".

## 2. Hipótese do sistema e autor do abandono
- [x] 2.1 `origem = "sistema"`, `chave_estruturada`, `referencia_fixada`, `abandonada_por`, `motivo_abandono` no schema de `Hipotese`.
- [x] 2.2 Regra condicional de `origem = "sistema"`, forma de `referencia_fixada` e `IMMUTABLE_LABEL_FIELDS` em `src/knowledge/validation.py` (design §2.2).
- [x] 2.3 Autoridade sobre `abandonada_por = "pesquisador"` e sobre o `status` dessas hipóteses (design §2.3).
- [x] 2.4 Levantar os leitores de `Hipotese.origem` (Curator, `graph-cli`, relatório, `suggestions.py`) e conferir que aceitam `sistema`; registrar a lista no PR.
- [x] 2.5 `abandoned_by(node, audit_history)` (trilha de auditoria; `WARNING` nas inconsistências) e `structured_key` em `src/knowledge/exploration_reads.py`.
- [x] 2.6 Validação do padrão `^[A-Za-z0-9._-]{1,128}$` em cada componente de `chave_estruturada`. Testes: os seis cenários de "Hipótese de origem sistema com chave e referência fixadas" (inclusive "Chave com componente inválido") e os seis de "Autor do abandono" ("Hipótese abandonada antiga com rejeição do pesquisador" e "... sem nota de rejeição", pela trilha de auditoria decidida em 2026-10-15, e "Abandono pelo agente não bloqueia").
- [x] 2.7 Testes dos cinco cenários de "Autoridade sobre o abandono em todos os caminhos de escrita": `KnowledgeService`, ingestão, ferramentas do Curator, `graph edit` e `Actor` declarado pelo LLM ignorado (parecer de segurança, item a).

## 3. Relações
- [x] 3.1 `PREPARA`, `REFERENCIA_DE` e destino `Hipotese` em `DERIVADA_DE` (design §3); recusa do laço em `DERIVADA_DE`.
- [x] 3.2 Testes: cenários de "Relação PREPARA", "Relação REFERENCIA_DE" (inclusive "Referência não entra no veredito") e "Hipótese derivada de hipótese".

## 4. Migração
- [x] 4.1 Confirmar que `scripts/migrate_v17_knowledge.py` cria os rótulos sem mudança de código.
- [x] 4.2 Teste de integração com AGE real: "Grafo anterior à V18.7" (inclui `read_query` pelo `knowledge_reader` e a recusa de escrita por esse papel, parecer de segurança, item c).
- [x] 4.3 Acrescentar a reexecução da migração ao roteiro de preparação do Pi (`.agents/workflows/run_project.md` ou o roteiro da bateria), sem executá-la no Pi sem confirmação do pesquisador.

## 5. Construtores compartilhados de teste
- [x] 5.1 `tests/support/exploration_graph.py` com `problema` por tipo de objetivo, `hipotese` (inclusive `origem = "sistema"` e `abandonada_por`), `experimento` com `papel`, `resultado` e `referencia` (design §5.1), sobre `HypothesisWorld` e `CuratorGraph`, sem duplicá-los.
- [x] 5.2 Os testes desta mudança usam esses construtores; teste próprio de cada construtor (nó e arestas esperados, `Actor` usado).
- [x] 5.3 Registrar no PR que `v18.7-hypothesis-linking`, `v18.7-exploration-limits`, `v18.7-exploration-metrics` e `v18.7-subtask-contract` reutilizam o módulo.

## 6. Validação
- [x] 6.1 `uv run ruff check .` sem erros novos.
- [x] 6.2 `uv run pytest -m "unit or integration" -v` verde, sem regressão em `tests/unit/knowledge/test_schema.py`, `test_validation.py` e `test_graph_store_inmemory.py`.
- [x] 6.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
