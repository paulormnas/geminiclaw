# Tarefas: v18.7-exploration-limits

**Estado (2026-10-16):** aprovada pelo pesquisador (schema do grafo, remoção das variáveis de teto, Questões 4 e 5 do design §17 decididas); tarefa 0.9 (divisão do módulo) feita; o comportamento novo (seções 1 a 6) ainda não iniciado. Todo valor de variável que precise de ajuste é validado em bateria de testes antes de mudar o padrão.

## 0. Pré-requisitos
- [x] 0.1 Mudança aprovada pelo pesquisador, inclusive o schema aditivo do grafo (`Restricao`, `RESTRINGE`, motivos, propriedades) e a remoção das variáveis de teto com falha na inicialização.
- [x] 0.2 Questões em aberto do `design.md` §17 respondidas ou mantidas com a proposta registrada (decididas pelo pesquisador em 2026-10-15: padrão de `SESSION_MAX_COST_USD` em 20.0, agrupamento do catálogo de pedidos com `v18.7-persistent-human-gate`, remoção de `MAX_PLANNING_RUNS_PER_SESSION` e reabertura por `graph edit`; ficam abertas as Questões 4 e 5).
- [ ] 0.3 Mergeadas antes: `v18.7-graph-exploration-relations`, `v18.7-hypothesis-linking`, `v18.7-resource-monitor-config` (mecanismo `_REMOVED_VARIABLES`), `v18.7-benchmark-fixes` (`limite_cota_provedor`) e o par `v18.7-background-sessions` + `v18.7-persistent-human-gate` (catálogo `decisao`/`motivo` do gate, `aguarda_pesquisador`, `encerrada_pesquisador`); rebase sobre todas.
- [ ] 0.4 Worktree `.worktrees/feat-v18.7-exploration-limits`; spec confrontada com o código (design §1). Os testes com grafo em memória usam e estendem `tests/support/exploration_graph.py` de `v18.7-graph-exploration-relations` (design §5.1 daquela mudança).
- [x] 0.9 (feito em 2026-10-16: relatório final e métricas de operação, ~360 linhas, movidos para `src/orchestration/loop_report.py` como `LoopReportMixin`, sem mudança de comportamento; os critérios de parada, o objetivo tipado, a estagnação e a saturação nascem já em módulos próprios nas seções 3 a 6, porque hoje estão embutidos no corpo de `_run_complex_path` e só serão reescritos) Divisão do módulo grande antes do comportamento novo (ADR 024 §5), só movendo código, com a suíte verde antes de seguir: `src/orchestration/autonomous_loop.py`: extrair para módulos próprios em `src/orchestration/` os critérios de parada, o objetivo tipado e a política ao atingir o objetivo, a estagnação e a saturação. Os caminhos citados nesta mudança valem pela tabela de `v18.7-source-layout`.

## 1. Configuração e variáveis removidas
- [ ] 1.1 `src/config.py`: `ON_PLAN_REJECTIONS`, `SESSION_MAX_COST_USD`, `SESSION_MAX_COST_USD_BY_PROVIDER`, `OPERATIONAL_THRESHOLD_COST_USAGE_PCT`, `EXPLORATION_STALL_CYCLES`, `EXPLORATION_MAX_INTERVENTIONS`, `EXPLORATION_PATIENCE_GROWTH`, `SATURATION_MIN_REPLICATES`, `SATURATION_SE_MULTIPLIER`, `COVERAGE_NOVELTY_WINDOW`, `COVERAGE_NOVELTY_MIN_RATE`, `RESTRICTION_SIMILARITY`, com validação (design §13).
- [ ] 1.2 Remover `HYPOTHESES_PER_CYCLE`, `MAX_EXPLORATION_CYCLES`, `SOLUTION_MIN_VERDICT`, `MAX_AGENT_RUNS_PER_SESSION`, `MAX_PLANNING_RUNS_PER_SESSION`, `OPERATIONAL_THRESHOLDS["agent_runs_pct"]` e `["cost_usd"]`; nomes acrescentados a `_REMOVED_VARIABLES` de `v18.7-resource-monitor-config` (design §12), sem mecanismo próprio.
- [ ] 1.3 `.env.example` atualizado.
- [ ] 1.4 Testes: cenários "Zero não desliga", "Formato inválido" e "Teto de ciclos antigo no .env".

