# Tarefas: v18.6-models-gemini4-gpt6

**Estado (2026-10-14):** Concluída e arquivada (#160), seções 0 a 4. Suíte no Pi: 3614 passed, 0 falhas (2026-10-14); os quatro modelos existem nas APIs da conta. Preços reconferidos nas páginas oficiais em 2026-10-14 (sem mudança).

## 0. Pré-requisitos
- [x] 0.1 Spec aprovada pelo pesquisador (merge do PR de especificação), com a escolha do `gpt-6.1-sol` (design §10.2).
- [x] 0.2 Worktree `.worktrees/feat-v18.6-models-gemini4-gpt6`; confrontar a spec com o código (21 arquivos de teste citam os modelos antigos).
- [x] 0.3 Reconferir os preços e IDs nas páginas oficiais no dia da implementação (promoção do Gemini 4 até 2026-11-30).

## 1. Catálogo e padrões
- [x] 1.1 `catalog.yaml` versão 5: incluir Gemini 4 Argon e GPT-6.1 Sol; remover Gemini 3.8 Flash e GPT-5.6 Terra; trocar nas preferências.
- [x] 1.2 `GOOGLE_FALLBACK_MODEL`, alias de visão, `.env.example`, `run_project.md` e docstrings.
- [x] 1.3 Testes dos cenários de "Catálogo com Gemini 4 e GPT-6" e ajuste dos testes que citam os modelos antigos.

## 2. Preços
- [x] 2.1 `Price.promo_until` e `Price.after_promo`; `estimate_cost` por data UTC (relógio injetável).
- [x] 2.2 `PRICES`: `gemini-4-argon` (com vigência) e `gpt-6.1-sol` (cache e contexto longo); remover os antigos.
- [x] 2.3 Testes dos cenários de "Preço com vigência".

## 3. Benchmark
- [x] 3.1 Resultado com `modelos`, `precos` e `data_execucao`; aviso `versao_desconhecida`.
- [x] 3.2 Relatório: tabela "Modelos e versões" e aviso de versão diferente entre rodadas da mesma combinação.
- [x] 3.3 `matrix_modelos_v18_6.json` com os modelos novos e `budget_usd` de US$ 14 para `anthropic`, `openai` e `google`.
- [x] 3.4 Teste da recriação das coleções do Qdrant depois do reset.
- [x] 3.5 Testes dos demais cenários do delta `benchmark`.

## 4. Validação
- [x] 4.1 `uv run ruff check .` e `uv run pytest -m unit -v` verdes.
- [x] 4.2 Suíte `unit or integration` no Pi 5 (worktree do Pi, `flock`, log em `~/*.log`): 0 falhas.
- [x] 4.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR.
- [x] 4.4 Disponibilidade dos quatro modelos na conta, conferida na API antes da bateria (memória de disponibilidade de modelos).
