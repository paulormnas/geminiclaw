# Tarefas: v18.6-validator-independence

**Estado (2026-10-13):** Implementada, com pendências: código e testes unitários prontos (3376 unit verdes, ruff limpo). Pendente: a integração no Raspberry Pi (ver 8.1) e a nota nos ADRs 007, 017 e 019 (7.2, do Arquiteto).

## 0. Pré-requisitos
- [x] 0.1 ADR 020 aprovado (PR #143); divergências 1 e 2 decididas (dica descartada; padrão `preferred` em `self_hosted_only`).
- [x] 0.2 Parecer de segurança (STRIDE curto) sobre o egresso no design §6; sem bloqueio, requisitos S1 a S6.
- [x] 0.3 Worktree `.worktrees/feat-v18.6-validator-independence`.

## 1. Modo
- [x] 1.1 `effective_judge_mode` e `LLM_JUDGE_INDEPENDENCE` em `src/config.py` e `.env.example` (design §2).
- [x] 1.2 Testes: os três cenários de "Modo de independência".

## 2. Roteador
- [x] 2.1 `JUDGE_ROLES`, `JUDGED_ROLES`, `MOTIVO_MESMA_FAMILIA`; `resolve()` com `familias_proibidas`, inclusive no ramo do pin (§3).
- [x] 2.2 `resolve_session`: nova ordem (pins, julgados, demais, juízes); evitar conflito em todos os papéis; exigência só para `validator`/`developer`; tabela de pins (§3).
- [x] 2.3 `_suggestion` com o ramo `mesma_familia_julgamento`; `PinError` em `strict`.
- [x] 2.4 Atualizar o comentário de ordem em `routing.py:250`.
- [x] 2.5 Testes: os quatro cenários de "Família do Validator" e os três de "Pins".

## 3. Despacho
- [x] 3.1 `JudgeIndependenceGuard` (§4) no estado da sessão.
- [x] 3.2 Chamadas em `apply_hint`/`validate_hint`, no despacho de `base`/`reviewer` (substituição antes do modo) e em `fallback_for`.
- [x] 3.3 Falha só da subtarefa em `required` sem alternativa.
- [x] 3.4 Testes: os cenários de "Conferência no despacho".

## 4. Catálogo
- [x] 4.1 `src/llm/catalog.yaml` (versão 3): preferência de `validator` e `reviewer` com Claude, Gemini e GPT antes dos locais; Claude segue primeiro (questão 10.2: divergência 1 decidida pela dica descartada).
- [x] 4.2 Teste: "Teste do catálogo".

## 5. Registro, banner, relatório, retomada
- [x] 5.1 `independencia_julgamento` no payload da sessão e evento por conferência (§5).
- [x] 5.2 Linha no banner e nos metadados do relatório final; resumo nas métricas de operação.
- [x] 5.3 Retomada: carregar famílias registradas e conferir (§7).
- [x] 5.4 Testes: "Registro na inicialização" e "Catálogo mudou entre as execuções".

## 6. Telemetria e avaliação de comunicação
- [x] 6.1 `review_result` registra papel `validator` e `funcao = "revisao_subtarefa"`.
- [x] 6.2 Conferir os consumidores do rótulo antigo: só `scripts/benchmark/communication.py` lia o modelo do `reviewer` em `token_usage` (agora `validator`, com `reviewer` para sessões antigas); `report.py` lê a saída de `communication.py`; as métricas de operação listam `agent_id` sem filtrar. O evento `subtask_review` (agent_events) segue com `agent_id="reviewer"`, fora do escopo. `token_usage` não tem coluna `funcao` (sem schema): `funcao` vai no log da chamada (`record_llm_call(funcao=...)`).
- [x] 6.3 `select_judge` exclui as famílias de `developer` e `base` (§8).
- [x] 6.4 Testes: "Telemetria da revisão" e seleção do juiz da avaliação de comunicação.

## 7. Documentação e ADRs
- [x] 7.1 `.env.example` com exemplo de juiz de outra família.
- [ ] 7.2 Nota de atualização nos ADRs 007, 017 e 019 apontando para o ADR 020 (PR de documentação, pelo Arquiteto).

## 8. Validação
- [ ] 8.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 8.2 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
