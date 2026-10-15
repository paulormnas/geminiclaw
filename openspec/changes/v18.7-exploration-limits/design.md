# Design: v18.7-exploration-limits

## 1. Confronto com o código (2026-10-15)

| Ponto | Onde está hoje | O que muda |
|---|---|---|
| Teto de hipóteses por ciclo | `HYPOTHESES_PER_CYCLE` (`src/config.py:534`); `HypothesisCycle._select_autonomous` corta em `self._per_cycle` (`src/knowledge/hypothesis_cycle.py:346-351`); retirada `hipotese_adiada_por_prioridade` (`src/exploration.py:390-391`) | Todas as executáveis entram, em ordem de prioridade; `Selection.deferred` deixa de existir |
| Teto de ciclos | `MAX_EXPLORATION_CYCLES` (`src/config.py:546`); `src/autonomous_loop.py:979-986`; `ExplorationStop.CYCLES` (`src/exploration.py:65`) | Removido; `cycle_no` continua contado e relatado |
| Teto de execuções | `MAX_AGENT_RUNS_PER_SESSION` e `MAX_PLANNING_RUNS_PER_SESSION` (`src/config.py:161-166`); `Orchestrator.effective_run_limit` e `AgentRunLimitReached` (`src/orchestrator.py:1841-1877`); fechamento `StopReason.RUNS` (`src/autonomous_loop.py:1023-1027`, `1393-1398`, `1653-1657`, `1764`) | Contadores mantidos para relatório; a exceção e o fechamento saem |
| Aviso de execuções | `OPERATIONAL_THRESHOLDS["agent_runs_pct"]` (`src/config.py:404-408`, `src/autonomous_loop.py:477-503`) | Removido (não há limite para percentual) |
| Critério de solução | `HypothesisCycle.check_solution` com filtro `SOLUTION_MIN_VERDICT` (`hypothesis_cycle.py:488-519`) e `_meets_target` (alvo **ou** `delta_min`, `:472-486`) | Substituído por `src/knowledge/objective.py` conforme o tipo; no `limiar`, sem veredito, alvo **e** `delta_min` quando ambos existem |
| Confirmação de solução no `assisted` | `terminal_solution_confirmer` (`src/exploration.py:134-164`), `_suspend_session` sem resposta (`src/autonomous_loop.py:1717-1724`) | Pedido `decidir_objetivo_atingido` ao gate persistente (política `perguntar`) |
| Custo | Estimado por chamada (`src/llm/pricing.py:98-121`), somado em `get_token_summary` com o buffer (`src/telemetry.py:825-889`); só aviso G5 absoluto `OPERATIONAL_THRESHOLD_COST_USD` (`src/config.py:399`) | Vira limite de parada no `UsageTracker` (`src/usage.py:328-520`) |
| Disjuntor | `CycleProgress` por nomes de subtarefa bem-sucedidas e assinaturas de erro (`src/autonomous_loop.py:63-72`, `1790-1845`) | Progresso por contagem de `Experimento` e `Resultado` da sessão no grafo, mais as assinaturas de erro |
| Ciclo ocioso e pedido pendente | `exploration.idle_cycles` (`src/autonomous_loop.py:1081-1127`); aprovação pendente suspende a sessão (`:1083-1087`) | Ciclo bloqueado só por pedido pendente não incrementa `idle_cycles` nem a estagnação |
| Planos rejeitados | `rejected_plans >= MAX_PLAN_RETRIES` fecha em todos os modos (`src/autonomous_loop.py:987-994`) | Só o `auto` fecha direto; `assisted` e `semi` registram pedido antes |
| Retomada | `MOTIVOS_RETOMAVEIS` (`src/continuity.py:64-70`), `evaluate_resumability` (`:1083-1135`) | `limite_custo` retomável; `saturacao` pede confirmação |
| Motivos no grafo | `Sessao.motivo_parada` (`src/knowledge/schema.py:134-150`) | Ganha `limite_custo` e `saturacao`; `limite_ciclos` e `limite_execucoes` ficam só para leitura de dados antigos |
| Benchmark | `stop_class` (`scripts/benchmark/run_benchmark.py:270-289`) já classifica qualquer `limite_*` como `limite` e o resto como `criterio_pesquisa` | Classificação explícita e testada; matriz declara o teto de custo |
| Decisões reservadas | `DECISOES_RESERVADAS` (`src/research_consult/__init__.py:13-19`) | `restringir_direcao` entra na lista por `v18.7-persistent-human-gate` (dona do catálogo do gate); esta mudança implementa o efeito da decisão (nó `Restricao`, §8) |
| `criterio_sucesso` | Propriedade livre de `Problema` (`src/knowledge/schema.py:173`), montada por `ProblemDraft.criterio_sucesso` (`src/knowledge/problem.py:71-78`) | Ganha `tipo`, `ao_atingir_objetivo` e campos por tipo, validados na escrita |

## 2. Fila sem teto (ADR 021 §5.1)

`HypothesisCycle.select` no `semi` e no `auto`: todas as hipóteses de agente não bloqueadas vão para `selection.execute`, ordenadas por `(-prioridade, id)`, e passam a `em_teste`. A ordem de despacho das subtarefas no DAG segue essa ordem entre subtarefas sem dependência entre si (desempate estável por `task_name`). `Selection.deferred`, `per_cycle` e o código `hipotese_adiada_por_prioridade` saem. O `assisted` não muda: as hipóteses de agente esperam aprovação.

Hipóteses concluídas (`validada`, `refutada`) deixam de ser excluídas da seleção pela regra do ADR 021 §4.3; essa parte é de `v18.7-hypothesis-linking`. As duas mudanças editam `select`; a ordem de merge define quem faz o rebase.

## 3. Limite de custo (ADR 021 §5.4)

### 3.1 Orçamento

`UsageBudget` ganha `max_cost_usd: float | None` e `max_cost_usd_by_provider: Mapping[str, float]` (vazio = só o total). Fora do modo sem limite, `max_cost_usd` é positivo e cada valor por provedor é positivo; no modo sem limite, ambos são `None`/vazio (mesma regra de tokens, tempo e egresso). `UsageBudget.from_config(max_cost_usd=...)` aceita o override da CLI `--max-cost-usd`, incompatível com `--unlimited`. `to_payload()` grava os dois campos em `payload["budget"]`.

