# Tarefas: v16-pipeline-robustness

## 0. Pré-requisitos
- [x] 0.1 Questões do design §10 respondidas em 2026-10-05 (1 e 2 mantidas como especificadas).
- [ ] 0.2 Worktree `.worktrees/feat-v16-pipeline-robustness`; um PR por bloco (1, 2, 3, 4, 5)
  ou um PR único, a critério do pesquisador (blocos 1 a 5 são independentes entre si, exceto 5
  depende de 4 para o evento de limite).

## 1. Normalizador de plano
- [ ] 1.1 `src/plan_normalizer.py`: `PlanRepair`, `NormalizedPlan`, `normalize_plan` (design §1.1).
- [ ] 1.2 Reparos da tabela §1.2, cada um com teste de entrada → saída e de registro do reparo.
- [ ] 1.3 Casos que não podem ser reparados (§1.2, último parágrafo) caem em `unrecoverable`.
- [ ] 1.4 `Orchestrator._run_planning_loop`: normaliza após `extract_json`; evento `plan_normalized`.
- [ ] 1.5 Assinatura de reprovação; `PlanningStalled` após `PLAN_REJECTION_STALL_LIMIT` reprovações
  determinísticas idênticas; Validator LLM consultivo com `approved_with_warnings` (design §1.3).
- [ ] 1.6 Feedback da regra do limiar com as subtarefas afetadas (§1.3, item 3).
- [ ] 1.7 Testes: plano em envelope; `depends_on` como string; nomes duplicados; dependência com
  grafia errada; ciclo não reparado; laço de reprovação determinística termina em erro; LLM
  consultivo aprova com avisos na segunda reprovação idêntica; `PLAN_NORMALIZER_ENABLED=false`.

## 2. Comparador de artefatos e revisão
- [ ] 2.1 `src/artifact_match.py`: `ArtifactResolution`, `resolve_artifacts` (design §2.1 e §2.2),
  com rejeição de caminhos fora da pasta da sessão.
- [ ] 2.2 `ValidatorAgent.review_result`: usar `resolve_artifacts`; mensagem de falha com o que
  existe em disco (§3, item 1).
- [ ] 2.3 Camada `extension` e `ARTIFACT_MATCH_MODE` (§2.2); depende da questão 2.
- [ ] 2.4 `_metric_criteria`; critério sem métrica nomeada segue para o revisor LLM (§3, item 2).
- [ ] 2.5 `metrics.json` da própria subtarefa e de dependências (§3, item 3); todos os critérios
  mapeáveis avaliados (§3, item 4).
- [ ] 2.6 `build_artifact_evidence` usa as resoluções (§3, item 5).
- [ ] 2.7 `SubtaskOutput.artifact_aliases` e `_build_context_prefix` com o mapa (§2.3); retentativa
  usa o mesmo mapa.
- [ ] 2.8 Evento `subtask_review` com `attempt`, `resolved_artifacts`, `signature`.
- [ ] 2.9 Testes: `iris_*.png` no lugar de `eda_*.png` aprova com `name_mismatch`; menos arquivos
  que o esperado reprova; ".py" nunca casa por extensão; "ao menos 3 gráficos" não exige
  `metrics.json`; `metrics.json` de outra subtarefa não vale sem dependência; dois critérios,
  um falha; `strict` reproduz o comportamento antigo; travessia de caminho rejeitada.

## 3. Relatório estruturado
- [ ] 3.1 `src/report/report_model.py`: dataclasses do design §6.1, `build_report_data`,
  `parse_narrative`, `render_report_markdown`.
- [ ] 3.2 Evento `sandbox_run` em `src/skills/code/` (§6.3) e contagem de execuções por papel.
- [ ] 3.3 `agents/summarizer/agent.py`: sem ferramentas; instrução pede só o JSON de `Narrative`;
  remover "Containers Utilizados" e a estrutura de Markdown da instrução.
- [ ] 3.4 `AutonomousLoop._synthesize_results`: montar `ReportData`, chamar o Summarizer, uma
  tentativa de reparo, fallback `narrativa_indisponivel`, gravar `relatorio_final.md` e
  `report_data.json`.
- [ ] 3.5 Testes: tabela de resultados idêntica aos `metrics.json`; metadados idênticos à
  telemetria simulada; narrativa inválida duas vezes marca `narrativa_indisponivel` sem
  inventar texto; nenhum "Container" no relatório; conversores (`docx`, `html`, `latex`) seguem
  funcionando sobre o Markdown novo.

## 4. Disjuntor de progresso
- [ ] 4.1 `CycleProgress` e assinatura de erro normalizada (§4).
- [ ] 4.2 `_run_complex_path`: contagem de ciclos sem progresso e `CIRCUIT_BREAKER_STALL_CYCLES`;
  evento `circuit_breaker` ampliado.
- [ ] 4.3 Atualizar `tests/unit/test_circuit_breaker.py` (o texto do módulo descreve o
  comportamento antigo): erro diferente entre ciclos conta como progresso; dois ciclos idênticos
  ainda encerram; um ciclo idêntico não encerra com o padrão 2.

## 5. Limites de execução
- [ ] 5.1 `StopReason.RUNS`; `AgentRunLimitReached`; contadores `planning` e `execution` com o
  rótulo `run_kind` (§5.1).
- [ ] 5.2 Piso derivado do plano aprovado; `MAX_PLANNING_RUNS_PER_SESSION`.
- [ ] 5.3 `AutonomousLoop` captura o limite e fecha com consolidação (§5.2); evento `limit_reached`.
- [ ] 5.4 Banner e `_check_operational_thresholds` com os dois contadores.
- [ ] 5.5 Atualizar o teste do limite em `tests/unit/test_circuit_breaker.py` (hoje espera
  `RuntimeError`); novos testes: planejamento não consome o limite de execução; limite cresce
  com o plano; sessão fecha com `motivo_parada="limite_execucoes"`.

## 6. Fechamento
- [ ] 6.1 Variáveis do design §7 em `src/config.py` e `.env.example`; teste de `config` para
  cada padrão.
- [ ] 6.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v` (nenhum teste chama
  provedor pago).
- [ ] 6.3 Sessão real da tarefa Iris no Pi 5, **uma execução**, com o mapa de modelos que antes
  falhou (sem repetir a matriz): anexar ao PR o resumo de `plan_normalized`, `subtask_review` e
  `circuit_breaker`, e o `report_data.json`. Crédito pago só conforme a regra de gasto do
  pesquisador.
- [ ] 6.4 Revisão do Analista de Segurança (comparador e `sandbox_run`); revisão nos 7 eixos; PR
  para `dev`; após o merge, arquivar a mudança e consolidar `specs/pipeline-robustness/spec.md`.
