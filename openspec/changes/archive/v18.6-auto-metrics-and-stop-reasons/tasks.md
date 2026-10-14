# Tarefas: v18.6-auto-metrics-and-stop-reasons

**Estado (2026-10-14):** Concluída e arquivada — código mergeado em `dev` (#157). Validação no Pi 5 (unit + integration): 3596 passed, 0 falhas. Aberto só o item 5.3 (sessão `auto` real, na bateria do benchmark, com confirmação do pesquisador); registrado em `PENDENCIAS.md`. Specs consolidadas em `openspec/specs/{hypothesis-loop,vocabulary,operation-metrics,benchmark}`.
**Estado anterior (2026-10-13):** Implementada na branch `feat/v18.6-auto-metrics`: itens 1 a 4 e testes por cenário (`tests/unit/test_auto_metrics_and_stop_reasons.py`, `tests/unit/benchmark/test_stop_reasons.py`, ajustes em `tests/unit/test_hypothesis_closure.py`). `ruff` e `pytest -m unit` verdes (3495 testes); a bateria de integração (5.2) fica para o Pi, a cargo do orquestrador depois do PR.

## 0. Pré-requisitos
- [x] 0.1 Direção aprovada pelo pesquisador (2026-10-13), inclusive o schema aditivo.
- [x] 0.2 Worktree `.worktrees/feat-v18.6-auto-metrics`; spec confrontada com o código (design, cabeçalho).

## 1. Schema e configuração (aditivo)
- [x] 1.1 `Sessao.motivo_parada` ganha `hipoteses_nao_testadas`; `Metrica` ganha `origem_definicao`, `aprovada_por`, `justificativa_definicao`.
- [x] 1.2 `METRICS_MAX_PER_PLAN` em `src/config.py` e `.env.example`.

## 2. `sem_hipotese` (item 3)
- [x] 2.1 `ReviewResult.motivos`; `review_result` registra `sem_hipotese`.
- [x] 2.2 Evento `subtask_review` e retorno de `_review_subtask` levam `motivos`.
- [x] 2.3 `HypothesisClosureReader.reprovacoes_sem_hipotese`; `scripts/benchmark/interactions.py` e `report.py`.
- [x] 2.4 Testes por cenário.

## 3. `hipoteses_nao_testadas` (item 2)
- [x] 3.1 `ExplorationStop.UNTESTED_HYPOTHESES`; `_close_untested_hypotheses` fecha com ele, sem resultado de erro; evento com `motivo_parada`.
- [x] 3.2 `evaluate_resumability` recusa com mensagem própria.
- [x] 3.3 Métricas de operação (`fechada_por_hipoteses_nao_testadas`), `describe_stop_reason` no relatório e na CLI.
- [x] 3.4 Benchmark: `stop_class`, `anomalies`, seção do relatório.
- [x] 3.5 Ajustar o teste do cenário "Ciclos ociosos esgotados"; testes dos demais cenários.

## 4. Métricas definidas pelo agente (item 1)
- [x] 4.1 `MetricDecl`, `parse_metrics`, `PlanExtras.metricas`, `split_plan`.
- [x] 4.2 `ValidatorAgent.validate_plan(metric_definition=...)`, `ValidationResult.metrics_approved`.
- [x] 4.3 `apply_validated_metrics` (`src/knowledge/metric_definition.py`).
- [x] 4.4 `ExplorationSession`: `metric_definition_required`, instrução no `prompt_block`, `apply_metrics`.
- [x] 4.5 Orquestrador: passar a definição ao Validator, aplicar após a aprovação, impedir a aprovação com avisos sem `metrics_approved`.
- [x] 4.6 Laço: remover o fechamento `erro` do modo `auto` e o teste correspondente.
- [x] 4.7 Testes por cenário.

## 5. Validação
- [x] 5.1 `uv run ruff check .` e `uv run pytest -m unit -v` verdes.
- [x] 5.2 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
- [ ] 5.3 Bateria de integração no Pi (a cargo do orquestrador, depois do PR): sessão `auto` com `Metrica` candidata e `hipoteses_nao_testadas` num benchmark.