`SESSION_MAX_COST_USD_BY_PROVIDER` tem o formato `provedor=valor[,provedor=valor]` (provedores de `src/llm/registry`); valor não numérico, não positivo ou provedor desconhecido falha na inicialização.

### 3.2 Leitura e parada

`UsageTracker` ganha `cost_reader: Callable[[], dict[str, float | None]]` (injetável; padrão: `get_token_summary(execution_id)` agrupado por `llm_provider`, que já soma o buffer não gravado). `LimitStatus` ganha `cost_usd`, `cost_pct`, `cost_by_provider`, `cost_exhausted` e `cost_exhausted_provider`.

- Teto de exploração do custo: `max_cost_usd × (1 − closing_reserve_pct)`, como o de tokens, para que o fechamento (checkpoint e consolidação do Curator) ainda tenha orçamento.
- Por provedor: atingir o teto de um provedor fecha a sessão com `limite_custo` (não há troca automática de provedor; a alocação é decisão de configuração, ADR 017).
- Prioridade de `stop_reason`: tokens > tempo > custo > egresso > `limite_cota_provedor` > conexão > pendente. `limite_cota_provedor` vem de `v18.7-benchmark-fixes` (cota ou teto de gasto esgotado **no provedor**, informado pela resposta da API); `limite_custo` é o teto **da sessão**, calculado pelo GeminiClaw. Os dois coexistem: se os dois ocorrem no mesmo ponto de verificação, vale `limite_custo`, porque é o limite que o pesquisador definiu.
- Custo `None` de um provedor (nenhuma chamada com preço) conta como 0 para o limite e como desconhecido para o relatório (`custo_recursos.chamadas_sem_custo`, já existente).

### 3.3 Preço desconhecido

Na inicialização da sessão, depois de resolvida a alocação de modelos por papel (`src/llm/allocation.py`), cada modelo alcançável pelo roteamento (os da alocação e os de reserva, como `GOOGLE_FALLBACK_MODEL` e equivalentes) com localidade diferente de `local` (ADR 019) e sem preço (`get_price` devolve `None`) faz a sessão não iniciar, com mensagem que cita o modelo e `LLM_PRICING_OVERRIDES`; no modo sem limite a verificação não se aplica. Modelos `local` têm custo 0 por definição. Durante a sessão, uma chamada não local sem preço (por exemplo, um modelo escolhido em tempo de execução fora da alocação e das reservas declaradas) emite `custo_nao_estimado` uma vez por modelo e segue; ver "Questões em aberto".

### 3.4 Aviso G5

`OPERATIONAL_THRESHOLDS["cost_usd"]` (US$ absolutos) dá lugar a `OPERATIONAL_THRESHOLDS["cost_usage_pct"]` (`OPERATIONAL_THRESHOLD_COST_USAGE_PCT`, padrão 0,80), percentual do orçamento efetivo de custo, omitido no modo sem limite (mesma regra de tokens e tempo).

## 4. Objetivo tipado do `Problema` (ADR 021 §5.2)

### 4.1 Formato de `criterio_sucesso`

```json
{
  "tipo": "limiar",
  "ao_atingir_objetivo": "parar",
  "metrica": "acuracia", "metrica_id": "...", "sentido": "maior_melhor",
  "alvo": 0.95, "delta_min": 0.01, "baseline_descricao": "classe majoritária",
  "hipoteses_concorrentes": [{"hipotese_id": "...", "predicao": "..."}],
  "definido_por": "pesquisador"
}
```

| Tipo | Campos obrigatórios | Campos proibidos |
|---|---|---|
| `limiar` | `metrica`, `sentido`, `delta_min`; `alvo` opcional | `hipoteses_concorrentes` |
| `discriminacao` | `hipoteses_concorrentes` com ao menos 2 itens, cada um com `predicao` não vazia | `alvo`, `delta_min` |
| `cobertura` | nenhum além de `tipo` | `alvo`, `delta_min`, `hipoteses_concorrentes` |
| `fronteira` | recusado nesta etapa (V19) | — |

`ao_atingir_objetivo` é opcional: ausente, vale `perguntar` no `assisted` e `parar` no `semi` e no `auto`. Só o pesquisador o define (confirmação do `Problema` ou `geminiclaw project objective <projeto> --ao-atingir parar|perguntar|continuar`); um valor vindo do plano é ignorado e registrado no evento `objetivo_definido` como `politica_ignorada`.

**Compatibilidade:** `criterio_sucesso` sem `tipo` (todos os `Problema` existentes) é lido como `limiar`; nada é reescrito.

**Validação na escrita:** `src/knowledge/validation.py` passa a validar a estrutura de `criterio_sucesso` pela tabela acima (enum de `tipo` e de `ao_atingir_objetivo`, campos por tipo). `fronteira` é aceito pelo schema (declarado), mas a confirmação do `Problema` e a aprovação do objetivo no plano o recusam com a mensagem "tipo `fronteira` ainda não suportado; será especificado com a V19 (equipamentos)".

### 4.2 Hipóteses concorrentes (`discriminacao`)

Cada item de `hipoteses_concorrentes` é uma `Hipotese` com `concorrente = true` e `predicao` (texto, até `HYPOTHESIS_TEXT_MAX_CHARS`). Na confirmação pelo pesquisador, os itens viram `Hipotese` com `origem = "pesquisador"`; propostos no plano do `auto` e aprovados pelo Validator, com `origem = "researcher"`. O Researcher pode acrescentar concorrentes depois, no plano (`"concorrente": true, "predicao": "..."` no item de `hipoteses`): no `auto`, valem depois da aprovação do plano; no `assisted` e no `semi`, a ampliação do conjunto é revisão do objetivo e vira pedido `confirmar_problema`.

### 4.3 Objetivo no plano (modo `auto`)