## 2. Schema do grafo
- [ ] 2.1 `src/knowledge/schema.py`: `motivo_parada` com `limite_custo` e `saturacao` (mantendo antigos e `limite_cota_provedor`); `Problema.objetivo_atingido`; `Hipotese.concorrente`, `predicao`; `Experimento.conferencia_predicoes`; nó `Restricao` e relação `RESTRINGE`.
- [ ] 2.2 `src/knowledge/validation.py`: validação estruturada de `criterio_sucesso`; barreira de agentes para `objetivo_atingido` e `Restricao`.
- [ ] 2.3 Migração idempotente do rótulo `Restricao` (junto da de `v18.7-graph-exploration-relations`).
- [ ] 2.4 Testes dos cenários de `specs/knowledge-graph/spec.md`.
- [ ] 2.5 Barreira de `ao_atingir_objetivo` e `definido_por = "pesquisador"` em `src/knowledge/validation.py` (mecanismo de `HUMAN_ONLY_TRANSITIONS`); testes do requisito "Campos do pesquisador no objetivo protegidos no grafo" com os actors `orquestrador`, agente e `pesquisador` (parecer de segurança, item 1).

## 3. Limite de custo
- [ ] 3.1 `src/usage.py`: `UsageBudget` com custo; `UsageTracker(cost_reader=...)`; `LimitStatus` com custo e precedência (design §3.2); `StopReason.COST`; remover `StopReason.RUNS`.
- [ ] 3.2 Verificação de preço na inicialização da sessão e evento `custo_nao_estimado` (design §3.3).
- [ ] 3.3 `src/cli.py` e `src/unlimited_mode.py`: `--max-cost-usd`, incompatibilidade com `--unlimited`, texto da confirmação, banner.
- [ ] 3.4 Aviso G5 por percentual de custo; remover aviso de execuções (`src/autonomous_loop.py:452-510`).
- [ ] 3.5 Testes dos cenários de `specs/usage-limits/spec.md` e `specs/operation-metrics/spec.md`, inclusive "Modelo de reserva sem preço" (verificação de início sobre os modelos de reserva, parecer de segurança, item 4) e o texto da confirmação com "indefinidamente", `wait_for_health` e `SANDBOX_MIN_FREE_BYTES` (item 5).

## 4. Fim dos tetos de hipóteses, ciclos e execuções
- [ ] 4.1 `HypothesisCycle.select` sem `per_cycle` nem `deferred`; ordem de despacho por prioridade; remover `hipotese_adiada_por_prioridade` de `prepare_cycle`.
- [ ] 4.2 `src/autonomous_loop.py`: remover o teto de ciclos (`:979-986`) e os fechamentos por `AgentRunLimitReached`; `src/orchestrator.py`: contadores sem limite, `effective_run_limit` e `AgentRunLimitReached` removidos; `custo_recursos.execucoes_agente`.
- [ ] 4.3 Testes: "Modo autônomo sem teto", "Sem teto de ciclos", "Muitas execuções não encerram a sessão".

## 5. Objetivo tipado
- [ ] 5.1 `src/knowledge/problem.py`: rascunho com `tipo`, campos por tipo, `ao_atingir_objetivo`; `delta_min` só no `limiar`; concorrentes viram `Hipotese` na confirmação; recusa de `fronteira`.
- [ ] 5.2 Chave `objetivo` no plano, `objective_required`, instrução ao Researcher, `validate_plan(objective_definition=...)`, gravação após aprovação, pedido `confirmar_problema` no `assisted`/`semi` (design §4.3).
- [ ] 5.3 `src/knowledge/objective.py` com `limiar`, `discriminacao`, `cobertura` (design §5); campos `discrimina` e `experimento_fisico` no plano; `predicoes` no parecer de revisão.
- [ ] 5.4 Substituir `check_solution`, `confirm_solution`, `terminal_solution_confirmer` e `declined_solutions` pela política (design §6); evento e marco `objetivo_atingido`.
- [ ] 5.5 Comandos `geminiclaw project objective`.
- [ ] 5.6 Testes dos requisitos "Objetivo do Problema por tipo", "Objetivo proposto no plano no modo auto", "Objetivo atingido no limiar sem filtro de veredito", "Desfechos do objetivo de discriminação", "Cobertura mínima", "Política ao atingir o objetivo" e de `specs/research-project/spec.md`.

