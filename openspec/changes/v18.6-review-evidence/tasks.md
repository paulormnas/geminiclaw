# Tarefas: v18.6-review-evidence

**Estado (2026-10-13):** Proposta, aguardando aprovação do pesquisador e parecer do Analista de Segurança (design §4).

## 0. Pré-requisitos
- [ ] 0.1 Questões do design §8 respondidas pelo pesquisador.
- [ ] 0.2 Parecer do Analista de Segurança sobre o perfil estrutural registrado no design §4 ou no PR.
- [ ] 0.3 Worktree `.worktrees/feat-v18.6-review-evidence`.

## 1. Qualificador de métrica
- [ ] 1.1 `split_metric_name` e `MetricName` em `src/knowledge/normalization.py` (design §1.1).
- [ ] 1.2 Revisor: candidatos por base e qualificador; critério que cita o conjunto (§1.2).
- [ ] 1.3 Ingestão: `_mede` com o nome base; `Resultado.qualificador`; sem `MEDE` para `cv`/`treino`/`validacao`.
- [ ] 1.4 `REVIEW_METRIC_QUALIFIERS` em `src/config.py` e `.env.example`.
- [ ] 1.5 Testes: os seis cenários de "Qualificador de conjunto", incluindo `cv_accuracy_mean`.

## 2. `metrics.json`
- [ ] 2.1 `metrics_of`: envelope `metricas`, achatamento de um nível, `metrics_ignored_paths` (§2).
- [ ] 2.2 `metric_candidates` (§2).
- [ ] 2.3 Testes: os três cenários de "Leitura tolerante"; consumidores existentes (ingestão, proveniência, referências numéricas) seguem verdes.

## 3. Critérios
- [ ] 3.1 `MetricCriterion.comparisons`; avaliação por comparação (§3.1).
- [ ] 3.2 Tabela de decisão por grupo (§3.2); `ReviewResult.undecided_criteria`.
- [ ] 3.3 Tabela achatada como evidência ao LLM (§3.3); evento `subtask_review` com `undecided_criteria` e `metric_qualifiers`.
- [ ] 3.4 Testes: os quatro cenários de "Critérios com várias comparações", com provedor LLM simulado.

## 4. Perfil estrutural
- [ ] 4.1 `src/artifact_profile.py` (`profile_artifact`) para CSV/TSV e JSON (§4.1).
- [ ] 4.2 Omissão de nulos em grupo pequeno (§4.2).
- [ ] 4.3 `build_artifact_evidence_fragments` usa o perfil para `dado_de_pesquisa`, origem `esquema_agregado`.
- [ ] 4.4 Instrução do revisor (§4.3).
- [ ] 4.5 `REVIEW_ARTIFACT_PROFILE`, `REVIEW_PROFILE_MAX_BYTES` (5 MB) e `REVIEW_PROFILE_MAX_CHARS` (1200) em `src/config.py` e `.env.example`.
- [ ] 4.6 Testes: os cinco cenários de "Perfil estrutural" e o de "Instrução do revisor"; teste de que o `EgressGate` não retém o perfil.

## 5. Comparador de artefatos
- [ ] 5.1 Camada `script` (§5).
- [ ] 5.2 `.joblib` e `.pkl` em `EXTENSION_TIER_SUFFIXES`.
- [ ] 5.3 Testes: os três cenários de "Script executado" e o de "Modelos serializados"; `.py` continua fora da camada `extension`.

## 6. Regra do limiar no plano
- [ ] 6.1 `validate_plan`: regra por `task_type` e `hypothesis_ref` (§6); aviso `validation_sem_hipotese`.
- [ ] 6.2 Testes: os dois cenários da regra modificada; atualizar testes de `v16-pipeline-robustness` que dependiam da regra antiga.

## 7. Validação
- [ ] 7.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 7.2 Reprocessar, sem LLM, os eventos `subtask_review`/`plan_validation` e os nós `Resultado` do benchmark de 2026-10-13 que ainda estão no Pi (os diretórios de sessão foram apagados) e registrar quantas reprovações determinísticas deixariam de ocorrer.
- [ ] 7.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