Envelope do plano ganha a chave opcional `objetivo` (`tipo`, `hipoteses_concorrentes` com `ref` e `predicao`, `justificativa`). No `limiar`, métrica, alvo e `delta_min` continuam vindo da chave `metricas` da V18.6. Regras:

- `ExplorationSession.objective_required` é verdadeiro no `auto` quando o `Problema` não tem objetivo válido (sem `tipo` e sem os campos do `limiar`, ou `tipo` inválido). Enquanto for verdadeiro, o prompt de planejamento traz a instrução `OBJECTIVE_DEFINITION_PLAN_INSTRUCTION` e um plano sem `objetivo` é reprovado de forma determinística, sem chamar o LLM.
- `ValidatorAgent.validate_plan(..., objective_definition=...)`: checagem determinística da tabela 4.1 e, pelo LLM, `objetivo_status` (`approved` | `revision_needed`) e `objetivo_issues`, na mesma chamada da validação do plano (sem chamada nova). A conversão em "aprova com avisos" por `PLAN_REJECTION_STALL_LIMIT` não vale quando o objetivo é exigido e não foi aprovado (mesma regra das métricas).
- Aprovado, o orquestrador grava `criterio_sucesso` com `definido_por = "agente"` e emite `objetivo_definido` (exibido ao pesquisador como evento). Um objetivo já válido e definido pelo pesquisador nunca é substituído pelo plano.
- No `assisted` e no `semi`, o objetivo é obrigatório na confirmação do `Problema` (terminal, antes da sessão, ADR 023 §1). Uma revisão proposta no plano não é aplicada: vira pedido `confirmar_problema` com a proposta.

## 5. Critérios por tipo (`src/knowledge/objective.py`)

Módulo puro sobre leituras do grafo (sem LLM). Interface:

```python
@dataclass(frozen=True)
class ObjectiveState:
    tipo: str                          # limiar | discriminacao | cobertura
    atingido: bool
    desfecho: str | None               # uma_compativel | todas_contrariadas | varias_compativeis | aguarda_experimento_fisico | None
    avanco: bool                       # houve avanço rumo ao objetivo neste ciclo
    saturacao: str                     # confirmada | nao_confirmada | nao_avaliavel | so_aviso
    detalhes: dict                     # valores usados (melhor valor, EP, réplicas, concorrentes...)

def evaluate(reader: ObjectiveReader, criterion: dict, previous: ObjectiveMemory, cycle: CycleView) -> ObjectiveState
```

`ObjectiveMemory` (melhor valor anterior, ciclos sem avanço, intervenções feitas, janela de novidade) vive em `ExplorationSession` e é gravada no checkpoint (`payload["exploracao_estado"]`) para a retomada.

Os nomes dos tipos, desfechos e motivos de parada são os da parte estruturada do regimento (ADR 022 §4.1, §5). Enquanto `v18.7-agent-system-prompts` não estiver mergeada, `objective.py` os declara como constantes; quando estiver, passa a lê-los de lá, e o teste de coerência daquela mudança cobre este módulo.

### 5.1 `limiar`

Resultados elegíveis: `Resultado` com `status_validacao = "validado"`, `MEDE` para a métrica principal do `Problema`, qualificador vazio ou `teste`, de `Experimento` com `papel` diferente de `referencia` (sem `papel` = `teste`, ADR 021 §9), de hipótese não abandonada pelo pesquisador. Sem filtro de veredito.

- **Atingido:** algum elegível satisfaz o `alvo` (quando definido) **e** supera a referência em `delta_min` (quando há referência: o baseline da tentativa, como hoje em `_meets_target`). Com só um dos dois definidos, vale o definido. Mudança em relação a hoje: com `alvo` e baseline, `_meets_target` só conferia o `alvo`.
- **Avanço:** o melhor valor elegível do ciclo supera o melhor anterior em mais que `SATURATION_SE_MULTIPLIER × EP`, onde `EP = s / √n` das réplicas da hipótese do melhor valor (`n ≥ 2`). Com `n < 2`, qualquer melhora validada é avanço, registrada com `avanco_sem_incerteza = true`.
- **Saturação:** confirmada quando a hipótese do melhor valor tem ao menos `SATURATION_MIN_REPLICATES` réplicas elegíveis e nenhuma melhora no período de estagnação passou de `SATURATION_SE_MULTIPLIER × EP`; com menos réplicas, `nao_avaliavel`.

Réplica: `Resultado` elegível de outro `Experimento` `teste` da mesma hipótese (nova seed, nova partição ou variação, ADR 021 §4.1).

### 5.2 `discriminacao`

- Plano: a subtarefa que distingue concorrentes declara `"discrimina": ["h1", "h2"]` (refs ou ids de concorrentes); a que exige bancada ou equipamento indisponível no sandbox declara `"experimento_fisico": true`. Ambos opcionais; ausência nunca reprova o plano.
- Revisão: para subtarefa com `discrimina` aprovada, o parecer do Validator da revisão traz `predicoes: [{"hipotese_id", "conferencia": "confirma"|"contraria"|"inconclusiva", "justificativa"}]`. Concorrente sem `predicao` declarada recebe `inconclusiva` de forma determinística. Itens para hipóteses fora de `discrimina` são descartados. A conferência só vale se o resultado for validado; fica em `Experimento.conferencia_predicoes`.
- Concorrente **contrariada**: ao menos uma conferência `contraria` validada. **Compatível**: ao menos uma `confirma` e nenhuma `contraria`.
- **Atingido** (`uma_compativel`): exatamente uma compatível e todas as demais contrariadas.
- **`todas_contrariadas`**: evento `objetivo_desfecho`, sem parada; o feedback do próximo plano pede hipóteses novas.
- **Avanço:** resultado validado do ciclo cujas conferências diferem entre ao menos duas concorrentes (uma `confirma`, outra `contraria`), ou que contraria uma concorrente ainda não contrariada.
- **Saturação:** nenhuma subtarefa na fila nem no último plano com `discrimina` cobrindo ao menos duas concorrentes não contrariadas, excluídas as `experimento_fisico`. Quando confirmada com duas ou mais compatíveis, o desfecho é `varias_compativeis` (pedido ao pesquisador em qualquer modo, sem parada automática).
- **`aguarda_experimento_fisico`:** quando a única subtarefa que distinguiria as restantes é `experimento_fisico`. A subtarefa não executa no sandbox (retirada com o código `experimento_fisico`, registrado, não é governança), o desfecho é registrado com a subtarefa proposta e vira pedido ao pesquisador; não conta como saturação.