## 6. Estagnação, intervenção e saturação
- [ ] 6.1 Contagem de ciclos sem avanço, paciência, intervenção do Curator (`curator_suggest(..., intervencao=...)`), pedidos (design §7).
- [ ] 6.2 Saturação por tipo, fechamento `saturacao` no `auto`, pedidos no `assisted`/`semi`, `intervencoes_esgotadas`.
- [ ] 6.3 `exploracao_estado` no checkpoint e restauração na retomada.
- [ ] 6.4 Testes dos requisitos "Estagnação leva a intervenção do Curator" (inclusive "Melhora dentro do erro não é avanço", regra de avanço com `SATURATION_SE_MULTIPLIER × EP`), "Saturação depois das intervenções", "Estado da exploração no checkpoint" e "Estado da exploração restaurado na retomada".

## 7. Restrições de direção
- [ ] 7.1 `src/knowledge/restrictions.py`: leitura das ativas, casamento por abordagem e por similaridade (índice semântico local), abandono da hipótese, evento `restricao_retirada`.
- [ ] 7.2 Efeito da decisão `restringir_direcao` (já em `DECISOES_RESERVADAS` e no `CHECK` do gate por `v18.7-persistent-human-gate`): resposta `restringir` cria `Restricao`; comandos `project restrict`, `restrictions`, `unrestrict`.
- [ ] 7.3 Validator do plano (`restricoes_duvidosas`) e da revisão (`viola_restricao`, motivo `direcao_restrita`).
- [ ] 7.4 Testes do requisito "Restrições de direção aplicadas ao plano e à revisão" e de `specs/researcher-consult/spec.md`; teste de reabertura pelo pesquisador por `graph edit` de hipótese retirada por restrição (design §8.2).
- [ ] 7.5 Validação de `Restricao` só pelo `Actor` pesquisador no terminal ou pela sessão com pedido `restringir_direcao` consumido por `consume_authorized` (`pedido_id` obrigatório), e ator pesquisador derivado de `Restricao` ativa na retirada por restrição; testes "Orquestrador sem pedido autorizado é recusado", "Pedido já consumido não cria segunda restrição", "Sessão sem pedido_id" e os três de "Abandono por restrição com autoridade da restrição" (parecer de segurança, itens 2 e 3).

## 8. Proteções contra falha
- [ ] 8.1 `CycleProgress` por contagem de `Experimento` e `Resultado` (design §9.1).
- [ ] 8.2 Ciclos de espera fora de `idle_cycles`, da estagnação e do disjuntor (design §9.2).
- [ ] 8.3 `ON_PLAN_REJECTIONS` (`explorar` padrão | `parar`) em `src/config.py` e `.env.example`, com validação; `MAX_PLAN_RETRIES` conforme a política (design §9.3): `explorar` aciona a intervenção do Curator com as últimas `issues` e zera `rejected_plans`; `parar` fecha no `auto` e pede no `assisted`/`semi`.
- [ ] 8.4 Testes de `specs/pipeline-robustness/spec.md`, "Disjuntor por novos experimentos e resultados", "Espera por pedido do pesquisador fora dos contadores" e dos cenários de planos rejeitados (um por política).

## 9. Retomada, métricas e benchmark
- [ ] 9.1 `src/continuity.py`: `limite_custo` retomável, `saturacao` com confirmação, antigos mantidos, `limite_cota_provedor` preservado.
- [ ] 9.2 `describe_stop_reason` e `custo_recursos` (custo por provedor, limites, execuções).
- [ ] 9.3 `scripts/benchmark/run_benchmark.py`: `stop_class` explícito (inclui `planos_rejeitados` com classe própria e `versao_modelo` → `limite`), `build_env` define `ON_PLAN_REJECTIONS=parar` no ambiente do subprocesso (junto de `ON_MODEL_VERSION_CHANGE=parar` de `v18.7-benchmark-fixes`); recusa da matriz sem `SESSION_MAX_COST_USD`; matriz atualizada.
- [ ] 9.4 Testes de `specs/session-continuity/spec.md` e `specs/benchmark/spec.md`.

## 10. Validação
- [ ] 10.1 `uv run ruff check .` e `uv run pytest -m "unit or integration" -v` verdes.
- [ ] 10.2 `.env` do Raspberry Pi migrado (com `v18.7-resource-monitor-config`), sem rodar a bateria sem confirmação do pesquisador.
- [ ] 10.3 `tasks.md` com caixas e linha **Estado** atualizadas no PR; ADR 021 confirmado pelo Arquiteto depois do merge.
- [ ] 10.4 Na bateria da V18.7 (com confirmação do pesquisador): nenhuma parada por `limite_ciclos` ou `limite_execucoes`; sessões com acurácia validada no alvo fecham por `solucao_encontrada`.
