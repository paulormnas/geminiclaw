# Tarefas: v18.6-hypothesis-closure

**Estado (2026-10-13):** Proposta, aguardando aprovação do pesquisador. Depende de `v18.6-review-evidence`.

## 0. Pré-requisitos
- [ ] 0.1 Questões do design §8 respondidas pelo pesquisador.
- [ ] 0.2 `v18.6-review-evidence` mergeada (qualificador de métrica e critérios por comparação).
- [ ] 0.3 Worktree `.worktrees/feat-v18.6-hypothesis-closure`.

## 1. Revisão
- [ ] 1.1 `ReviewResult.outcome` e as condições do design §1.
- [ ] 1.2 `NEGATIVE_RESULT_AS_PROGRESS` em `src/config.py` e `.env.example`.
- [ ] 1.3 Testes: os cinco cenários de "Resultado negativo na revisão".

## 2. Laço
- [ ] 2.1 Estado `concluded_negative` no DAG; sem retentativa; dependentes liberadas (§2.1).
- [ ] 2.2 `CycleProgress` conta `concluded_negative` (§2.2).
- [ ] 2.3 Feedback de resultado negativo (§2.3).
- [ ] 2.4 Testes: "Dependente roda", "Disjuntor não dispara", "Feedback ao Researcher"; atualizar `tests/unit/test_circuit_breaker.py`.

## 3. Ingestão
- [ ] 3.1 `_experiment_status` e `criterio_plano_atendido`; propriedade opcional em `src/knowledge/schema.py`.
- [ ] 3.2 Evento `resultado_sem_mede` (§3).
- [ ] 3.3 Testes: "Veredito recebe a tentativa" (grafo em memória, vocabulário semeado) e "Métrica candidata".

## 4. Início da sessão
- [ ] 4.1 Conferência do veredito e evento `veredito_indisponivel` (§4); recusa no modo `auto`.
- [ ] 4.2 Testes: os dois cenários de "Conferência do veredito".

## 5. Fechamento por falta de caminhos
- [ ] 5.1 `has_open_paths` com hipóteses do plano sem tentativa (§5).
- [ ] 5.2 Fechamento com `erro` e mensagem ao esgotar os ciclos ociosos.
- [ ] 5.3 Testes: os três cenários do requisito modificado.

## 6. Afirmações
- [ ] 6.1 Investigar por que a sessão do Sonnet (2026-10-12 21:53) não gravou `afirmacoes.json`, pelos eventos no Pi, e registrar a causa no PR.
- [ ] 6.2 `session_results_item` e inclusão para frases sem código (§6.1).
- [ ] 6.3 `afirmacoes.json` sempre gravado com `motivo_vazio` (§6.2).
- [ ] 6.4 Testes: "Frase sem código recebe a tabela" e "Relatório sem afirmações".

## 7. Métricas de operação
- [ ] 7.1 `operation_metrics`: `resultados_sem_mede`, `subtarefas_resultado_negativo`, `hipoteses_sem_tentativa_no_fechamento`.
- [ ] 7.2 Teste dos três contadores.

## 8. Validação
- [ ] 8.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 8.2 Teste de integração com AGE real: sessão simulada (provedores LLM falsos) com uma hipótese refutada e outra validada fecha uma delas com status calculado.
- [ ] 8.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
