# Proposta: Limites da exploração e parada pelo objetivo do Problema

**ID:** `v18.7-exploration-limits` · **Versão:** V18.7

**Capacidades:** `hypothesis-loop`, `usage-limits`, `agent-runtime`, `operation-metrics`, `benchmark`, `session-continuity`, `research-project`, `knowledge-graph`, `researcher-consult`, `pipeline-robustness`

**ADRs de origem:** [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §5 inteiro (§5.1 sem teto de hipóteses e de ciclos; §5.2 objetivo tipado; §5.3 política `ao_atingir_objetivo`; §5.4 limites de custo, tokens, tempo e egresso; §5.5 estagnação, saturação e restrições; §5.6 proteções contra falha; §5.7 segundo plano; §5.8 replanejamento), §6 (motivo `hipotese_direcao_restrita`), cabeçalho (mudanças no ADR 015 §4, §8 e §9 e no ADR 012 §8); [ADR 023](../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) §1.2 e §4.4 (compatibilidade das esperas); [ADR 022](../../../docs/decisions/adr_022_contrato_contexto_por_chamada.md) §4.1 item 3 e §5 (os critérios por tipo vivem na parte estruturada do regimento).

**Depende de:** `v18.7-graph-exploration-relations` (propriedades novas de `Hipotese` e `Experimento` no mesmo `src/knowledge/schema.py`; `papel` do experimento, usado para excluir `referencia` do critério de atingimento; `abandonada_por`, usado pelas restrições); `v18.7-hypothesis-linking` (mergeada antes: esta mudança faz rebase sobre a nova ordem de `prepare_cycle`, sobre `select` aceitando hipóteses concluídas e sobre a regra de `depende_de_subtarefa_retirada`, e acrescenta só o fim do teto em `select` e a conferência de restrições em `prepare_cycle`); `v18.7-persistent-human-gate` e `v18.7-background-sessions` (mergeadas juntas antes desta: pedidos ao pesquisador pelo gate persistente, com o catálogo `decisao`/`motivo` daquela mudança, e o estado `aguarda_pesquisador` quando só restam pedidos); `v18.7-resource-monitor-config` (dona do mecanismo `_REMOVED_VARIABLES` / `check_removed_variables`; esta mudança só acrescenta os nomes dela); `v18.7-benchmark-fixes` (mergeada antes: cria o motivo `limite_cota_provedor` e o texto do requisito "Classificação dos motivos de parada" sobre o qual esta mudança escreve; esta mudança preserva `limite_cota_provedor` em `StopReason`, no enum de `Sessao.motivo_parada`, em `MOTIVOS_RETOMAVEIS`, em `describe_stop_reason` e em `stop_class`). Coordena com `v18.7-agent-system-prompts` (parte estruturada do regimento com os tipos de objetivo e os motivos de parada), que vem depois. Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.

**Nota de data:** escrita em 2026-10-15, a partir dos ADRs 021, 022 e 023 aprovados nessa data.

## Por quê

A bateria V18.6 (2026-10-15) mostrou que tetos de seleção e de iteração cortam a exploração antes do resultado: `HYPOTHESES_PER_CYCLE` (padrão 2, `src/config.py:534`) retira hipóteses com `hipotese_adiada_por_prioridade` (`src/exploration.py:391`); `MAX_EXPLORATION_CYCLES` (20, `src/config.py:546`) fecha com `limite_ciclos` (`src/autonomous_loop.py:979-986`); `MAX_AGENT_RUNS_PER_SESSION` (30, `src/config.py:161`) e `MAX_PLANNING_RUNS_PER_SESSION` (20, `src/config.py:166`) fecham com `limite_execucoes` (`src/autonomous_loop.py:1023-1027`, `1653-1657`). O critério de solução exige veredito `>= SOLUTION_MIN_VERDICT` (`src/knowledge/hypothesis_cycle.py:509`), e uma evidência perfeita dá no máximo 0,11: nenhuma sessão da bateria fechou por solução, mesmo com acurácia validada 1,0.

O pesquisador decidiu (ADR 021 §5): sem teto de hipóteses nem de ciclos; limites de custo, tokens, tempo e egresso, configuráveis e desligáveis só pela decisão reservada do modo sem limite; parada pelo objetivo do `Problema`, que passa a ter tipo; estagnação como sinal para mudar de tática, não para parar; saturação estatística como parada automática; restrição de direções por segurança, ética ou recurso.

## O que muda

### Novo

- **Limite de custo por sessão** (`SESSION_MAX_COST_USD`, total, e `SESSION_MAX_COST_USD_BY_PROVIDER`, por provedor), com o motivo de parada `limite_custo`, a opção `--max-cost-usd` e a recusa de iniciar com modelo não local sem preço conhecido.
- **Objetivo tipado do `Problema`:** `criterio_sucesso.tipo` em `limiar`, `discriminacao`, `cobertura` (forma mínima) ou `fronteira` (declarado, recusado nesta etapa); `criterio_sucesso.ao_atingir_objetivo` em `parar`, `perguntar` ou `continuar`, com padrão por modo.
- **Critérios por tipo:** atingimento, avanço e saturação (ADR 021 §5.2), aplicados por código determinístico em `src/knowledge/objective.py` (novo).
- **Hipóteses concorrentes e predições** no `discriminacao`; a revisão de subtarefa confere o resultado contra a predição de cada concorrente; desfechos `uma_compativel`, `todas_contrariadas`, `varias_compativeis` e `aguarda_experimento_fisico`.
- **Objetivo proposto no plano** no modo `auto` (chave `objetivo`), válido depois de aprovado pelo Validator, como as métricas da V18.6.
- **Estagnação como intervenção:** depois de `EXPLORATION_STALL_CYCLES` ciclos sem avanço, o Curator é acionado em modo intervenção; paciência crescente; até `EXPLORATION_MAX_INTERVENTIONS` intervenções.
- **Saturação** (motivo de parada `saturacao`) no `auto`; pedido ao pesquisador no `assisted` e no `semi`; pedido também quando as intervenções se esgotam sem saturação avaliável.
- **Restrições de direção:** efeito da decisão reservada `restringir_direcao` (a entrada em `DECISOES_RESERVADAS` e no catálogo do gate é de `v18.7-persistent-human-gate`), nó `Restricao` ligado ao `Problema` ou ao `Projeto`, retirada `hipotese_direcao_restrita` por chave, abordagem e similaridade, conferência na validação do plano e na revisão de subtarefa.
- **Marco do objetivo atingido** no `Problema` e evento `objetivo_atingido`.
- **Falha na inicialização** quando uma variável removida está definida no ambiente.

### Modificado

- **Seleção de hipóteses** (`HypothesisCycle.select`): no `semi` e no `auto`, todas as hipóteses executáveis entram na fila, em ordem de prioridade; nada é adiado.
- **Critério de solução no `limiar`:** resultado aprovado pelo Validator que atinge o alvo e o ganho mínimo sobre a referência, sem filtro de veredito.
- **Disjuntor de zero progresso:** mede progresso por novos `Experimento` e `Resultado` gravados no grafo, inclusive replicações e variações com o mesmo nome de subtarefa.
- **Ciclos ociosos e estagnação:** ciclos em que o único trabalho restante depende de pedido pendente ao pesquisador não contam.
- **`MAX_PLAN_RETRIES`:** fecha com `planos_rejeitados` no `auto`; no `assisted` e no `semi` registra um pedido ao pesquisador antes de fechar.
- **Modo sem limite:** cobre também o custo; a confirmação informa que, sem limites, não há parada automática garantida; não desliga estagnação nem saturação.
- **Aviso G5 de custo:** passa a ser percentual do limite de custo (`OPERATIONAL_THRESHOLD_COST_USAGE_PCT`).
- **Retomada:** `limite_custo` retoma sem perguntar; `saturacao` pergunta; `limite_ciclos` e `limite_execucoes` de sessões antigas continuam retomáveis.
- **Benchmark:** `limite_custo` classificado como `limite`; `saturacao` como `criterio_pesquisa`; a matriz declara o teto de custo da sessão.
- **Rascunho do `Problema`:** traz o tipo de objetivo; `delta_min` só é exigido no `limiar`.

### Removido

- `HYPOTHESES_PER_CYCLE`, `MAX_EXPLORATION_CYCLES`, `SOLUTION_MIN_VERDICT`, `MAX_AGENT_RUNS_PER_SESSION` (e o alias `MAX_CONTAINERS_PER_SESSION`), `MAX_PLANNING_RUNS_PER_SESSION`, `OPERATIONAL_THRESHOLD_AGENT_RUNS_PCT` (e o alias `OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT`) e `OPERATIONAL_THRESHOLD_COST_USD` de `src/config.py` e do `.env.example`.
- Motivos de parada gravados `limite_ciclos` e `limite_execucoes` (`ExplorationStop.CYCLES`, `StopReason.RUNS`); os valores continuam aceitos na leitura de sessões e checkpoints antigos.
- Motivo de retirada `hipotese_adiada_por_prioridade`.
- Cenários "Modo autônomo" (`HYPOTHESES_PER_CYCLE=2`) e "Teto de ciclos" de `hypothesis-loop`; cenários de limite de execuções de `pipeline-robustness` e `agent-runtime`.

### Fora do escopo

- Papel do experimento, ligações derivadas, hipótese do sistema, fila substituída no replanejamento (§5.8 só como regra de saída da fila, implementada por `v18.7-hypothesis-linking`) e demais motivos de retirada do §6: `v18.7-hypothesis-linking` e `v18.7-graph-exploration-relations`.
- Contadores por papel e por origem e o grupo de métricas da exploração: `v18.7-exploration-metrics`, que lê os eventos desta mudança.
- Gate persistente, papel de banco do terminal, estados `aguarda_pesquisador` e `suspensa_sem_pesquisador`, processo da sessão: `v18.7-persistent-human-gate` e `v18.7-background-sessions`.
- Texto do regimento e dos prompts: `v18.7-agent-system-prompts`; aqui só se define o comportamento e os códigos que a parte estruturada declara.
- Tipo `fronteira` além da declaração (V19).
- Direção `o` do veredito a partir da predição nos tipos sem alvo e termo `m` neutro (ADR 015 §9 alterado pelo ADR 021): não estão atribuídos a nenhuma mudança na tabela do ADR 021; ver "Questões em aberto" no `design.md`.
- Calibração do veredito e dos limiares de saturação (Etapa 2).

## Impacto

- **Código:** `src/config.py`, `src/usage.py`, `src/unlimited_mode.py`, `src/cli.py`, `src/exploration.py`, `src/autonomous_loop.py`, `src/orchestrator.py`, `src/knowledge/hypothesis_cycle.py`, `src/knowledge/objective.py` (novo), `src/knowledge/restrictions.py` (novo), `src/knowledge/problem.py`, `src/knowledge/schema.py`, `src/knowledge/validation.py`, `src/agents/validator_agent.py`, `src/research_consult/__init__.py`, `src/continuity.py`, `src/operation_metrics.py`, `scripts/benchmark/run_benchmark.py`, `scripts/benchmark/matrix_modelos_v18_6.json` (ou a matriz V18.7 de `v18.7-benchmark-fixes`), `.env.example`.
- **Contratos:** `UsageBudget.max_cost_usd` e `max_cost_usd_by_provider`; `LimitStatus.cost_usd`, `cost_exhausted`; `StopReason.COST = "limite_custo"`; `ExplorationStop.SATURATION = "saturacao"`; chave `objetivo` do envelope do plano; campos de subtarefa `discrimina` e `experimento_fisico`; campo `predicoes` no parecer de revisão (só no `discriminacao`); eventos `objetivo_atingido`, `objetivo_desfecho`, `estagnacao_intervencao`, `intervencoes_esgotadas`, `saturacao_avaliada`, `cobertura_aviso`, `restricao_retirada`, `custo_nao_estimado`, `variavel_removida` (falha de inicialização).
- **Schema (grafo, aditivo):** enum de `Sessao.motivo_parada` ganha `limite_custo` e `saturacao`; `Problema` ganha `objetivo_atingido` (marco) e a validação estruturada de `criterio_sucesso`; `Hipotese` ganha `predicao` e `concorrente`; `Experimento` ganha `conferencia_predicoes`; novo nó `Restricao` com a relação `RESTRINGE` para `Problema` ou `Projeto`. Nenhuma tabela relacional nova; nenhum dado existente é reescrito.
- **Custo:** nenhuma chamada LLM nova por ciclo; a intervenção por estagnação usa o Curator já chamado por ciclo, com contexto a mais; a conferência de predições e de restrições reaproveita as chamadas de validação do plano e de revisão. O limite de custo reduz o risco de gasto sem fim.

## Aprovações necessárias

- **Alteração de schema do grafo (aditiva):** novo rótulo de nó `Restricao` e relação `RESTRINGE`; valores novos em `Sessao.motivo_parada`; propriedades novas em `Problema`, `Hipotese` e `Experimento` (AGENTS.md §1.5). Sem migração de dados.
- **Remoção de variáveis de configuração** com falha de inicialização quando definidas: todo `.env` derivado do `.env.example` (inclusive o do Raspberry Pi de testes) precisa ser migrado; a migração do `.env` do Pi é feita junto com a de `v18.7-resource-monitor-config`.
- Nenhuma alteração de Dockerfile, `docker-compose.yml`, `AGENTS.md` ou exclusão de arquivo de produção.