### 5.3 `cobertura` (mínima)

- **Atingido:** só por decisão do pesquisador (resposta `objetivo_atingido` a um pedido, ou `geminiclaw project objective <projeto> --atingido`).
- **Avanço:** hipótese nova gravada no ciclo (não reutilizada pela deduplicação, `HYPOTHESIS_DEDUP_SIMILARITY`).
- **Saturação (só aviso):** média de hipóteses novas por ciclo nos últimos `COVERAGE_NOVELTY_WINDOW` ciclos `<= COVERAGE_NOVELTY_MIN_RATE` emite `cobertura_aviso` e um pedido ao pesquisador; a sessão não fecha por isso.

### 5.4 `fronteira`

Declarado no enum; recusado na confirmação e no plano (4.1). Nenhum critério implementado.

## 6. Política ao atingir o objetivo (ADR 021 §5.3)

Ao primeiro atingimento na sessão: evento `objetivo_atingido` (`tipo`, `desfecho`, valor e `resultado_id` no `limiar`, hipótese compatível no `discriminacao`, `politica`) e marco no `Problema` (`objetivo_atingido = {em, sessao_id, tipo, resultado_id|hipotese_id, valor}`, acrescentado à lista, nunca sobrescrito).

| Política | Efeito |
|---|---|
| `parar` | Fecha com `solucao_encontrada` (promoção de descobertas como hoje, `src/autonomous_loop.py:889-897`) |
| `perguntar` | Pedido `decidir_objetivo_atingido` (encerrar ou continuar); a sessão segue com o que não depende dele; `encerrar` fecha com `solucao_encontrada`; `continuar` passa a política efetiva da sessão a `continuar` |
| `continuar` | Segue (replicação, otimização além do alvo, hipóteses abertas) até limites, falta de caminho, pesquisador ou falha; estagnação e saturação deixam de valer na sessão |

O evento não se repete na mesma sessão para o mesmo `Problema`. Substitui `declined_solutions` e `terminal_solution_confirmer`.

## 7. Estagnação, intervenção e saturação (ADR 021 §5.5)

Ao fim de cada ciclo que executou algo (ciclos só de espera não contam, §9.2):

1. `state = objective.evaluate(...)`. Se `state.avanco`: `ciclos_sem_avanco = 0`, `intervencoes = 0`. Senão, `ciclos_sem_avanco += 1`.
2. Paciência: `ceil(EXPLORATION_STALL_CYCLES × (1 + EXPLORATION_PATIENCE_GROWTH × intervencoes) × (1 + f))`, com `f` a maior fração consumida entre os limites ativos (tokens, tempo, custo) e `f = 0` no modo sem limite. Exemplo: 5 ciclos, crescimento 0,5, 1 intervenção feita e 50% do custo gasto: `ceil(5 × 1,5 × 1,5) = 12`.
3. `ciclos_sem_avanco >= paciência` e `intervencoes < EXPLORATION_MAX_INTERVENTIONS`: **intervenção**. `curator_suggest(session_id, intervencao=StallContext)` com o que já foi tentado (abordagens, hipóteses e melhores valores, como dado delimitado) e o pedido de direções novas (abordagens não tentadas, hipóteses derivadas, diversificação); as sugestões entram pelo canal existente (`CURATOR_MAX_SUGGESTIONS`) e o Researcher responde a cada uma no plano seguinte (requisito existente "Sugestões do Curator e respostas obrigatórias"). No `assisted`, também um pedido `estagnacao` (continuar, orientar, parar). Evento `estagnacao_intervencao` (`intervencao`, `ciclos_sem_avanco`, `paciencia`, `sugestoes`). `intervencoes += 1`, `ciclos_sem_avanco = 0`.
4. `intervencoes >= EXPLORATION_MAX_INTERVENTIONS` e nova paciência esgotada sem avanço: avaliar `state.saturacao` (evento `saturacao_avaliada`).
   - `confirmada`: `auto` fecha com `saturacao`; `assisted` e `semi` registram pedido `saturacao` (continuar, orientar, parar) e seguem.
   - `nao_avaliavel` ou `nao_confirmada`: em qualquer modo, evento `intervencoes_esgotadas` e pedido `intervencoes_esgotadas`; a sessão segue.
   - `so_aviso` (`cobertura`): pedido `cobertura_saturada`; segue.
   - Resposta `continuar` ou `orientar` zera `intervencoes` e `ciclos_sem_avanco`; `orientar` entrega o texto ao Researcher no próximo plano como dado delimitado; `parar` fecha com `encerrada_pesquisador` (§10).
5. Política efetiva `continuar` com objetivo já atingido: os passos 1–4 não rodam.
6. `EXPLORATION_STALL_CYCLES = 0` desliga estagnação, intervenção e saturação (desligável sozinho, sem afetar os limites). O modo sem limite não os desliga.

A sessão não registra um segundo pedido do mesmo tipo enquanto o anterior estiver pendente.

## 8. Restrições de direção (ADR 021 §5.5, §6)

### 8.1 Registro

Nó `Restricao` (`direcao` texto, `categoria` em `seguranca`/`etica`/`recurso`, `abordagens` lista de nomes canônicos, `status` em `ativa`/`revogada`, `decidida_por = "pesquisador"`, `decidida_em`, `pedido_id`) com `(Restricao)-[:RESTRINGE]->(Problema|Projeto)`. A validação do grafo (`src/knowledge/validation.py`) aceita a criação ou a revogação só em dois caminhos: `Actor` pesquisador no processo do terminal (comandos, `pedido_id` vazio), ou o processo da sessão depois de `PersistentGate.consume_authorized("restringir_direcao", ...)` devolver o pedido autorizado e consumido, com `pedido_id` obrigatório e igual ao do pedido (parecer de segurança, item 2). O orquestrador sem pedido e os agentes são recusados; nada é apagado. O texto é indexado no índice semântico local (ADR 011).

