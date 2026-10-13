# Tarefas: v18.6-review-evidence

**Estado (2026-10-13):** Implementada, com pendências: código e testes unitários das seções 1 a 6 concluídos (branch `feat/v18.6-review-evidence`); ficam abertos o parecer do Analista de Segurança (0.2) e a medição sobre os dados do benchmark no Pi (7.2). Questões do design §8 resolvidas com as propostas do próprio design, por instrução do orquestrador.

## 0. Pré-requisitos
- [x] 0.1 Questões do design §8: adotadas as propostas do design (limiar só com `hypothesis_ref`; `val_` é `validacao`; um nível de achatamento). Confirmar no PR.
- [ ] 0.2 Parecer do Analista de Segurança sobre o perfil estrutural registrado no design §4 ou no PR.
- [x] 0.3 Worktree `.worktrees/v18.6-review-evidence` (branch `feat/v18.6-review-evidence`).

## 1. Qualificador de métrica
- [x] 1.1 `split_metric_name` e `MetricName` em `src/knowledge/normalization.py` (design §1.1).
- [x] 1.2 Revisor: candidatos por base e qualificador; critério que cita o conjunto (§1.2).
- [x] 1.3 Ingestão: `_mede` com o nome base; `Resultado.qualificador`; sem `MEDE` para `cv`/`treino`/`validacao`.
- [x] 1.4 `REVIEW_METRIC_QUALIFIERS` em `src/config.py` e `.env.example`.
- [x] 1.5 Testes: os seis cenários de "Qualificador de conjunto", incluindo `cv_accuracy_mean`.

## 2. `metrics.json`
- [x] 2.1 `metrics_of`: envelope `metricas`, achatamento de um nível, `metrics_ignored_paths` (§2).
- [x] 2.2 `metric_candidates` (§2).
- [x] 2.3 Testes: os três cenários de "Leitura tolerante"; consumidores existentes (ingestão, proveniência, referências numéricas) seguem verdes.

## 3. Critérios
- [x] 3.1 `MetricCriterion.comparisons`; avaliação por comparação (§3.1).
- [x] 3.2 Tabela de decisão por grupo (§3.2); `ReviewResult.undecided_criteria`.
- [x] 3.3 Tabela achatada como evidência ao LLM (§3.3); evento `subtask_review` com `undecided_criteria` e `metric_qualifiers`.
- [x] 3.4 Testes: os quatro cenários de "Critérios com várias comparações", com provedor LLM simulado.

## 4. Perfil estrutural
- [x] 4.1 `src/artifact_profile.py` (`profile_artifact`) para CSV/TSV e JSON (§4.1).
- [x] 4.2 Omissão de nulos em grupo pequeno (§4.2).
- [x] 4.3 `build_artifact_evidence_fragments` usa o perfil para `dado_de_pesquisa`, origem `esquema_agregado`.
- [x] 4.4 Instrução do revisor (§4.3).
- [x] 4.5 `REVIEW_ARTIFACT_PROFILE`, `REVIEW_PROFILE_MAX_BYTES` (5 MB) e `REVIEW_PROFILE_MAX_CHARS` (1200) em `src/config.py` e `.env.example`.
- [x] 4.6 Testes: os cinco cenários de "Perfil estrutural" e o de "Instrução do revisor"; teste de que o `EgressGate` não retém o perfil.

## 5. Comparador de artefatos
- [x] 5.1 Camada `script` (§5).
- [x] 5.2 `.joblib` e `.pkl` em `EXTENSION_TIER_SUFFIXES`.
- [x] 5.3 Testes: os três cenários de "Script executado" e o de "Modelos serializados"; `.py` continua fora da camada `extension`.

## 6. Regra do limiar no plano
- [x] 6.1 `validate_plan`: regra por `task_type` e `hypothesis_ref` (§6); aviso `validation_sem_hipotese`.
- [x] 6.2 Testes: os dois cenários da regra modificada; atualizar testes de `v16-pipeline-robustness` que dependiam da regra antiga.

## 7. Validação
- [ ] 7.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 7.2 Reprocessar, sem LLM, os eventos `subtask_review`/`plan_validation` e os nós `Resultado` do benchmark de 2026-10-13 que ainda estão no Pi (os diretórios de sessão foram apagados) e registrar quantas reprovações determinísticas deixariam de ocorrer.
- [x] 7.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
