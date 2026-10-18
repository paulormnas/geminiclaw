# ADR 021 — Exploração Rastreável por Hipóteses: Estrutura dos Nós e Governança por Registro

**Status:** Parcialmente implementado (2026-10-17; aprovado em 2026-10-15)
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md` (criado junto com as mudanças OpenSpec)
**ADRs relacionados:** ADR 010 (assistente de pesquisa), ADR 012 (Curator e ciclo de exploração), ADR 015 (modelo de dados do grafo), ADR 020 (independência do Validator), ADR 022 (contrato de contexto por chamada), ADR 023 (pesquisa em segundo plano)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 015 §2 | `Experimento` ganha a propriedade `papel` (`teste` / `preparacao` / `referencia`). |
| 015 §4 | `Hipotese.origem` ganha o valor `sistema`; `Hipotese` ganha a chave estruturada `(problema, abordagem, metrica)` para hipóteses do sistema, a referência R fixada e `abandonada_por`; as transições de status passam a valer também para hipóteses concluídas (§4.4). |
| 015 §4 (`Problema`) | `criterio_sucesso` ganha `tipo` (`limiar`, `discriminacao`, `cobertura`, `fronteira`) e `ao_atingir_objetivo`; os campos passam a depender do tipo (alvo e `delta_min` só no `limiar`; hipóteses concorrentes e predições no `discriminacao`). |
| 015 §9 (veredito) | Nos tipos sem alvo, a direção `o` de cada evidência vem da predição declarada da hipótese, conferida pelo Validator contra o resultado aprovado (confirma: `o = +1`; contraria: `o = −1`); sem predição declarada, a tentativa conta como inconclusiva (§9.3). O termo de magnitude `m` usa o valor neutro já usado sem baseline. Ambos revistos na calibração da Etapa 2. O veredito continua sendo medida de confiança: a parada do `discriminacao` usa as evidências validadas, não o valor do veredito (§5.2). |
| Spec `research-project` | O rascunho do Problema passa a ter o tipo de objetivo; `delta_min` só é exigido no `limiar`. |
| 012 §8 / spec `researcher-consult` | Nova decisão reservada `restringir_direcao` (§5.5). |
| 015 §5 | Novas relações `PREPARA` e `REFERENCIA_DE`; o destino de `DERIVADA_DE` passa a aceitar `Hipotese`. |
| Spec `curator` | O requisito "Veredito calculado sem LLM" passa a recalcular também hipóteses concluídas, com os efeitos do §4.4 sobre oportunidades, decisões e atalhos. |
| 015 §8 (emenda de 2026-10-08, motivos de parada) | `limite_ciclos` e `limite_execucoes` deixam de existir como motivos; entram `limite_custo` e `saturacao`; `solucao_encontrada` passa a vir do critério do tipo de objetivo (no `limiar`, resultado aprovado pelo Validator que atinge o alvo, sem o filtro de veredito), e respeita a política `ao_atingir_objetivo` (§5.2–§5.5). |
| 012 | O Curator passa a ver as hipóteses `origem=sistema` e pode sugerir reformulação ao Researcher pelo canal de sugestões existente (não há fusão de hipóteses pelo Curator). |
| Spec `hypothesis-loop` | A exigência "cada subtarefa referencia a hipótese que testa" vira registro; a retirada por `sem_hipotese` deixa de existir; `HYPOTHESES_PER_CYCLE`, o teto de ciclos e o filtro `SOLUTION_MIN_VERDICT` saem (cenários "Modo autônomo", "Teto de ciclos" e o critério de solução); hipóteses concluídas podem receber novos testes. |
| Spec `agent-runtime` | O circuit breaker por `MAX_AGENT_RUNS_PER_SESSION` deixa de encerrar a sessão (§5.1). |
| Spec `operation-metrics` | O modo sem limite passa a cobrir também o limite de custo; a regra de ativação só por confirmação do pesquisador continua (§5.4). |
| Spec `pipeline-robustness` | O cenário "Baseline sem hipótese" passa a ser `papel = referencia`. |
| Spec `operation-metrics` | `reprovacoes_sem_hipotese` dá lugar a contadores de ligação derivada (§8). |

---

## Contexto

### O que a bateria V18.6 mostrou (2026-10-15)

A bateria com 4 combinações × 3 repetições no Pi 5 terminou com as 12 execuções em `exit 0` (relatório em `docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md`), mas com dois padrões:

1. **Planos esvaziados pela governança.** Nas 6 execuções com Claude como Researcher/Developer, a sessão fechou em 4 a 12 minutos sem treinar modelo (acurácia nula, `sem_mede`). A cadeia é sempre a mesma: o Researcher declara hipóteses (h1, h2…) e as liga às subtarefas de treino; o pré-processamento e o baseline ficam sem `hypothesis_ref`, porque não testam nada; `prepare_cycle` (`src/exploration.py:374-377`) os retira por `sem_hipotese`; todas as subtarefas dependem do pré-processamento e caem em cascata como `depende_de_subtarefa_retirada`; só a EDA executa; depois de 2 ciclos ociosos a sessão fecha como `hipoteses_nao_testadas`.
2. **Regras que se contradizem.** O prompt do Researcher diz que só "subtarefas que testam uma hipótese" precisam de `hypothesis_ref` e que "preparação (eda) ou síntese" podem omiti-lo (`src/exploration.py:108-109`); o código (`_is_bound`, `src/exploration.py:295-308`) exige hipótese de toda subtarefa do Developer que não seja `eda` ou `synthesis`; o prompt do Validator do plano diz que `hypothesis_ref` é opcional e "nunca é motivo de reprovação" (`src/agents/validator_agent.py:95-96`). O Researcher não é informado das retiradas e reenviou o mesmo plano três vezes. O campo `hypothesis` da EDA ("Não se testa hipótese; produz o diagnóstico…") ainda virou nó `Hipotese` `em_teste`.

As execuções com Gemini como Researcher não esvaziaram porque o Gemini agrupa o trabalho em subtarefas grandes: o Claude planeja em passos finos e esbarra na regra.

### O que outros sistemas fazem

Os sistemas agênticos de pesquisa revisados convergem num padrão: **gerar com liberdade, registrar tudo de forma estruturada e verificar com rigor**. AIDE (arXiv:2502.13138) e AIRA-dojo (arXiv:2507.02554) rastreiam a exploração como uma árvore de soluções em código (rascunhar, depurar, melhorar) e deixam a métrica decidir; o AI Scientist v2 (arXiv:2504.08066) usa busca em árvore conduzida por um gerente de experimentos; o Curie (arXiv:2502.16069) põe o rigor em módulos que verificam o que foi feito; o Co-Scientist (Nature 655, 2026; arXiv:2502.18864) faz das hipóteses o objeto central e as governa por ranking, não por bloqueio.

### Decisões do pesquisador (2026-10-15)

Hipóteses rejeitadas pelo pesquisador não devem ser executadas.

Uma exploração não surge do nada. Pode ser uma nova abordagem, mas está conectada à solução de um problema. Mesmo no caso de testar uma nova ideia, existe uma hipótese do tipo "essa nova arquitetura ou esse novo método de treinamento trazem resultados melhores?". Talvez uma reorganização na estrutura de como os nós se conectam faça mais sentido do que ter nós soltos.

---

## Decisão

### 1. Princípio

**Toda execução se liga a um `Problema`, e todo teste se liga a uma `Hipotese`; a ligação é registrada, não exigida como condição para executar.** O que impede uma execução é uma decisão humana ou uma regra de integridade (§6), nunca a falta de um campo no plano nem um teto de seleção. Quando o plano não declara a ligação, o sistema a deriva (§3) e registra que a derivou.

### 2. Três papéis de `Experimento`

Cada subtarefa executada continua gerando um `Experimento` (ADR 015 §2), agora com a propriedade `papel`:

| Papel | O que é | Exemplos | Liga-se a |
|---|---|---|---|
| `teste` | Mede algo que uma hipótese afirma | treinar e avaliar um modelo; comparar abordagens | `(Experimento)-[:TESTA]->(Hipotese)` |
| `preparacao` | Produz insumo para outros experimentos, ou caracteriza o problema; não afirma nada sozinho | EDA, limpeza, divisão treino/teste, engenharia de atributos, síntese final | `(Experimento)-[:PREPARA]->(Hipotese \| Problema)` |
| `referencia` | Mede o ponto de comparação do Problema | baseline (classe majoritária, modelo de referência do artigo) | `(Resultado)-[:REFERENCIA_DE]->(Problema)` |

**Como o papel é decidido**, nesta ordem:

1. **Declarado no plano.** O formato do plano ganha o campo `papel` por subtarefa; o Researcher é instruído a declará-lo (as regras vêm da fonte única do ADR 022 §5). A ausência do campo nunca é motivo de reprovação do plano.
2. **Com `hypothesis_ref` resolvível** → `teste`.
3. **`task_type` `eda` ou `synthesis`** → `preparacao`, sempre.
4. **Sem `hypothesis_ref`, com sinal de teste** → `teste` com hipótese derivada (§3.3), **mesmo que outras subtarefas dependam dela** (um `treinar_rf` que alimenta `comparar_modelos` é teste). Sinal de teste: um critério de validação com limiar numérico sobre a **métrica principal M do Problema** (a mesma da hipótese derivada, §3.3), ou `abordagem` com `tipo = "algoritmo"`. Limiares sobre outras grandezas ("proporção de nulos <= 0", que o Validator do plano costuma pedir) não bastam. Só a `abordagem` de outro tipo (por exemplo `protocolo`) não basta: alguns modelos a preenchem em todas as subtarefas, inclusive na EDA (`src/exploration.py:298-301`).
5. **Sem `hypothesis_ref`, sem sinal de teste, com subtarefas que dependem dela** → `preparacao`. Esta regra estrutural cobre o pré-processamento e a divisão treino/teste, seja qual for o `task_type`.
6. **Qualquer outro caso** → `preparacao` ligada ao `Problema`, com o fato registrado. Na dúvida, o sistema não inventa hipótese.

O papel `referencia` só vem da declaração no plano (regra 1): o sistema não tenta adivinhar o que é baseline. Um baseline não declarado e com limiar nos critérios cai na regra 4 e vira `teste` de uma hipótese do sistema, que tende a ser refutada (o baseline não supera a referência): é evidência negativa legítima e executa normalmente; o Researcher recebe a indicação de que poderia declará-lo como referência (§7).

### 3. Ligações derivadas pelo sistema

1. **Preparação → hipóteses que ela serve.** O destino de `PREPARA` sai do DAG: a preparação liga-se a toda hipótese testada por um experimento que dependa dela, direta ou transitivamente. A derivação roda **depois** da validação do DAG (ciclos e dependências inexistentes já rejeitados pelo `task_scheduler`) e é **incremental sobre o grafo**: quando um teste de um ciclo posterior depende de uma preparação já concluída, a aresta `PREPARA` é acrescentada ao `Experimento` existente. Sem nenhuma hipótese dependente, a preparação liga-se ao `Problema`.
2. **Referência → `Problema`.** O resultado de um experimento `referencia` liga-se ao `Problema` por `REFERENCIA_DE`. **Neste ADR o valor medido é registrado, não entra no veredito**: a fórmula (ADR 015 §9) continua usando o baseline como hoje; usar o valor medido como entrada de `m` é decisão da calibração (Etapa 2).
3. **Teste sem hipótese declarada → hipótese de melhoria do sistema.** Uma subtarefa `teste` (regra 4 do §2), ou com `hypothesis_ref` que o registro não aceita por falha de formato (`id_inexistente`, `sem_enunciado`), não é retirada: o sistema cria uma `Hipotese` com `origem = "sistema"` no formato "*a abordagem A melhora a métrica M do Problema P em relação à referência R*":
   - M é a métrica principal aprovada do Problema;
   - R é **fixada na criação** e registrada na hipótese (valor e origem): o resultado medido de `referencia` do Problema, se existir; senão, o baseline do critério do Problema. R não muda durante a sessão. A comparação com o melhor resultado até então é registrada à parte, como informação, e não define o veredito;
   - a hipótese tem `SOBRE->Problema` e `PROPOE->Abordagem`;
   - o evento do ciclo registra `hipotese_derivada` com a subtarefa e o motivo.
4. **Deduplicação estruturada.** Hipóteses do sistema são deduplicadas pela chave `(problema, abordagem canônica, metrica)`, não pela similaridade de texto (que fundiria enunciados que só diferem no nome da abordagem). A deduplicação por similaridade (`HYPOTHESIS_DEDUP_SIMILARITY`) continua valendo para as hipóteses declaradas.
5. **Ciclo de vida.** A hipótese do sistema existe por causa da subtarefa que a originou: se essa subtarefa for retirada (§6), sair da fila num replanejamento (§5.8) ou esgotar as tentativas sem nenhuma execução, a hipótese vai a `abandonada` com `abandonada_por = "sistema"` e o motivo, em vez de ficar `em_teste` sem tentativa (o que manteria caminhos "abertos" sem trabalho real e levaria a `hipoteses_nao_testadas`). **O abandono pelo sistema não bloqueia:** quando um plano posterior traz a mesma chave estruturada (§3.4), a hipótese volta a `em_teste` com o histórico preservado. Só o abandono pelo pesquisador (`abandonada_por = "pesquisador"`) impede novos testes e a reabertura.
6. **Aprovação.** No modo `assisted` (o sistema trabalha em parceria com o pesquisador), a hipótese do sistema aguarda a aprovação dele, como as hipóteses dos agentes. Nos modos `semi` e `auto`, segue por decisão dos agentes: a proposta do Researcher e a aprovação do plano pelo Validator bastam (decisão do pesquisador, 2026-10-15).
7. **Curator.** Hipóteses `origem = "sistema"` aparecem para o Curator (ADR 012), que pode sugerir ao Researcher uma formulação melhor pelo canal de sugestões já existente. O Curator não funde hipóteses.

### 4. Variações, derivações e replicação

1. **O sistema não deriva hipótese para variação.** Mudar hiperparâmetros, normalização, seed ou partição dentro da mesma abordagem é um novo `Experimento` `teste` da **mesma** hipótese, com a configuração na aresta `APLICOU {config}` (ADR 015 §5). O Researcher continua livre para declarar uma hipótese própria sobre um mecanismo ("padronizar melhora o kNN"), ligada à anterior por `DERIVADA_DE`.
2. **Hipótese derivada.** Uma hipótese que refina ou contrapõe outra liga-se a ela por `(Hipotese)-[:DERIVADA_DE]->(Hipotese)`. O grafo mostra a árvore da exploração: Problema → hipóteses → hipóteses derivadas → experimentos → resultados.
3. **Hipótese concluída aceita novos testes.** Uma hipótese `validada` ou `refutada` pode receber novos testes (replicação, nova seed, nova partição, variação), e o veredito é recalculado com todas as evidências, **inclusive para baixo**: uma replicação que falha pode contestar uma validação. Só não executam testes de hipótese abandonada pelo pesquisador ou rejeitada pelo pesquisador. Hoje a seleção (`src/knowledge/hypothesis_cycle.py:326`) e `sync_statuses` (`hypothesis_cycle.py:420`) ignoram hipóteses concluídas; isso muda.
4. **Transições de status.** Não há status novo. Ao fim de cada ciclo (nunca no meio dele), `sync_statuses` aplica a todas as hipóteses não abandonadas a mesma regra que já usa para `em_teste` (`DECISION_EVAL_MIN_VERDICT`): veredito `>= limiar` → `validada`; `<= -limiar` → `refutada`; entre os dois, uma hipótese concluída volta a `em_teste`. Cada transição fica registrada com o veredito anterior e o novo. Quando uma hipótese concluída reabre ou muda de lado, os efeitos da conclusão são revistos: a `Oportunidade` ligada por `GEROU` volta ao status anterior à conclusão; as decisões já avaliadas recebem nova avaliação; os atalhos `FUNCIONOU_PARA`/`FALHOU_PARA` apoiados nela passam a `status = "contestada"`, como a spec `curator` já prevê para evidência que muda.
5. **Replicação não infla o veredito.** A independência das evidências já é descontada pela fórmula (ADR 015 §9: `d = 0,2` para nova seed e `0,5` para nova sessão, contra `1,0` para novo dataset ou nó); repetir seeds na mesma sessão acumula pouco. A parada por objetivo (§5.2) não depende do veredito, então repetir testes não antecipa a parada; a calibração dos pesos fica para a Etapa 2.

### 5. Limites da exploração e parada pelo objetivo do Problema

Decisão do pesquisador (2026-10-15): *"Estabelecer um teto para hipóteses pode ser um problema para pesquisas que demandam uma exploração mais longa. Os limites devem ser de custo, uso de token ou tempo, configuráveis e permitindo uma exploração infinita. O critério de parada será definido no problema: todo problema deve ter um objetivo, e o Validator verifica se já o atingiu ao avaliar os resultados."*

1. **Sem teto de hipóteses nem de ciclos.** `HYPOTHESES_PER_CYCLE` deixa de existir: todas as hipóteses executáveis do plano entram na fila, em ordem de prioridade (a prioridade atual continua ordenando), e nenhuma subtarefa é retirada por `hipotese_adiada_por_prioridade`. `MAX_EXPLORATION_CYCLES` (`limite_ciclos`) e `MAX_AGENT_RUNS_PER_SESSION` (`limite_execucoes`) deixam de ser condições de parada (continuam medidos e relatados).
2. **Parada pelo objetivo, conforme o tipo.** Todo `Problema` tem um objetivo, e o objetivo tem um **tipo**. No `auto`, o objetivo proposto no plano vale depois de aprovado pelo Validator e é exibido ao pesquisador como evento; no `assisted` e no `semi`, confirmá-lo é decisão reservada (`confirmar_problema`) e passa pelo gate. O objetivo pode ser revisto depois pelo mesmo caminho. Cada tipo define três critérios, que o regimento da pesquisa (ADR 022 §4) descreve e o código aplica: quando o objetivo é atingido, o que conta como avanço rumo a ele e como se mede a saturação.

   | Tipo | Atingido quando | Avanço | Saturação |
   |---|---|---|---|
   | `limiar` | um resultado aprovado pelo Validator alcança o alvo e o ganho mínimo sobre a referência | melhora do melhor resultado validado acima da incerteza da medida; sem incerteza medida, qualquer melhora validada (registrada como tal) | com ao menos `SATURATION_MIN_REPLICATES` réplicas (padrão 3), a melhora ainda possível fica abaixo do erro estatístico da medida |
   | `discriminacao` | as evidências validadas que discriminam as hipóteses concorrentes deixam um desfecho: uma compatível e as demais contrariadas; todas contrariadas; ou várias compatíveis (mecanismos que coexistem) | novo resultado validado cuja predição difere entre as concorrentes | nenhum experimento planejado ou executável tem predições diferentes entre as concorrentes que restam |
   | `cobertura` | o pesquisador considera o mapeamento suficiente | hipótese nova que não repete as existentes (abaixo do limiar de similaridade) | a taxa de hipóteses novas cai a quase zero (nesta etapa, só aviso; não fecha a sessão) |
   | `fronteira` | o pesquisador aceita o conjunto, ou há k soluções não dominadas | nova solução não dominada pelas já encontradas | as tentativas recentes não ampliam a fronteira |

   - No tipo `limiar`, a comparação com o alvo é determinística (a que `check_solution` já faz, `src/knowledge/hypothesis_cycle.py:508-514`), **sem o filtro de veredito** (`hypothesis_cycle.py:509`), que sai; a verificação do Validator é a aprovação do resultado.
   - No tipo `discriminacao`, cada hipótese concorrente declara a predição que a distingue; um resultado validado contraria uma hipótese quando o Validator, na revisão, confirma que ele diverge da predição dela. O desfecho é decidido por essas evidências validadas, **não pelo valor do veredito**, que ainda não foi calibrado (Etapa 2). "Todas contrariadas" é um resultado registrado e leva o Researcher a propor hipóteses novas; "várias compatíveis" vai ao pesquisador. Quando o experimento que distinguiria as restantes existe mas exige bancada ou equipamento indisponível no sandbox, o desfecho é `aguarda_experimento_fisico` (registrado com o experimento proposto), e não saturação.
   - Nesta etapa são implementados `limiar`, `discriminacao` e uma forma mínima de `cobertura` (objetivo decidido pelo pesquisador; saturação só como aviso); `fronteira` fica declarado e é especificado junto com a V19 (equipamentos), quando houver experimentos físicos para validá-lo.
   - O veredito continua sendo, em todos os tipos, a medida de confiança do conhecimento no grafo.
3. **O que acontece ao atingir o objetivo.** Atingir o objetivo é sempre um evento e um marco registrado. Se a sessão fecha depende da política do Problema `ao_atingir_objetivo`: `parar` (padrão no `semi` e no `auto`), `perguntar` (padrão no `assisted`: o pesquisador escolhe encerrar ou continuar, pelo gate) ou `continuar` (segue replicando, otimizando além do alvo e testando hipóteses abertas, até os limites ou até não haver caminho).
4. **Limites de custo, tokens, tempo e egresso.** A sessão tem limites configuráveis de custo (US$, total e por provedor; novo, com o motivo de parada `limite_custo`), tokens, tempo e volume de egresso. Cada um pode ser ajustado livremente para cima. **Desligar limites** é a decisão reservada que já existe ("ativar o modo sem limite"): exige confirmação do pesquisador no terminal ou pelo gate persistente (ADR 023), nunca por variável de ambiente ou arquivo de configuração (spec `operation-metrics`). Com os limites desligados, a exploração segue até o objetivo (conforme a política do item 3), até não haver caminho, até a saturação (item 5), até o pesquisador parar ou até uma falha.
5. **Estagnação leva a intervenção; saturação leva a parada.** Os sistemas revisados não deixam o agente decidir quando parar: usam orçamento externo, tratam a estagnação como sinal para mudar de tática (CostAda, arXiv:2607.26828; RankEvolve, arXiv:2609.39551) e, quando há incerteza medida, param quando a melhora ainda possível fica abaixo do erro da medida (Makarova et al., AutoML 2022). Aqui:
   - **Dois progressos distintos.** Resultados negativos, refutações e replicações são progresso do conhecimento e ficam no grafo e no veredito. Só o **avanço rumo ao objetivo**, conforme o tipo (item 2), zera o contador de estagnação; criar hipóteses ou executar experimentos, sozinho, não zera.
   - **Estagnação.** Depois de `EXPLORATION_STALL_CYCLES` ciclos (padrão 5) sem avanço rumo ao objetivo, a sessão **intervém**, não fecha: o Curator é acionado para sugerir direções novas (abordagens não tentadas, hipóteses derivadas, diversificação), e o Researcher deve responder a cada sugestão no plano seguinte; no `assisted`, vira também um pedido ao pesquisador. A paciência cresce com o número de intervenções já feitas e, quando há limite de orçamento, com a fração já gasta.
   - **Saturação.** Esgotadas as intervenções (`EXPLORATION_MAX_INTERVENTIONS`, padrão 3) sem avanço, e se o critério de saturação do tipo (item 2) se confirmar, a sessão fecha com `saturacao` no `auto`; no `assisted` e no `semi`, registra um pedido ao pesquisador (continuar, orientar ou parar) e segue enquanto ele não responde.
   - **Intervenções esgotadas sem saturação avaliável** (por exemplo, sem réplicas suficientes): em qualquer modo, a sessão emite um evento e registra um pedido ao pesquisador, e segue enquanto ele não responde. A confirmação do modo sem limite informa que, sem limites, não há parada automática garantida.
   - Não se aplica enquanto a política `ao_atingir_objetivo` for `continuar` e o objetivo já tiver sido atingido. Os limiares são configuráveis e desligáveis **sozinhos**, sem afetar os limites de custo, tokens e tempo; o modo sem limite **não** os desliga.
   - **Restrições.** Uma direção pode ser encerrada por segurança, ética ou recurso (reagente perigoso, nível de biossegurança indisponível, risco de uso dual). É uma decisão reservada nova (`restringir_direcao`), registrada como **regra persistente** do Problema ou do projeto: retira as hipóteses daquela direção (`hipotese_direcao_restrita`) e é aplicada pela governança a todo plano novo, por chave estruturada e abordagem e por similaridade com a direção encerrada. O Validator do plano recebe as restrições ativas; um caso duvidoso vira pedido ao pesquisador e não executa enquanto pendente. O Validator da revisão também confere a subtarefa executada contra as restrições ativas. Risco residual: a verificação é sobre o plano e sobre o que foi executado, não um bloqueio dentro do sandbox. As retiradas por similaridade são contadas e listadas no relatório da sessão, para auditar a regra.
6. **Proteções contra falha, ajustadas à exploração longa.**
   - O disjuntor de zero progresso passa a medir progresso por novos `Experimento` e `Resultado` (inclusive replicações e variações com o mesmo nome de subtarefa), e não por nomes de subtarefa novos (`src/autonomous_loop.py:70-75`); o limiar continua configurável.
   - A espera por um pedido pendente do pesquisador não conta como ciclo ocioso nem como estagnação (`src/autonomous_loop.py:1091`).
   - `MAX_PLAN_RETRIES` (planos rejeitados em sequência) fecha com `planos_rejeitados` no `auto`; no `assisted` e no `semi`, registra um pedido ao pesquisador antes de fechar.
   - **Revisão do pesquisador (2026-10-15):** no uso normal a sessão não para por planos rejeitados. Com `ON_PLAN_REJECTIONS=explorar` (padrão), `MAX_PLAN_RETRIES` planos rejeitados em sequência são um sinal de estagnação: o Curator intervém com as últimas `issues`, o Researcher propõe outra abordagem ou variação, a contagem zera e valem as regras de intervenções e saturação deste item. A parada por `planos_rejeitados` e o pedido ao pesquisador descritos acima ficam com `ON_PLAN_REJECTIONS=parar`, que o benchmark usa.
7. **Exploração longa em segundo plano.** Uma exploração sem teto não pode prender o pesquisador: a execução em segundo plano, com acompanhamento à parte, é decidida no ADR 023.
8. **Replanejamento.** Quando o Researcher replaneja, **o plano novo substitui a fila**: itens da fila ausentes do plano novo saem com o motivo `removida_pelo_replanejamento` (registrado, não é retirada por governança), e as hipóteses do sistema ligadas a eles seguem o §3.5.

### 6. O que continua impedindo a execução

Os códigos são os que o código grava hoje (`src/exploration.py:374-392`; os motivos do registro vêm de `src/knowledge/hypotheses.py:584-606` e saem prefixados por `hipotese_`):

| Motivo (código) | Situação | Por quê |
|---|---|---|
| `hipotese_rejeitada_pelo_pesquisador` | Testes de hipótese rejeitada pelo pesquisador; preparações que só a serviam | Decisão humana (pesquisador, 2026-10-15) |
| `hipotese_aguarda_aprovacao` | Testes de hipótese aguardando o pesquisador (`assisted`) | Decisão humana |
| `hipotese_ja_concluida_ou_abandonada` → renomeado `hipotese_abandonada_pelo_pesquisador` | Testes de hipótese abandonada pelo pesquisador (concluídas deixam de bloquear, §4.3) | Decisão humana |
| `hipotese_hipotese_abandonada`, `hipotese_equivalente_a_hipotese_abandonada` | Plano que referencia ou repete hipótese abandonada **pelo pesquisador** (abandono pelo sistema reabre, §3.5) | Decisão humana |
| `hipotese_oportunidade_nao_aprovada` | Hipótese de oportunidade sem aprovação | ADR 012 |
| `hipotese_direcao_restrita` | Hipótese numa direção encerrada pelo pesquisador por segurança, ética ou recurso (§5.5) | Decisão humana |
| `depende_de_subtarefa_retirada` | Só quando **todas** as hipóteses que a subtarefa serve foram retiradas por um dos motivos acima | Consequência de decisão humana |
| Reprovação do Validator | O resultado não conta como evidência validada (a subtarefa executa) | ADR 020; integridade |
| Orçamento, egresso, localidade | Inalterados | ADR 019 |

Deixam de impedir a execução: `sem_hipotese` (substituída pela derivação do §3); `hipotese_adiada_por_prioridade` (substituída pela fila do §5); `hipotese_id_inexistente` e `hipotese_sem_enunciado`, falhas de formato do plano (a subtarefa segue a derivação do §3.3 e o Researcher recebe o aviso, §7).

### 7. Retorno ao Researcher

Toda retirada e toda ligação derivada voltam ao Researcher no replanejamento seguinte, como dado delimitado: subtarefa, motivo e o que o sistema fez (por exemplo, "`preprocessar_dados`: registrada como `preparacao` de h1 e h2"; "`treinar_knn`: hipótese de melhoria do sistema criada"; "`baseline_majoritario`: executada como `preparacao`; declare `papel: referencia` para registrá-la como referência do Problema").

### 8. Revisão de subtarefa e contadores

1. O motivo de revisão `sem_hipotese` (só registrado, sem efeito no status) deixa de ocorrer, porque todo `teste` tem hipótese; a revisão passa a registrar `hipotese_do_sistema` quando a hipótese foi derivada.
2. **Resultado negativo** (abaixo do limiar, contado como progresso) só vale para hipótese do sistema quando os artefatos esperados existem e os demais critérios passaram: falha de execução ou artefato ausente não vira "resultado negativo".
3. O campo `hypothesis` (texto livre por subtarefa) deixa de criar nós `Hipotese` para `preparacao` e `referencia`; em `teste` sem `hypothesis_ref`, vira o enunciado da hipótese derivada quando for afirmativo e citar a métrica, senão vale o formato do §3.3.
4. O evento `hypothesis_cycle` e o relatório contam, por sessão: experimentos por papel; testes por origem da hipótese (pesquisador, researcher, curator, oportunidade, sistema); ligações `PREPARA` derivadas; hipóteses do sistema abandonadas. O contador `reprovacoes_sem_hipotese` é substituído por esses; `fechada_por_hipoteses_nao_testadas` continua.

### 9. Compatibilidade

Grafos existentes não são reescritos: `Experimento` sem `papel` é lido como `teste`; hipóteses existentes mantêm a origem. Os registros federados da V20 (`v20-federated-records`) passam a levar `papel`; se só `teste` e `referencia` são publicáveis fica como pendência daquelas mudanças.

---

## Consideradas e Rejeitadas

### A. Manter o bloqueio e só alinhar prompts e código
Alinhar o texto do Researcher e do Validator com `_is_bound` e informar as retiradas.
**Rejeitada:** resolve a contradição, mas mantém o comportamento que esvazia planos de modelos que planejam em passos finos; o desfecho passa a depender do estilo de planejamento do modelo.

### B. Nó de "exploração livre" sem hipótese
**Rejeitada pelo pesquisador:** uma exploração está sempre ligada a um problema e é, no fundo, uma hipótese; nós soltos enfraquecem a rastreabilidade.

### C. Exigir hipótese própria para toda subtarefa (inclusive preparação e baseline)
**Rejeitada:** força o Researcher a inventar "hipóteses" para etapas que não afirmam nada (foi o que o campo `hypothesis` da EDA fez), poluindo o grafo e o veredito.

### D. Papel decidido só pelo `task_type`
**Rejeitada na revisão:** pré-processamento e baseline aparecem como `model_impl` ou `validation`; a regra os classificaria como `teste` e criaria hipóteses absurdas ("o pré-processamento melhora a acurácia"). A estrutura do DAG (ter dependentes) é o sinal mais confiável.

### E. Tornar `papel` obrigatório e reprovar o plano sem ele
**Rejeitada:** troca um bloqueio por formato por outro; o papel é declarado quando possível e inferido quando não.

### F. Referência R = melhor resultado validado até o momento
**Rejeitada na revisão:** depende da ordem de execução e é autorreferente quando o melhor resultado é da mesma abordagem; toda abordagem testada depois de um resultado ótimo seria refutada.

### G. Ligação inteiramente pelo Curator, depois da sessão
**Rejeitada:** a ligação do DAG é determinística e não precisa de LLM; adiar deixa a sessão sem veredito durante a execução.

### H. Manter `HYPOTHESES_PER_CYCLE` como ordenação, e `MAX_EXPLORATION_CYCLES` como parada
**Rejeitada pelo pesquisador:** tetos de hipóteses ou de ciclos limitam pesquisas que precisam de uma exploração longa; o controle de gasto fica com os limites de custo, tokens, tempo e egresso (§5.4).

### I. Teto de tentativas para hipóteses do sistema deixarem de prender a sessão
**Rejeitada:** era a defesa contra sessões que nunca fecham; com a parada pelo objetivo (§5.2), a estagnação (§5.5) e a execução em segundo plano (ADR 023), a sessão não prende o pesquisador, e um teto desses voltaria a cortar exploração.

### J. Solução decidida pelo veredito da hipótese (`SOLUTION_MIN_VERDICT`)
**Rejeitada:** o veredito mede a confiança acumulada do conhecimento e precisa de várias evidências independentes (uma evidência perfeita dá no máximo 0,11); usá-lo como parada fez nenhuma sessão da bateria V18.6 fechar por solução, mesmo com acurácia validada 1,0. A parada passa a ser o objetivo do Problema atingido por um resultado aprovado pelo Validator, com comparação determinística (§5.2).

### K. Confirmação do objetivo por um campo novo no parecer do Validator
**Rejeitada na revisão:** trocaria a comparação determinística que já existe por um julgamento de LLM, sujeito a falso positivo (encerra cedo) e falso negativo (nunca encerra). O Validator verifica ao aprovar o resultado; a comparação com o alvo é feita pelo código.

### L. Desligar limites por `0` ou vazio no `.env`
**Rejeitada na revisão:** contornaria a decisão reservada do modo sem limite; desligar limites continua exigindo a confirmação do pesquisador (§5.4).

### M. Um único tipo de objetivo (limiar numa métrica)
**Rejeitada pelo pesquisador:** pesquisas em química e biologia nem sempre têm uma métrica contínua com alvo; elucidar um mecanismo termina por eliminação de hipóteses, buscar rotas de síntese termina numa fronteira de compromissos, e uma descoberta aberta termina por saturação de novidade. Experimentos de bancada têm poucas réplicas, e a incerteza nem sempre é medível. O objetivo passa a ter tipo (§5.2).

### N. Estagnação como parada (N ciclos sem melhora)
**Rejeitada:** seria um teto de ciclos com outro nome; os sistemas revisados usam a estagnação para mudar de tática. A parada automática, além do objetivo e dos limites, é a saturação estatística depois das intervenções (§5.5).

---

## Consequências

### Positivas
- Planos em passos finos executam; o desfecho deixa de depender do estilo de planejamento do modelo.
- Nenhum nó solto: toda execução tem um caminho até o `Problema`.
- A exploração aparece como árvore (hipóteses derivadas; variações e replicações como experimentos da mesma hipótese).
- Replicação passa a ser possível e pode contestar uma validação.
- A proporção de testes por origem da hipótese vira métrica do comportamento dos agentes.

### Negativas / Trade-offs
- Hipóteses do sistema podem sair genéricas; mitigação: formato fixo com métrica e referência fixada, chave estruturada e sugestão do Curator.
- Mais relações no grafo (`PREPARA`, `REFERENCIA_DE`) e propriedades novas (`papel`, `origem=sistema`, chave estruturada).
- Hipóteses concluídas podem mudar de status com novas evidências; leitores do grafo que assumiam status final precisam lidar com isso.
- O Researcher perde a "punição" por não declarar hipótese; a qualidade passa a ser cobrada pela medida do §8 e pelas sugestões do Curator.
- Com os limites desligados, uma sessão pode gastar sem fim enquanto houver caminho aberto; a proteção é o disjuntor de zero progresso, a parada pelo objetivo e o acompanhamento pelo pesquisador (ADR 023).
- A parada passa a depender do parecer do Validator; um Validator que aprova um resultado errado encerra a sessão cedo (mitigado pela independência de família, ADR 020, e pela verificação de afirmações).

---

## Decisões do pesquisador sobre as questões levantadas (2026-10-15)

1. **Calibração do veredito.** Os parâmetros do veredito são calibrados na Etapa 2, depois destes ajustes. A parada deixa de depender deles (§5.2).
2. **Hipótese do sistema por modo.** No `assisted`, aguarda aprovação do pesquisador; no `semi` e no `auto`, segue por decisão do Researcher e do Validator (§3.6).
3. **Tetos.** Sem teto de hipóteses nem de ciclos; limites de custo, tokens e tempo, configuráveis e desligáveis (pela decisão reservada do modo sem limite); parada pelo objetivo do Problema, verificado pelo Validator (§5).
4. **Sessão livre.** O trabalho longo ocorre em segundo plano, com acompanhamento à parte, enquanto o pesquisador continua conversando com os agentes (ADR 023).
5. **Objetivo tipado e regras comuns (2026-10-15).** O objetivo do Problema tem tipo, porque pesquisas de outros contextos (química, biologia) não param por um limiar; os critérios de cada tipo ficam no regimento da pesquisa, comum a todos os agentes e injetado em toda chamada (ADR 022 §4).

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-hypothesis-linking` | `hypothesis-loop` | §2–§4, §6–§8: papel do experimento, ligações derivadas, hipótese do sistema (chave, ciclo de vida, R fixada, aprovação por modo), novos testes de hipótese concluída, fila substituída no replanejamento, retorno ao Researcher, motivos de retirada |
| `v18.7-graph-exploration-relations` | `knowledge-graph` | §2–§4, §9: `papel`, `origem=sistema`, chave estruturada, referência R fixada, `abandonada_por`, `PREPARA`, `REFERENCIA_DE`, `DERIVADA_DE -> Hipotese`, leitura compatível |
| `v18.7-exploration-limits` | `hypothesis-loop`, `usage-limits`, `agent-runtime`, `operation-metrics`, `benchmark`, `session-continuity`, `research-project`, `knowledge-graph`, `researcher-consult` | §5: fim de `HYPOTHESES_PER_CYCLE`, `MAX_EXPLORATION_CYCLES` e `MAX_AGENT_RUNS_PER_SESSION` como parada; limite de custo por sessão (`limite_custo`); modo sem limite cobrindo custo; objetivo tipado (`limiar`, `discriminacao` e `cobertura` mínima nesta etapa, `fronteira` declarado para a V19), réplicas mínimas para saturação, `aguarda_experimento_fisico`, decisão reservada `restringir_direcao` e parada pelo critério do tipo, sem filtro de veredito no `limiar`; política `ao_atingir_objetivo`; estagnação como intervenção do Curator; saturação; restrições por direção; disjuntor por novos experimentos; espera do gate fora dos ciclos ociosos; objetivo obrigatório no `Problema` (confirmado pelo gate no `assisted`/`semi`); motivos novos na classificação do benchmark (`limite_custo` como limite, `saturacao` como critério de pesquisa) e na retomada (`src/continuity.py:64-67`: `limite_custo` retoma sem perguntar, como os demais limites; `saturacao` pergunta) |
| `v18.7-exploration-metrics` | `operation-metrics`, `benchmark` | §8.4: contadores por papel e origem, substituição de `reprovacoes_sem_hipotese`; também ADR 022 §6.3 e §7 (hash do contrato por tentativa, tokens do contrato por execução) |