Caminhos de criação: comando `geminiclaw project restrict <projeto> [--problema <id>] --direcao "<texto>" --categoria <c> [--abordagem <nome>]...` (processo do terminal); resposta `restringir` do pesquisador a um pedido `restringir_direcao` (motivo `restricao_duvidosa`, §10); pedido de agente por `ask_researcher` com `decisao_reservada = "restringir_direcao"`, que fica `pendente_pesquisador` (requisito existente). `geminiclaw project restrictions <projeto>` lista; `geminiclaw project unrestrict <restricao_id>` revoga (status `revogada`).

### 8.2 Aplicação

Em `prepare_cycle`, depois de gravar as hipóteses do plano e antes da seleção, cada hipótese referenciada é conferida contra as restrições ativas do `Problema` e do `Projeto`:

1. abordagem canônica da hipótese (ou da chave estruturada da hipótese do sistema) em `abordagens` → retirada, `criterio = "abordagem"`;
2. similaridade semântica entre `enunciado + abordagem` e `direcao` `>= RESTRICTION_SIMILARITY` → retirada, `criterio = "similaridade"`, com o valor.

A hipótese retirada vai a `abandonada`, `abandonada_por = "pesquisador"`, motivo `direcao_restrita:<restricao_id>` (revogar a restrição não a reabre). A gravação usa o `Actor` pesquisador derivado da `Restricao` (primeira saída do item 3 do parecer de segurança): o ator cita o `restricao_id`, e a validação só aceita a derivação quando a `Restricao` existe, tem `decidida_por = "pesquisador"` e `status = "ativa"`; em qualquer outra escrita a derivação é recusada, e a regra de autoridade de `v18.7-graph-exploration-relations` §2.3 continua fechada. Não há hoje comando de hipóteses na CLI (`src/cli*.py`); o pesquisador reabre a hipótese por `geminiclaw graph edit` (operação `update_node` proposta pelo Curator, confirmada no terminal e aplicada com `Actor(pesquisador)`, `src/knowledge/change_proposals.py`), que é o único caminho que pode tirar a hipótese de `abandonada_por = "pesquisador"` pela regra de autoridade de `v18.7-graph-exploration-relations`. A tarefa 7.4 testa esse caminho; um comando dedicado, se o pesquisador quiser, fica para mudança própria (Questão 8). As subtarefas que a testam saem com `hipotese_direcao_restrita`; dependentes seguem a regra de `depende_de_subtarefa_retirada` de `v18.7-hypothesis-linking`. Evento `restricao_retirada` por hipótese (`restricao_id`, `hipotese_id`, `criterio`, `similaridade`).

### 8.3 Validator

- **Plano:** recebe as restrições ativas como dado delimitado; devolve `restricoes_duvidosas: [{task_name, restricao_id, motivo}]`. Cada item vira pedido `restringir_direcao` com `motivo = "restricao_duvidosa"`; a subtarefa sai com `hipotese_aguarda_decisao_restricao` enquanto pendente. A resposta `restringir` cria a restrição; `liberar` deixa a subtarefa voltar no próximo plano.
- **Revisão:** recebe as restrições ativas; `viola_restricao: <restricao_id> | null`. Quando preenchido, o resultado não é validado (motivo `direcao_restrita` em `motivos`), a tentativa não é refeita e um pedido `restringir_direcao` (motivo `restricao_duvidosa`) é registrado.

Risco residual (ADR 021 §5.5): a verificação é sobre o plano e sobre o executado, não um bloqueio dentro do sandbox.

## 9. Proteções contra falha (ADR 021 §5.6)

### 9.1 Disjuntor

`CycleProgress` passa a ter `experiments: int`, `results: int` (contagem de `Experimento` com `EXECUTADO_EM` a sessão e de `Resultado` desses experimentos, lida do grafo ao fim do ciclo) e `failure_signatures`. `advanced_from`: `experiments` ou `results` cresceram, ou as assinaturas mudaram. Replicação com o mesmo `task_name` gera `Experimento` novo e conta. Sessões sem projeto (laço da V17) mantêm a regra antiga por nomes. `CIRCUIT_BREAKER_STALL_CYCLES` continua (padrão 2).

### 9.2 Espera do gate

Ciclo em que todas as subtarefas novas foram retiradas só por pedido pendente (`hipotese_aguarda_aprovacao`, `hipotese_aguarda_decisao_restricao`) ou em que só restam pedidos pendentes: não incrementa `idle_cycles`, `ciclos_sem_avanco` nem o disjuntor. O que acontece depois é de `v18.7-persistent-human-gate` e `v18.7-background-sessions` (ADR 023 §4.4: `semi` e `auto` passam a `aguarda_pesquisador` e encerram o processo; `assisted` com terminal aberto espera). As duas são mergeadas antes desta mudança, então o comportamento atual (`_suspend_session`) não é usado por ela.

### 9.3 Planos rejeitados

`rejected_plans >= MAX_PLAN_RETRIES`: `auto` fecha com `planos_rejeitados` (como hoje). `assisted` e `semi`: pedido `decidir_continuidade` com motivo `planos_rejeitados` (continuar, orientar, parar) com as últimas `issues`; sem outro trabalho, a sessão espera conforme 9.2; `continuar`/`orientar` zera `rejected_plans`; `parar` fecha com `planos_rejeitados`.

## 10. Pedidos ao pesquisador

Esta mudança só produz pedidos; a persistência, a resposta pelo terminal e o estado da sessão são de `v18.7-persistent-human-gate`, que é a dona do catálogo (coluna `decisao`, com `CHECK`, e `DECISOES_RESERVADAS`). Interface usada: `PersistentGate.request(decisao, referencia, pergunta, opcoes, *, motivo, session_id, project_id)`, `pending(...)`, `answered_unconsumed(...)` e `mark_consumed(...)` (design §2.3 daquela mudança). Não há invólucro próprio (`submit(kind, ...)`): os nomes abaixo são os gravados no banco. O `motivo` distingue os pedidos que compartilham uma `decisao`; a `referencia` inclui o motivo para que o índice único de pendentes (`session_id`, `decisao`, `referencia`) não junte pedidos de motivos diferentes.

