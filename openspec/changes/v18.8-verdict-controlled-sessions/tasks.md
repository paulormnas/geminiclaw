# Tarefas: v18.8-verdict-controlled-sessions

**Estado (2026-10-20):** especificada e aprovada pelo pesquisador (valores dos regimes, piloto primeiro, regime F incluído, unidade = exploração). Seções 0 a 3 mergeadas (#229, #230, #232, #233); seção 4 (N-abordagem-4 offline) implementada no PR `feat/v18.8-approach-failure`: cenários N-abordagem-3 e N-abordagem-ruido, variantes de `q`, `p_falha_abordagem` e tipo `abordagem_falha` na simulação, comando `abordagem` e relatório com a proposta (rodada idêntica no Pi e no Mac). **Decisão pendente do pesquisador:** valor de `VERDICT_APPROACH_FAILURE_Q` (o relatório propõe manter 0,3 até o piloto e, se necessário, 0,5); `src/config.py` não foi alterado. Nenhuma execução com LLM foi feita; piloto e bateria só com confirmação explícita e orçamento aprovado.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador (decisões em `proposal.md`).
- [x] 0.2 Spec confrontada com o código (design §1) e `N-abordagem-4` medido (design §7).
- [x] 0.3 PR das specs (ADR 025, roadmap V18.8, `openspec/README.md`, `docs/decisions/README.md`) mergeado; parecer de segurança no PR.

## 1. Gerador, regimes e verdade (PR próprio)
- [x] 1.1 `scripts/verdict_lab/controlled/generator.py`: dados P, T, N e F determinísticos por semente (biblioteca padrão), `dados.csv` e `dados.yaml` (`compartilhavel` com motivo).
- [x] 1.2 `regimes.py`: `ProblemDraft` por regime, tarefa neutra, forças calibradas no oráculo, `verdade.json`.
- [x] 1.3 Testes: determinismo byte a byte; teto e patamares dentro de ±0,005; N sem associação com os atributos; tamanho do F; `verdade.json` fora de `input_context/`; `dados.yaml` aceito pelo carregador de contexto.

## 2. Orquestrador, orçamento e runner (PR próprio)
- [x] 2.1 `scripts/benchmark/run_benchmark.py` e `seed_project.py`: parâmetros opcionais `seeder`, `input_dir` (e `draft` no `seed_project`); teste de regressão do Iris.
- [x] 2.2 `explorer.py`: laço da exploração (design §4.2), `exploracao.json`, censura, `sem_progresso`, teto de gasto, sessões e minutos; modo `--ensaio` padrão.
- [x] 2.3 `budget.py` e comando `orcamento` (design §5.1), sem LLM nem banco.
- [x] 2.4 Testes com processo simulado (`command` substituível): fim natural, retomada após `limite_*`, teto de custo, `limite_cota_provedor` repetido, falha, recusa sem `--confirm-target`.

## 3. Medição e comparação com o laboratório (PR próprio)
- [x] 3.1 `measure.py`: medidas do design §6.2 com intervalos de Wilson e Clopper-Pearson; `resultados.csv`, `relatorio.md`, `manifesto.json`.
- [x] 3.2 Equivalência com `completa2` e variante `atual` ao lado (design §6.3, item 1).
- [x] 3.3 Estimativa dos parâmetros e previsão pela simulação (item 2) e leitura (item 3).
- [x] 3.4 Testes com grafos arquivados sintéticos: um por medida e por regime, censura e o cenário "compatível/incompatível".

## 4. N-abordagem-4 offline (PR próprio)
- [x] 4.1 Catálogo: N-abordagem-3 e N-abordagem-ruido; `variantes.json`: `approach_failure_q` 0,5, 0,7 e 1,0.
- [x] 4.2 Simulação: `p_falha_abordagem` e tipo `abordagem_falha`; medidas por `q` (design §7).
- [x] 4.3 Rodada no Raspberry Pi e relatório curto em `docs/calibracao-veredito/` com a proposta; **decisão do pesquisador** sobre `VERDICT_APPROACH_FAILURE_Q` (mudança de valor só em PR próprio, com ADR 015 §9.9).

## 5. Piloto (somente com confirmação explícita)
- [ ] 5.1 Plano do piloto e tabela `orcamento` (teto US$ 56) aprovados pelo pesquisador.
- [ ] 5.2 Piloto: P, T, N e F × `haiku-dev-sol-juiz` e `sonnet-dev-sol-juiz`, uma exploração cada, `--reset-stores --confirm-target geminiclaw_bench@localhost`.
- [ ] 5.3 Relatório do piloto em `docs/calibracao-veredito/`: chamadas, tokens e US$ por papel, variações por hipótese, fim natural alcançado, calibração do regime F.
- [ ] 5.4 Tabela `orcamento` da bateria com os dados do piloto, aprovada pelo pesquisador.

## 6. Bateria controlada (somente com confirmação explícita)
- [ ] 6.1 Bateria com as repetições aprovadas (design §5.3).
- [ ] 6.2 `medir`, comparação com a previsão e relatório final em `docs/calibracao-veredito/` (pergunta, método, resultados, leitura, limitações, comandos, commit).

## 7. Documentação e fechamento
- [ ] 7.1 ADR 025: etapa 3 e status, tabela "Estado da implementação"; `docs/decisions/README.md`.
- [ ] 7.2 `roadmaps/roadmap_V18.8.md`, `docs/calibracao-veredito/README.md` e `openspec/README.md`.
- [ ] 7.3 `uv run ruff check .`, `uv run lint-imports` e `uv run pytest -m "unit or integration" -v` verdes no Raspberry Pi.
- [ ] 7.4 Memória do projeto e `tasks.md` com caixas e linha **Estado** atualizadas a cada PR; confirmação do Arquiteto para o ADR 025 depois do merge.