### Estado da implementação (2026-10-17)

| Mudança | Estado |
|---|---|
| `v18.7-graph-exploration-relations` | Implementada e mergeada. |
| `v18.7-hypothesis-linking` | Implementada e mergeada. |
| `v18.7-exploration-limits` | Implementada, mergeada (#187 a #200) e validada na bateria parcial de 2026-10-18 (`docs/benchmarks/2026-10-18-bateria-v18-7-parcial-resultados.md`): sem paradas por `limite_ciclos`/`limite_execucoes` e `solucao_encontrada` com acurácia validada 0,975. Pendências em `tasks.md`: concorrente declarada no item de `hipoteses`; `viola_restricao` só no revisor LLM; revisão do objetivo para `discriminacao` não aplicada pela sessão. |
| `v18.7-exploration-metrics` | Não iniciada (§8.4: contadores por papel e origem; ADR 022 §6.3 e §7). |

O §5.1 (nenhuma parada por `limite_ciclos` ou `limite_execucoes`) e o §5.2 (sessões com acurácia validada no alvo fecham por `solucao_encontrada`) foram confirmados na bateria parcial de 2026-10-18, com uma repetição. O ADR passa a `Aceito` quando `v18.7-exploration-metrics` for implementada; a revisão do ADR (comparar modelos treinados, paradas por `hipoteses_nao_testadas` e proporção de hipóteses do sistema) segue pendente da bateria completa.

A mudança `v18.7-hypothesis-linking` também atualiza o cenário "Baseline sem hipótese" de `pipeline-robustness` e o tratamento de resultado negativo (§8.2) em `hypothesis-loop`.

---

## Revisão

Revisar depois da primeira bateria com este ADR implementado: comparar, por combinação, o número de modelos treinados, as paradas por `hipoteses_nao_testadas`, a proporção de hipóteses do sistema e quantas foram abandonadas.