| `decisao` | `motivo` | Opções (`opcoes`) | Origem |
|---|---|---|---|
| `decidir_objetivo_atingido` | (vazio) | `encerrar`, `continuar` | §6 (política `perguntar`) |
| `decidir_continuidade` | `estagnacao` | `continuar`, `orientar`, `parar` | §7 passo 3 (`assisted`) |
| `decidir_continuidade` | `saturacao` | `continuar`, `orientar`, `parar` | §7 passo 4 (`assisted`, `semi`) |
| `decidir_continuidade` | `intervencoes_esgotadas` | `continuar`, `orientar`, `parar` | §7 passo 4 |
| `decidir_continuidade` | `cobertura_saturada` | `continuar`, `orientar`, `parar`, `objetivo_atingido` | §5.3 |
| `decidir_continuidade` | `varias_compativeis` | `aceitar_conjunto`, `continuar`, `orientar`, `parar` | §5.2 |
| `decidir_continuidade` | `aguarda_experimento_fisico` | `continuar`, `orientar`, `parar` | §5.2 |
| `decidir_continuidade` | `planos_rejeitados` | `continuar`, `orientar`, `parar` | §9.3 |
| `restringir_direcao` | `restricao_duvidosa` | `restringir`, `liberar` | §8.3 |
| `confirmar_problema` | `revisao_objetivo` | `autorizar`, `negar` | §4.3 (revisão do objetivo) |

`aceitar_conjunto` e `objetivo_atingido` fecham com `solucao_encontrada`. `parar` fecha com `encerrada_pesquisador` (motivo de `v18.7-background-sessions`), exceto no motivo `planos_rejeitados`, em que fecha com `planos_rejeitados`. Nos cenários das specs desta mudança, "pedido `<motivo>`" designa a linha desta tabela com esse motivo.

## 11. Motivos de parada, retomada e benchmark

- `StopReason.COST = "limite_custo"`; `ExplorationStop.SATURATION = "saturacao"`; `StopReason.RUNS` e `ExplorationStop.CYCLES` saem do código. O enum de `Sessao.motivo_parada` acrescenta os dois novos e mantém `limite_ciclos` e `limite_execucoes` (dados antigos; `MOTIVOS_PARADA` da validação de checkpoint deriva do enum).
- Compatibilidade com `v18.7-benchmark-fixes` (mergeada antes desta): `limite_cota_provedor` permanece em `StopReason`, no enum de `Sessao.motivo_parada`, em `MOTIVOS_RETOMAVEIS`, em `describe_stop_reason` e em `stop_class` (classe `limite`).
- Dono de cada motivo de parada novo da V18.7: `limite_cota_provedor` (`v18.7-benchmark-fixes`); `limite_custo` e `saturacao` (esta mudança); `aguarda_pesquisador`, `suspensa_sem_pesquisador` e `encerrada_pesquisador` (`v18.7-background-sessions`); `pausada_pesquisador` (`v18.7-session-events-terminal`). O código de saída do comando direto de cada um está na tabela única de `v18.7-background-sessions` (design §1.4): `limite_custo` → 3 (limite); `saturacao` → 0 (parada de pesquisa).
- `MOTIVOS_RETOMAVEIS` ganha `limite_custo` e mantém os antigos. `saturacao` → `RESUME_CONFIRM` com a mensagem "a exploração saturou (saturacao): a melhora possível ficou abaixo do erro da medida; continuar explorando?".
- `describe_stop_reason` ganha `limite_custo` e `saturacao`.
- Benchmark: `stop_class` ganha os casos explícitos (`limite_custo` → `limite`; `saturacao` → `criterio_pesquisa`; `limite_ciclos` e `limite_execucoes` continuam `limite` em resultados antigos). A matriz declara `SESSION_MAX_COST_USD` em `env`; o runner recusa a matriz sem ele, antes de qualquer execução.

## 12. Variáveis removidas

O mecanismo é de `v18.7-resource-monitor-config` (design §1.5 daquela mudança): `_REMOVED_VARIABLES` (nome → mensagem fixa ou função do valor) e `check_removed_variables(environ)`, chamada no fim da importação de `src/config.py`, depois de carregar o `.env`, que levanta `ConfigurationError` (subclasse de `RuntimeError`) listando todos os nomes encontrados. Esta mudança só acrescenta itens ao dicionário. Mensagens: `HYPOTHESES_PER_CYCLE`, `MAX_EXPLORATION_CYCLES`, `MAX_AGENT_RUNS_PER_SESSION`, `MAX_CONTAINERS_PER_SESSION`, `MAX_PLANNING_RUNS_PER_SESSION`, `OPERATIONAL_THRESHOLD_AGENT_RUNS_PCT`, `OPERATIONAL_THRESHOLD_CONTAINER_COUNT_PCT`: "removida pelo ADR 021 §5.1; a exploração não tem teto de hipóteses, ciclos ou execuções; use os limites de custo, tokens e tempo; remova a linha". `SOLUTION_MIN_VERDICT`: "removida pelo ADR 021 §5.2; a parada usa o objetivo do Problema; remova a linha". `OPERATIONAL_THRESHOLD_COST_USD`: "substituída por OPERATIONAL_THRESHOLD_COST_USAGE_PCT (percentual do limite de custo)".

`MAX_PLANNING_RUNS_PER_SESSION`: o ADR 021 §5.1 não a nomeia, mas decide "sem teto de hipóteses nem de ciclos", e o cabeçalho do ADR 021 (mudança no ADR 015 §8) elimina `limite_execucoes` como motivo de parada, que é o motivo com que esse teto fecha hoje (`src/orchestrator.py:1848`, `src/autonomous_loop.py:1023-1027`). Como há ao menos uma execução de planejamento por ciclo, o teto de planejamento é um teto de ciclos (alternativa H, rejeitada). Por isso sai junto; o contador continua relatado em `custo_recursos.execucoes_agente.planejamento`. A confirmação do pesquisador está registrada na Questão 6.

