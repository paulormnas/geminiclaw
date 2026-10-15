# Tarefas: v18.7-exploration-metrics

**Estado (2026-10-15):** não iniciada.

## 0. Pré-requisitos
- [ ] 0.1 Mudança aprovada pelo pesquisador (sem aprovação de schema).
- [ ] 0.2 `v18.7-hypothesis-linking` e `v18.7-subtask-contract` mergeadas (ou os blocos `ligacao` e `contrato` implementados com o estado `indisponivel` até elas entrarem); confrontar os nomes dos campos do evento `hypothesis_cycle` e de `SubtaskContract.sha256()` com o código.
- [ ] 0.3 Worktree `.worktrees/feat-v18.7-exploration-metrics`; spec confrontada com o código (design §1).

## 1. Configuração
- [ ] 1.1 `OPERATION_METRICS_LIST_MAX_ITEMS` em `src/config.py` e `.env.example`.

## 2. Contrato por tentativa
- [ ] 2.1 Evento `subtask_attempt` em cada tentativa do Developer (`src/autonomous_loop.py:1373-1393`), uma vez por tentativa, com `recorte_sha256` lido do `AgentContext` (`null` sem `v18.7-agent-system-prompts`).
- [ ] 2.2 `contrato_sha256` em `subtask_review` (`src/autonomous_loop.py:2401-2425`); comparação e evento `contrato_divergente`.
- [ ] 2.3 Testes do requisito "Hash e tokens do contrato por tentativa" (cenários de evento, laço de ferramentas, divergência, sem contrato, hash do recorte, sem texto).

## 3. Grupo `exploracao`
- [ ] 3.1 `GROUPS` com `exploracao`, `VERSION = 2`; leitura de `versao = 1`.
- [ ] 3.2 `ExplorationLinkingReader` (grafo e `hypothesis_cycle`), `ExplorationStopReader` (eventos de `v18.7-exploration-limits`), `ContractReader` (eventos e `token_usage`), cada um com `indisponivel` e o nome da mudança produtora quando ela falta.
- [ ] 3.3 Remover `reprovacoes_sem_hipotese` de `HypothesisClosureReader` e a linha do relatório.
- [ ] 3.4 Linha "Exploração" em `render_operation_metrics_section`, com a lista das retiradas por similaridade.
- [ ] 3.5 Testes dos requisitos "Métricas de operação registradas por sessão", "Motivos de parada e de reprovação nas métricas de operação", "Contadores de ligação da exploração", "Contadores da parada e das restrições" e da fração da entrada.

## 4. Benchmark
- [ ] 4.1 `scripts/benchmark/interactions.py`: `subtask_attempts`, contagem de `contrato_divergente`, motivos genéricos.
- [ ] 4.2 `scripts/benchmark/run_benchmark.py`: grupo `exploracao` no resultado; aviso de placar `contrato_divergente`.
- [ ] 4.3 `scripts/benchmark/report.py`: `render_exploration` e tokens do contrato por combinação; `n/d` para resultados antigos.
- [ ] 4.4 Testes de `specs/benchmark/spec.md`.

## 5. Validação
- [ ] 5.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 5.2 `tasks.md` com caixas e linha **Estado** atualizadas no PR; ADRs 021 (§8.4) e 022 (§6.3, §7) confirmados pelo Arquiteto depois do merge.
- [ ] 5.3 Na bateria da V18.7 (com confirmação do pesquisador): relatório com a tabela de exploração e os tokens do contrato por combinação, comparável à V18.6 conforme a "Revisão" do ADR 021.
