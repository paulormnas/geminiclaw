# Tarefas: v16-agent-communication-eval

## 0. Pré-requisitos
- [ ] 0.1 `v16-pipeline-robustness` mergeada (comparador, eventos `plan_normalized`, `sandbox_run`,
  `subtask_review` com `attempt`/`signature`/`resolved_artifacts`).
- [x] 0.2 Questões do design §9 aceitas em 2026-10-05; modelo e teto do juiz definidos na execução.
- [ ] 0.3 Worktree `.worktrees/feat-v16-agent-communication-eval`.

## 1. Leitura de eventos
- [ ] 1.1 `scripts/benchmark/communication.py`: carregar eventos e plano da sessão (reuso de
  `interactions.collect_session`), com falha explícita se faltar o evento esperado.
- [ ] 1.2 Agrupar por alvo e ordenar (design §4.1).

## 2. Verdade determinística
- [ ] 2.1 `SubtaskTruth`/`TruthCheck` e `compute_truth` (design §2).
- [ ] 2.2 Regra de artefatos sobrescritos por mtime.
- [ ] 2.3 Testes (`tmp_path`): artefato presente e métrica ok → `fulfilled`; artefato ausente →
  `unfulfilled`; só critérios qualitativos → `indeterminate`; `exit_code` 0 sozinho →
  `indeterminate`; artefato renomeado (`iris_*.png`) → `fulfilled`.

## 3. Veredito do revisor e resolução
- [ ] 3.1 Matriz de confusão e taxas (design §3), com `null` para denominador zero.
- [ ] 3.2 Taxa de resolução, tentativas até resolver, `unresolved_tail` (§4.2).
- [ ] 3.3 Detecção de laços por assinatura, Validator e revisor separados (§4.3).
- [ ] 3.4 Contagem de `plan_normalized` por modelo do Researcher (§4.4).
- [ ] 3.5 Testes com sequências sintéticas: falso reprovado, falso aprovado, laço de 3 e de 2,
  reprovação seguida de aprovação, reprovação sem evento seguinte.

## 4. Juiz LLM
- [ ] 4.1 `redact_for_judge` (design §6) e testes (decimais, dígitos longos, nomes de arquivo,
  URL, e-mail, truncamento).
- [ ] 4.2 Seleção automática do juiz (pool, exclusões, preferência por outro provedor, menor
  preço) e recusa sem candidato, com `same_model` e juiz externo não habilitado (§5.3 e §6).
- [ ] 4.3 Rubrica, prompt do juiz e validação do JSON de saída; uma nova tentativa; `judge_error`
  (§5.2).
- [ ] 4.4 `efeito` determinístico quando possível (§5.2).
- [ ] 4.5 Teto de custo `COMM_EVAL_MAX_USD` com o medidor existente (§5.5).
- [ ] 4.6 Testes com provedor simulado: nota válida; JSON inválido duas vezes → `judge_error`;
  modelo do agente → `judge_skipped: same_model`; seleção e exclusões testadas; orçamento estourado; nenhum teste usa rede.

## 5. Calibração humana
- [ ] 5.1 Comando `calibration-sheet`: amostra estratificada com semente fixa; planilha em
  branco; teste de determinismo da amostra.
- [ ] 5.2 Formato de `docs/benchmarks/calibracao/ask_researcher.jsonl` e leitor com validação.
- [ ] 5.3 Comando `calibrate`: kappa ponderado por critério; selo `não calibrado` (§5.4); teste
  com vetores de kappa conhecido (1,0; 0,0; valor intermediário calculado à mão).
- [ ] 5.4 Invalidação da calibração quando muda modelo do juiz ou versão da rubrica.
- [ ] 5.5 Rotulagem humana de cerca de 20 eventos (ação do pesquisador); registrar no PR.

## 6. Integração com o benchmark
- [ ] 6.1 `communication_eval.json` por sessão e resumo em `results.json` (design §7).
- [ ] 6.2 `report.py`: tabela por combinação com taxas, maior laço e selo de calibração.
- [ ] 6.3 `run_benchmark.py --eval-comm`: roda a avaliação depois da execução, nunca antes.
- [ ] 6.4 `summarize_events` e tabela atual inalterados (teste de regressão).

## 7. Fechamento
- [ ] 7.1 Variáveis `COMM_EVAL_*` do design em `src/config.py` e `.env.example`, com teste de
  padrões.
- [ ] 7.2 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v`.
- [ ] 7.3 Avaliar **uma** sessão já existente no Pi (`~/bench/`), sem juiz externo
  (`COMM_EVAL_ALLOW_EXTERNAL_JUDGE=false`): anexar o `communication_eval.json` ao PR.
- [ ] 7.4 Revisão do Analista de Segurança (redação e política do juiz); revisão nos 7 eixos; PR
  para `dev`; arquivar e consolidar `specs/communication-eval/spec.md` após o merge.