## 13. Configuração

| Variável | Padrão | Regra |
|---|---|---|
| `SESSION_MAX_COST_USD` | `10.0` | > 0; ≤ 0 ou vazio falha na inicialização (desligar só pelo modo sem limite) |
| `SESSION_MAX_COST_USD_BY_PROVIDER` | vazio (só o total) | `provedor=valor,...`, valores > 0 |
| `OPERATIONAL_THRESHOLD_COST_USAGE_PCT` | `0.80` | em (0, 1] |
| `EXPLORATION_STALL_CYCLES` | `5` | inteiro ≥ 0; 0 desliga estagnação, intervenção e saturação |
| `EXPLORATION_MAX_INTERVENTIONS` | `3` | inteiro ≥ 1 |
| `EXPLORATION_PATIENCE_GROWTH` | `0.5` | ≥ 0 |
| `SATURATION_MIN_REPLICATES` | `3` | inteiro ≥ 2 |
| `SATURATION_SE_MULTIPLIER` | `1.0` | > 0 |
| `COVERAGE_NOVELTY_WINDOW` | `5` | inteiro ≥ 1 |
| `COVERAGE_NOVELTY_MIN_RATE` | `0.2` | ≥ 0 (hipóteses novas por ciclo) |
| `RESTRICTION_SIMILARITY` | `0.80` | em (0, 1] |

Mantidas: `SESSION_MAX_TOKENS`, `SESSION_MAX_MINUTES`, `EGRESS_SESSION_MAX_BYTES`, `SESSION_MAX_TASK_RETRIES`, `SESSION_MAX_CONNECTION_RETRIES`, `MAX_PLAN_RETRIES`, `CIRCUIT_BREAKER_STALL_CYCLES`, `DECISION_EVAL_MIN_VERDICT`, `HYPOTHESIS_DEDUP_SIMILARITY`, `CURATOR_MAX_SUGGESTIONS`. O valor padrão de `SESSION_MAX_COST_USD` é provisório (ver "Questões em aberto").

## 14. Análise de impacto (6 eixos)

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Alto | Saem três condições de parada; entram custo, objetivo por tipo, política, estagnação com intervenção, saturação, restrições; disjuntor por grafo; espera do gate fora dos contadores; checkpoint do estado da exploração |
| Agentes & Prompts | Médio | Researcher: chave `objetivo` (no `auto`), campos `discrimina`, `experimento_fisico`, `concorrente`, `predicao`; Validator do plano: objetivo e restrições duvidosas; Validator da revisão: `predicoes` e `viola_restricao`; Curator: contexto de intervenção. Os textos finais vêm de `v18.7-agent-system-prompts` |
| Sandboxes & Containers | Nenhum | `experimento_fisico` nunca chega ao sandbox |
| Persistência de Estado | Médio | Schema aditivo do grafo (nó `Restricao`, `RESTRINGE`, propriedades, enum); `payload["budget"]` com custo; `payload["exploracao_estado"]` no checkpoint |
| Segurança & Hardening | Médio | Limite de custo contra gasto sem fim; restrições como regra persistente só do pesquisador; política de parada fora do alcance dos agentes; variáveis antigas falham em vez de serem ignoradas |
| Testes & Telemetria | Médio | Eventos novos; leitores de custo injetáveis; grafo em memória; Validator e Curator simulados |

## 15. Segurança

- **Gasto sem fim:** o limite de custo vale por padrão; desligá-lo exige a confirmação do modo sem limite (spec `operation-metrics`), nunca `0` ou vazio no `.env` (ADR 021, rejeitada L). Modelo não local sem preço impede o início.
- **Agente afrouxando a parada:** `ao_atingir_objetivo` só é definida pelo pesquisador; no `auto`, o objetivo do agente só vale depois do Validator, de família diferente da do Developer (ADR 020), e nunca substitui o do pesquisador; o adendo de projeto (ADR 022 §4.4) só restringe.
- **Restrições:** criadas e revogadas só por ação do pesquisador no processo do terminal; agentes não escrevem `Restricao` (barreira de validação); o texto da direção e as justificativas do Validator são dado delimitado nos prompts, nunca instrução. As retiradas por similaridade são auditáveis (evento por hipótese, listagem no relatório por `v18.7-exploration-metrics`).
- **Injeção pelo plano:** `discrimina`, `experimento_fisico`, `predicao` e `objetivo` são texto de LLM: tamanho limitado, saneados por `clean_free_text`, refs resolvidos contra o registro, valores inválidos descartados e contados.
- **Dados de pesquisa:** o contexto de intervenção do Curator leva nomes de abordagens, hipóteses e valores de métricas já validados (mesma classe de dado do feedback de hoje), sob os filtros de egresso.

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.**

1. **Médio: campos do pesquisador protegidos no grafo.** Só o `Actor` pesquisador grava ou altera `ao_atingir_objetivo` e `definido_por = "pesquisador"` em `criterio_sucesso`. A regra fica em `src/knowledge/validation.py`, pelo mesmo mecanismo de `HUMAN_ONLY_TRANSITIONS`, e não apenas na lógica do orquestrador. Um teste usa os actors `orquestrador` e `agente`.
2. **Médio: `Restricao` só por decisão humana verificável.** Criar ou revogar uma restrição exige o `Actor` pesquisador (comando do terminal). No processo da sessão, exige um pedido `restringir_direcao` autorizado e consumido no gate persistente, e nesse caminho `pedido_id` é obrigatório. Um teste confere que o orquestrador sem pedido é recusado.
3. **Baixo: coerência com `v18.7-graph-exploration-relations` §2.3.** A retirada por restrição grava `abandonada_por = "pesquisador"` pela sessão. É preciso definir uma de duas saídas. Na primeira, a gravação usa o `Actor` pesquisador derivado da `Restricao`, citando um `restricao_id` com `decidida_por = "pesquisador"`. Na segunda, a retirada usa um valor próprio. Sem isso, a barreira do grafo recusa a gravação, ou acaba aberta a outros caminhos.
4. **Baixo: preço desconhecido.** A verificação de início cobre todos os modelos alcançáveis pelo roteamento, inclusive os de reserva (`GOOGLE_FALLBACK_MODEL` e equivalentes). O limite de tokens continua como rede de segurança.
5. **Informativo: recursos no Pi.** Sem teto de ciclos, a parada depende dos limites de custo, tokens e tempo, e o modo sem limite remove os três. A confirmação desse modo diz que, no `auto`, a sessão pode rodar indefinidamente e que só `wait_for_health` e `SANDBOX_MIN_FREE_BYTES` protegem o hardware.

