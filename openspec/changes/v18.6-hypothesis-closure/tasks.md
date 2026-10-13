# Tarefas: v18.6-hypothesis-closure

**Estado (2026-10-13):** Implementada. Testes verdes (ruff; Pi 5: 3534 passed, 1 falha preexistente da fila de similaridade; AGE real passou). Pendentes: (b) tarefa 6.1 (causa da ausência de `afirmacoes.json` no Sonnet) sem confirmação nos eventos do Pi; (c) respostas do pesquisador às questões do design §8 (adotadas as propostas conservadoras, design §8.1). `v18.6-review-evidence` já está em `dev` (#142).

## 0. Pré-requisitos
- [ ] 0.1 Questões do design §8 respondidas pelo pesquisador. (Pendente: adotadas as propostas conservadoras, design §8.1.)
- [x] 0.2 `v18.6-review-evidence` mergeada (qualificador de métrica e critérios por comparação).
- [x] 0.3 Worktree `.worktrees/feat-v18.6-hypothesis-closure`.

## 1. Revisão
- [x] 1.1 `ReviewResult.outcome` e as condições do design §1.
- [x] 1.2 `NEGATIVE_RESULT_AS_PROGRESS` em `src/config.py` e `.env.example`.
- [x] 1.3 Testes: os cinco cenários de "Resultado negativo na revisão".

## 2. Laço
- [x] 2.1 Estado `concluded_negative` no DAG; sem retentativa; dependentes liberadas (§2.1).
- [x] 2.2 `CycleProgress` conta `concluded_negative` (§2.2).
- [x] 2.3 Feedback de resultado negativo (§2.3).
- [x] 2.4 Testes: "Dependente roda", "Disjuntor não dispara", "Feedback ao Researcher"; atualizar `tests/unit/test_circuit_breaker.py`.

## 3. Ingestão
- [x] 3.1 `_experiment_status` e `criterio_plano_atendido`; propriedade opcional em `src/knowledge/schema.py`.
- [x] 3.2 Evento `resultado_sem_mede` (§3).
- [x] 3.3 Testes: "Veredito recebe a tentativa" (grafo em memória, vocabulário semeado) e "Métrica candidata".

## 4. Início da sessão
- [x] 4.1 Conferência do veredito e evento `veredito_indisponivel` (§4); recusa no modo `auto`.
- [x] 4.2 Testes: os dois cenários de "Conferência do veredito".

## 5. Fechamento por falta de caminhos
- [x] 5.1 `has_open_paths` com hipóteses do plano sem tentativa (§5).
- [x] 5.2 Fechamento com `erro` e mensagem ao esgotar os ciclos ociosos.
- [x] 5.3 Testes: os três cenários do requisito modificado.

## 6. Afirmações
- [ ] 6.1 Investigar por que a sessão do Sonnet (2026-10-12 21:53) não gravou `afirmacoes.json`, pelos eventos no Pi, e registrar a causa no PR. (Pendente: sem acesso aos logs do Pi; análise de código no design §8.1.)
- [x] 6.2 `session_results_item` e inclusão para frases sem código (§6.1).
- [x] 6.3 `afirmacoes.json` sempre gravado com `motivo_vazio` (§6.2).
- [x] 6.4 Testes: "Frase sem código recebe a tabela" e "Relatório sem afirmações".

## 7. Métricas de operação
- [x] 7.1 `operation_metrics`: `resultados_sem_mede`, `subtarefas_resultado_negativo`, `hipoteses_sem_tentativa_no_fechamento`.
- [x] 7.2 Teste dos três contadores.

## 8. Validação
- [x] 8.1 `ruff` verde. Pi 5 (2026-10-13): unit + integration 3534 passed, 8 skipped, 1 failed (`test_similarity_queue_integration::test_fluxo_completo_da_fila`, preexistente: item `x` sobrando na fila compartilhada; falha também na dev antiga do Pi). No Mac, 4 testes exigem `openpyxl`/`pytesseract`, instalados no Pi.
- [x] 8.2 Teste de integração com AGE real (`tests/integration/knowledge/test_hypothesis_closure_age.py`): passou no Pi 5 em 2026-10-13; sessão simulada com uma hipótese refutada e outra validada fecha pelo veredito calculado.
- [x] 8.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
