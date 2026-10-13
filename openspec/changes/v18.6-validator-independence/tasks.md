# Tarefas: v18.6-validator-independence

**Estado (2026-10-13):** Proposta, aguardando aprovação do ADR 020 (Proposto), das divergências registradas nele e o parecer do Analista de Segurança (design §6).

## 0. Pré-requisitos
- [ ] 0.1 ADR 020 aprovado; divergências 1 e 2 decididas pelo pesquisador.
- [ ] 0.2 Parecer do Analista de Segurança sobre o egresso (design §6).
- [ ] 0.3 Worktree `.worktrees/feat-v18.6-validator-independence`.

## 1. Modo
- [ ] 1.1 `effective_judge_mode` e `LLM_JUDGE_INDEPENDENCE` em `src/config.py` e `.env.example` (design §2).
- [ ] 1.2 Testes: os três cenários de "Modo de independência".

## 2. Roteador
- [ ] 2.1 `JUDGE_ROLES`, `JUDGED_ROLES`, `MOTIVO_MESMA_FAMILIA`; `resolve()` com `familias_proibidas`, inclusive no ramo do pin (§3).
- [ ] 2.2 `resolve_session`: nova ordem (pins, julgados, demais, juízes); evitar conflito em todos os papéis; exigência só para `validator`/`developer`; tabela de pins (§3).
- [ ] 2.3 `_suggestion` com o ramo `mesma_familia_julgamento`; `PinError` em `strict`.
- [ ] 2.4 Atualizar o comentário de ordem em `routing.py:250`.
- [ ] 2.5 Testes: os quatro cenários de "Família do Validator" e os três de "Pins".

## 3. Despacho
- [ ] 3.1 `JudgeIndependenceGuard` (§4) no estado da sessão.
- [ ] 3.2 Chamadas em `apply_hint`/`validate_hint`, no despacho de `base`/`reviewer` (substituição antes do modo) e em `fallback_for`.
- [ ] 3.3 Falha só da subtarefa em `required` sem alternativa.
- [ ] 3.4 Testes: os cenários de "Conferência no despacho".

## 4. Catálogo
- [ ] 4.1 `src/llm/catalog.yaml`: preferência de `validator` e `reviewer` com Claude, Gemini e GPT antes dos locais (ordem conforme a questão 10.2).
- [ ] 4.2 Teste: "Teste do catálogo".

## 5. Registro, banner, relatório, retomada
- [ ] 5.1 `independencia_julgamento` no payload da sessão e evento por conferência (§5).
- [ ] 5.2 Linha no banner e nos metadados do relatório final; resumo nas métricas de operação.
- [ ] 5.3 Retomada: carregar famílias registradas e conferir (§7).
- [ ] 5.4 Testes: "Registro na inicialização" e "Catálogo mudou entre as execuções".

## 6. Telemetria e avaliação de comunicação
- [ ] 6.1 `review_result` registra papel `validator` e `funcao = "revisao_subtarefa"`.
- [ ] 6.2 Conferir os consumidores do rótulo antigo (`scripts/benchmark/report.py`, `communication.py`, métricas de operação) e ajustar.
- [ ] 6.3 `select_judge` exclui as famílias de `developer` e `base` (§8).
- [ ] 6.4 Testes: "Telemetria da revisão" e seleção do juiz da avaliação de comunicação.

## 7. Documentação e ADRs
- [ ] 7.1 `.env.example` com exemplo de juiz de outra família.
- [ ] 7.2 Nota de atualização nos ADRs 007, 017 e 019 apontando para o ADR 020 (PR de documentação, pelo Arquiteto).

## 8. Validação
- [ ] 8.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 8.2 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