Rastreio dos itens nas specs e tarefas: item 1 no requisito "Campos do pesquisador no objetivo protegidos no grafo" (`specs/knowledge-graph`, tarefa 2.5); item 2 no requisito "Restrição de direção como nó" (`specs/knowledge-graph`) e em `specs/researcher-consult` (tarefa 7.5); item 3 no requisito "Abandono por restrição com autoridade da restrição" (`specs/knowledge-graph`, primeira saída, tarefa 7.5); item 4 no requisito "Modelo sem preço impede o início" (`specs/usage-limits`, tarefa 3.5); item 5 no requisito "Modo sem limite explícito" (`specs/operation-metrics`, tarefa 3.5).

## 16. Riscos e mitigações

| Risco | Severidade | Mitigação |
|---|---|---|
| Sessão gasta muito sem atingir o objetivo | Alta | Limite de custo padrão; avisos G5 por percentual; disjuntor; estagnação com intervenção; saturação no `auto` |
| Validator aprova resultado errado e encerra cedo (ADR 021, Consequências) | Média | Independência de família (ADR 020); verificação de afirmações; política `perguntar` disponível ao pesquisador |
| Saturação nunca avaliável (poucas réplicas) | Média | Pedido `intervencoes_esgotadas` em todos os modos; confirmação do modo sem limite avisa que não há parada garantida |
| Restrição por similaridade retira hipótese legítima | Média | Limiar configurável; evento por retirada; listagem no relatório; pesquisador reabre por `graph edit` (§8.2) |
| Pedidos acumulados sem resposta | Baixa | Um pedido por tipo pendente; ciclos de espera não contam; `aguarda_pesquisador` (ADR 023) |
| `.env` antigos param de iniciar | Baixa | Mensagem por variável com a ação; migração do `.env.example` e do Pi na mesma onda |
| Conflito de edição em `prepare_cycle`, `select` e `schema.py` com `v18.7-hypothesis-linking` e `v18.7-graph-exploration-relations` | Média | Ordem fixa: as duas são mergeadas antes desta. Divisão: `v18.7-graph-exploration-relations` é dona das propriedades do ADR 021 §2-§4 em `schema.py`; esta mudança, só de `Restricao`, `RESTRINGE`, `Problema.objetivo_atingido`, `Hipotese.predicao`/`concorrente`, `Experimento.conferencia_predicoes` e dos motivos `limite_custo`/`saturacao`; `v18.7-hypothesis-linking` é dona da ordem de `prepare_cycle`, das retiradas do §6 e de `select` aceitar concluídas; esta mudança, do fim do teto em `select` e da conferência de restrições em `prepare_cycle` |

## 17. Questões em aberto

1. **Calibração do veredito e de `SOLUTION_MIN_VERDICT`.** O filtro sai da parada (ADR 021 §5.2, rejeitada J). Se algum limiar de veredito volta a ter papel (por exemplo, um aviso de "objetivo atingido com evidência fraca"), e os pesos `d`, `m` e `DECISION_EVAL_MIN_VERDICT`, ficam para a calibração da Etapa 2, decisão do pesquisador. Esta mudança não define nenhum substituto.
2. **Direção `o` do veredito a partir da predição nos tipos sem alvo** (cabeçalho do ADR 021, ADR 015 §9) e termo `m` neutro: não estão na tabela de mudanças do ADR 021. Esta mudança grava as conferências de predição (necessárias à parada do `discriminacao`), mas não altera `src/knowledge/verdict.py`. Proposta: incluir na calibração da Etapa 2 ou numa mudança `evidence-scoring` própria; decisão do pesquisador.
3. **Valor padrão de `SESSION_MAX_COST_USD`.** Proposto US$ 10 por sessão (a bateria V18.6 gastou até US$ 14 por provedor e rodada em quatro combinações). O valor é decisão do pesquisador.
4. **Chamada não local sem preço durante a sessão.** Proposto: segue com evento `custo_nao_estimado` (a verificação de início já cobre a alocação declarada). Alternativa mais conservadora: fechar com `limite_custo`. Decisão do pesquisador.
5. **Limiares de saturação e de novidade** (`SATURATION_MIN_REPLICATES`, `SATURATION_SE_MULTIPLIER`, `COVERAGE_NOVELTY_*`): os padrões são iniciais e entram na calibração da Etapa 2.
6. **`MAX_PLANNING_RUNS_PER_SESSION`.** Mantida a remoção, pelo ADR 021 §5.1 (sem teto de ciclos) e pela eliminação de `limite_execucoes` como motivo no cabeçalho do ADR 021 (justificativa no §12). O nome não aparece no texto do ADR: se o pesquisador preferir manter um teto de planejamento, ele precisa de um motivo de parada novo e de emenda ao ADR 021; a proposta é não manter.
7. **Catálogo de pedidos** (§10): alinhado em 2026-10-15 com `v18.7-persistent-human-gate` (três decisões com `motivo`, opções por motivo). Resta a escolha do pesquisador entre esse agrupamento e uma `decisao` por motivo (Questão 5 daquela mudança); a tabela do §10 muda junto.
8. **Reabertura de hipótese retirada por restrição revogada:** proposto não reabrir automaticamente; o pesquisador reabre por `graph edit` (§8.2). Confirmar, e decidir se quer um comando dedicado de hipóteses (mudança própria).
