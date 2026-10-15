# ADR 021 — Exploração Rastreável por Hipóteses: Estrutura dos Nós e Governança por Registro

**Status:** Proposto
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md` (criado junto com as mudanças OpenSpec)
**ADRs relacionados:** ADR 010 (assistente de pesquisa), ADR 012 (Curator e ciclo de exploração),
ADR 015 (modelo de dados do grafo), ADR 020 (independência do Validator), ADR 022 (contrato de contexto
por chamada)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 015 §2 | `Experimento` ganha a propriedade `papel` (`teste` / `preparacao` / `referencia`). |
| 015 §4 | `Hipotese.origem` ganha o valor `sistema`; `Hipotese` ganha a chave estruturada `(problema, abordagem, metrica)` para hipóteses do sistema, a referência R fixada e `abandonada_por`; as transições de status passam a valer também para hipóteses concluídas (§4.4). |
| 015 §5 | Novas relações `PREPARA` e `REFERENCIA_DE`; o destino de `DERIVADA_DE` passa a aceitar `Hipotese`. |
| Spec `curator` | O requisito "Veredito calculado sem LLM" passa a recalcular também hipóteses concluídas, com os efeitos do §4.4 sobre oportunidades, decisões e atalhos. |
| 012 | O Curator passa a ver as hipóteses `origem=sistema` e pode sugerir reformulação ao Researcher pelo canal de sugestões existente (não há fusão de hipóteses pelo Curator). |
| Spec `hypothesis-loop` | A exigência "cada subtarefa referencia a hipótese que testa" vira registro; a retirada por `sem_hipotese` deixa de existir; o teto por ciclo deixa de retirar subtarefas; hipóteses concluídas podem receber novos testes. |
| Spec `pipeline-robustness` | O cenário "Baseline sem hipótese" passa a ser `papel = referencia`. |
| Spec `operation-metrics` | `reprovacoes_sem_hipotese` dá lugar a contadores de ligação derivada (§8). |

---

## Contexto

### O que a bateria V18.6 mostrou (2026-10-15)

A bateria com 4 combinações × 3 repetições no Pi 5 terminou com as 12 execuções em `exit 0` (relatório em
`docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md`), mas com dois padrões:

1. **Planos esvaziados pela governança.** Nas 6 execuções com Claude como Researcher/Developer, a sessão
   fechou em 4 a 12 minutos sem treinar modelo (acurácia nula, `sem_mede`). A cadeia é sempre a mesma:
   o Researcher declara hipóteses (h1, h2…) e as liga às subtarefas de treino; o pré-processamento e o
   baseline ficam sem `hypothesis_ref`, porque não testam nada; `prepare_cycle` (`src/exploration.py:374-377`)
   os retira por `sem_hipotese`; todas as subtarefas dependem do pré-processamento e caem em cascata como
   `depende_de_subtarefa_retirada`; só a EDA executa; depois de 2 ciclos ociosos a sessão fecha como
   `hipoteses_nao_testadas`.
2. **Regras que se contradizem.** O prompt do Researcher diz que só "subtarefas que testam uma hipótese"
   precisam de `hypothesis_ref` e que "preparação (eda) ou síntese" podem omiti-lo
   (`src/exploration.py:108-109`); o código (`_is_bound`, `src/exploration.py:295-308`) exige hipótese de
   toda subtarefa do Developer que não seja `eda` ou `synthesis`; o prompt do Validator do plano diz que
   `hypothesis_ref` é opcional e "nunca é motivo de reprovação" (`src/agents/validator_agent.py:95-96`). O
   Researcher não é informado das retiradas e reenviou o mesmo plano três vezes. O campo `hypothesis` da
   EDA ("Não se testa hipótese; produz o diagnóstico…") ainda virou nó `Hipotese` `em_teste`.

As execuções com Gemini como Researcher não esvaziaram porque o Gemini agrupa o trabalho em subtarefas
grandes: o Claude planeja em passos finos e esbarra na regra.

### O que outros sistemas fazem

Os sistemas agênticos de pesquisa revisados convergem num padrão: **gerar com liberdade, registrar tudo de
forma estruturada e verificar com rigor**. AIDE (arXiv:2502.13138) e AIRA-dojo (arXiv:2507.02554) rastreiam
a exploração como uma árvore de soluções em código (rascunhar, depurar, melhorar) e deixam a métrica
decidir; o AI Scientist v2 (arXiv:2504.08066) usa busca em árvore conduzida por um gerente de experimentos;
o Curie (arXiv:2502.16069) põe o rigor em módulos que verificam o que foi feito; o Co-Scientist
(Nature 655, 2026; arXiv:2502.18864) faz das hipóteses o objeto central e as governa por ranking, não por
bloqueio.

### Decisões do pesquisador (2026-10-15)

> Hipóteses rejeitadas pelo pesquisador não devem ser executadas.

> Uma exploração não surge do nada. Pode ser uma nova abordagem, mas está conectada à solução de um
> problema. Mesmo no caso de testar uma nova ideia, existe uma hipótese do tipo "essa nova arquitetura ou
> esse novo método de treinamento trazem resultados melhores?". Talvez uma reorganização na estrutura de
> como os nós se conectam faça mais sentido do que ter nós soltos.

---

## Decisão

### 1. Princípio

**Toda execução se liga a um `Problema`, e todo teste se liga a uma `Hipotese`; a ligação é registrada,
não exigida como condição para executar.** O que impede uma execução é uma decisão humana ou uma regra
de integridade (§6), nunca a falta de um campo no plano nem um teto de seleção. Quando o plano não
declara a ligação, o sistema a deriva (§3) e registra que a derivou.

### 2. Três papéis de `Experimento`

Cada subtarefa executada continua gerando um `Experimento` (ADR 015 §2), agora com a propriedade `papel`:

| Papel | O que é | Exemplos | Liga-se a |
|---|---|---|---|
| `teste` | Mede algo que uma hipótese afirma | treinar e avaliar um modelo; comparar abordagens | `(Experimento)-[:TESTA]->(Hipotese)` |
| `preparacao` | Produz insumo para outros experimentos, ou caracteriza o problema; não afirma nada sozinho | EDA, limpeza, divisão treino/teste, engenharia de atributos, síntese final | `(Experimento)-[:PREPARA]->(Hipotese \| Problema)` |
| `referencia` | Mede o ponto de comparação do Problema | baseline (classe majoritária, modelo de referência do artigo) | `(Resultado)-[:REFERENCIA_DE]->(Problema)` |

**Como o papel é decidido**, nesta ordem:

1. **Declarado no plano.** O formato do plano ganha o campo `papel` por subtarefa; o Researcher é
   instruído a declará-lo (as regras vêm da fonte única do ADR 022 §5). A ausência do campo nunca é motivo
   de reprovação do plano.
2. **Com `hypothesis_ref` resolvível** → `teste`.
3. **`task_type` `eda` ou `synthesis`** → `preparacao`, sempre.
4. **Sem `hypothesis_ref`, com sinal de teste** → `teste` com hipótese derivada (§3.3), **mesmo que outras
   subtarefas dependam dela** (um `treinar_rf` que alimenta `comparar_modelos` é teste). Sinal de teste:
   um critério de validação com limiar numérico sobre a **métrica principal M do Problema** (a mesma da
   hipótese derivada, §3.3), ou `abordagem` com `tipo = "algoritmo"`. Limiares sobre outras grandezas ("proporção
   de nulos <= 0", que o Validator do plano costuma pedir) não bastam.
   Só a `abordagem` de outro tipo (por exemplo `protocolo`) não basta: alguns modelos a preenchem em todas
   as subtarefas, inclusive na EDA (`src/exploration.py:298-301`).
5. **Sem `hypothesis_ref`, sem sinal de teste, com subtarefas que dependem dela** → `preparacao`. Esta
   regra estrutural cobre o pré-processamento e a divisão treino/teste, seja qual for o `task_type`.
6. **Qualquer outro caso** → `preparacao` ligada ao `Problema`, com o fato registrado. Na dúvida, o sistema
   não inventa hipótese.

O papel `referencia` só vem da declaração no plano (regra 1): o sistema não tenta adivinhar o que é
baseline. Um baseline não declarado e com limiar nos critérios cai na regra 4 e vira `teste` de uma
hipótese do sistema, que tende a ser refutada (o baseline não supera a referência): é evidência negativa
legítima e executa normalmente; o Researcher recebe a indicação de que poderia declará-lo como referência
(§7).

### 3. Ligações derivadas pelo sistema

1. **Preparação → hipóteses que ela serve.** O destino de `PREPARA` sai do DAG: a preparação liga-se a
   toda hipótese testada por um experimento que dependa dela, direta ou transitivamente. A derivação roda
   **depois** da validação do DAG (ciclos e dependências inexistentes já rejeitados pelo
   `task_scheduler`) e é **incremental sobre o grafo**: quando um teste de um ciclo posterior depende de
   uma preparação já concluída, a aresta `PREPARA` é acrescentada ao `Experimento` existente. Sem nenhuma
   hipótese dependente, a preparação liga-se ao `Problema`.
2. **Referência → `Problema`.** O resultado de um experimento `referencia` liga-se ao `Problema` por
   `REFERENCIA_DE`. **Neste ADR o valor medido é registrado, não entra no veredito**: a fórmula (ADR 015 §9)
   continua usando o baseline como hoje; usar o valor medido como entrada de `m` é decisão da calibração
   (Etapa 2).
3. **Teste sem hipótese declarada → hipótese de melhoria do sistema.** Uma subtarefa `teste` (regra 4 do
   §2), ou com `hypothesis_ref` que o registro não aceita por falha de formato (`id_inexistente`,
   `sem_enunciado`), não é retirada: o sistema cria uma `Hipotese` com `origem = "sistema"` no formato "*a abordagem A
   melhora a métrica M do Problema P em relação à referência R*":
   - M é a métrica principal aprovada do Problema;
   - R é **fixada na criação** e registrada na hipótese (valor e origem): o resultado medido de
     `referencia` do Problema, se existir; senão, o baseline do critério do Problema. R não muda durante a
     sessão. A comparação com o melhor resultado até então é registrada à parte, como informação, e não
     define o veredito;
   - a hipótese tem `SOBRE->Problema` e `PROPOE->Abordagem`;
   - o evento do ciclo registra `hipotese_derivada` com a subtarefa e o motivo.
4. **Deduplicação estruturada.** Hipóteses do sistema são deduplicadas pela chave
   `(problema, abordagem canônica, metrica)`, não pela similaridade de texto (que fundiria enunciados que
   só diferem no nome da abordagem). A deduplicação por similaridade (`HYPOTHESIS_DEDUP_SIMILARITY`)
   continua valendo para as hipóteses declaradas.
5. **Ciclo de vida.** A hipótese do sistema existe por causa da subtarefa que a originou: se essa subtarefa
   for retirada (§6), sair da fila num replanejamento (§5) ou esgotar as tentativas sem nenhuma execução,
   a hipótese vai a `abandonada` com `abandonada_por = "sistema"` e o motivo, em vez de ficar `em_teste`
   sem tentativa (o que manteria caminhos "abertos" e levaria a `hipoteses_nao_testadas` ou a
   `limite_ciclos`). **O abandono pelo sistema não bloqueia:** quando um plano posterior traz a mesma
   chave estruturada (§3.4), a hipótese volta a `em_teste` com o histórico preservado. Só o abandono pelo
   pesquisador (`abandonada_por = "pesquisador"`) impede novos testes e a reabertura.
6. **Caminho aberto com teto.** Como uma sessão isolada raramente leva o veredito acima do limiar (questão
   em aberto 1), hipóteses do sistema tenderiam a ficar `em_teste` e a manter `has_open_paths` verdadeiro
   até `limite_ciclos`. Por isso, uma hipótese do sistema com `SYSTEM_HYPOTHESIS_MAX_ATTEMPTS_PER_SESSION`
   tentativas na sessão (padrão 3) **deixa de contar como caminho aberto** para as regras de parada. Ela não
   é bloqueada: o Researcher pode continuar a testá-la; só não prende a sessão. A bateria de revisão mede as
   paradas por `limite_ciclos`.
7. **Curator.** Hipóteses `origem = "sistema"` aparecem para o Curator (ADR 012), que pode sugerir ao
   Researcher uma formulação melhor pelo canal de sugestões já existente. O Curator não funde hipóteses.

### 4. Variações, derivações e replicação

1. **O sistema não deriva hipótese para variação.** Mudar hiperparâmetros, normalização, seed ou partição
   dentro da mesma abordagem é um novo `Experimento` `teste` da **mesma** hipótese, com a configuração na
   aresta `APLICOU {config}` (ADR 015 §5). O Researcher continua livre para declarar uma hipótese própria
   sobre um mecanismo ("padronizar melhora o kNN"), ligada à anterior por `DERIVADA_DE`.
2. **Hipótese derivada.** Uma hipótese que refina ou contrapõe outra liga-se a ela por
   `(Hipotese)-[:DERIVADA_DE]->(Hipotese)`. O grafo mostra a árvore da exploração: Problema → hipóteses →
   hipóteses derivadas → experimentos → resultados.
3. **Hipótese concluída aceita novos testes.** Uma hipótese `validada` ou `refutada` pode receber novos
   testes (replicação, nova seed, nova partição, variação), e o veredito é recalculado com todas as
   evidências, **inclusive para baixo**: uma replicação que falha pode contestar uma validação. Só não
   executam testes de hipótese abandonada pelo pesquisador ou rejeitada pelo pesquisador. Hoje a seleção
   (`src/knowledge/hypothesis_cycle.py:326`) e `sync_statuses` (`hypothesis_cycle.py:420`) ignoram
   hipóteses concluídas; isso muda.
4. **Transições de status.** Não há status novo. Ao fim de cada ciclo (nunca no meio dele), `sync_statuses`
   aplica a todas as hipóteses não abandonadas a mesma regra que já usa para `em_teste`
   (`DECISION_EVAL_MIN_VERDICT`): veredito `>= limiar` → `validada`; `<= -limiar` → `refutada`; entre os
   dois, uma hipótese concluída volta a `em_teste`. Cada transição fica registrada com o veredito anterior e
   o novo. Quando uma hipótese concluída reabre ou muda de lado, os efeitos da conclusão são revistos: a
   `Oportunidade` ligada por `GEROU` volta ao status anterior à conclusão; as decisões já avaliadas recebem
   nova avaliação; os atalhos `FUNCIONOU_PARA`/`FALHOU_PARA` apoiados nela passam a `status = "contestada"`,
   como a spec `curator` já prevê para evidência que muda.
5. **Replicação não infla o veredito.** A independência das evidências já é descontada pela fórmula
   (ADR 015 §9: `d = 0,2` para nova seed e `0,5` para nova sessão, contra `1,0` para novo dataset ou nó);
   repetir seeds na mesma sessão acumula pouco. Se isso basta para impedir `solucao_encontrada` por
   repetição é verificado na calibração (Etapa 2), junto com a questão em aberto 1.

### 5. Seleção por ciclo: ordenar, não retirar

O teto `HYPOTHESES_PER_CYCLE` (padrão 2) hoje retira as subtarefas das demais hipóteses como
`hipotese_adiada_por_prioridade` (`src/exploration.py:390`). Com este ADR, **o teto ordena a execução**:
as hipóteses além do teto ficam na fila do plano para o ciclo seguinte, sem retirada e sem exigir
replanejamento. Hipóteses do sistema derivadas do mesmo plano entram na mesma fila, pela prioridade já
existente. O custo continua limitado pelos tetos de orçamento, tempo e ciclos da sessão.

Quando o Researcher replaneja, **o plano novo substitui a fila**: itens da fila ausentes do plano novo saem
com o motivo `removida_pelo_replanejamento` (registrado, não é retirada por governança), e as hipóteses do
sistema ligadas a eles seguem o §3.5.

### 6. O que continua impedindo a execução

Os códigos são os que o código grava hoje (`src/exploration.py:374-392`; os motivos do registro vêm de
`src/knowledge/hypotheses.py:584-606` e saem prefixados por `hipotese_`):

| Motivo (código) | Situação | Por quê |
|---|---|---|
| `hipotese_rejeitada_pelo_pesquisador` | Testes de hipótese rejeitada pelo pesquisador; preparações que só a serviam | Decisão humana (pesquisador, 2026-10-15) |
| `hipotese_aguarda_aprovacao` | Testes de hipótese aguardando o pesquisador (`assisted`) | Decisão humana |
| `hipotese_ja_concluida_ou_abandonada` → renomeado `hipotese_abandonada_pelo_pesquisador` | Testes de hipótese abandonada pelo pesquisador (concluídas deixam de bloquear, §4.3) | Decisão humana |
| `hipotese_hipotese_abandonada`, `hipotese_equivalente_a_hipotese_abandonada` | Plano que referencia ou repete hipótese abandonada **pelo pesquisador** (abandono pelo sistema reabre, §3.5) | Decisão humana |
| `hipotese_oportunidade_nao_aprovada` | Hipótese de oportunidade sem aprovação | ADR 012 |
| `depende_de_subtarefa_retirada` | Só quando **todas** as hipóteses que a subtarefa serve foram retiradas por um dos motivos acima | Consequência de decisão humana |
| Reprovação do Validator | O resultado não conta como evidência validada (a subtarefa executa) | ADR 020; integridade |
| Orçamento, egresso, localidade | Inalterados | ADR 019 |

Deixam de impedir a execução: `sem_hipotese` (substituída pela derivação do §3);
`hipotese_adiada_por_prioridade` (substituída pela fila do §5); `hipotese_id_inexistente` e
`hipotese_sem_enunciado`, falhas de formato do plano (a subtarefa segue a derivação do §3.3 e o Researcher
recebe o aviso, §7).

### 7. Retorno ao Researcher

Toda retirada e toda ligação derivada voltam ao Researcher no replanejamento seguinte, como dado
delimitado: subtarefa, motivo e o que o sistema fez (por exemplo, "`preprocessar_dados`: registrada como
`preparacao` de h1 e h2"; "`treinar_knn`: hipótese de melhoria do sistema criada";
"`baseline_majoritario`: executada como `preparacao`; declare `papel: referencia` para registrá-la como
referência do Problema").

### 8. Revisão de subtarefa e contadores

1. O motivo de revisão `sem_hipotese` (só registrado, sem efeito no status) deixa de ocorrer, porque todo
   `teste` tem hipótese; a revisão passa a registrar `hipotese_do_sistema` quando a hipótese foi derivada.
2. **Resultado negativo** (abaixo do limiar, contado como progresso) só vale para hipótese do sistema
   quando os artefatos esperados existem e os demais critérios passaram: falha de execução ou artefato
   ausente não vira "resultado negativo".
3. O campo `hypothesis` (texto livre por subtarefa) deixa de criar nós `Hipotese` para `preparacao` e
   `referencia`; em `teste` sem `hypothesis_ref`, vira o enunciado da hipótese derivada quando for
   afirmativo e citar a métrica, senão vale o formato do §3.3.
4. O evento `hypothesis_cycle` e o relatório contam, por sessão: experimentos por papel; testes por origem
   da hipótese (pesquisador, researcher, curator, oportunidade, sistema); ligações `PREPARA` derivadas;
   hipóteses do sistema abandonadas. O contador `reprovacoes_sem_hipotese` é substituído por esses;
   `fechada_por_hipoteses_nao_testadas` continua.

### 9. Compatibilidade

Grafos existentes não são reescritos: `Experimento` sem `papel` é lido como `teste`; hipóteses existentes
mantêm a origem. Os registros federados da V20 (`v20-federated-records`) passam a levar `papel`; se só
`teste` e `referencia` são publicáveis fica como pendência daquelas mudanças.

---

## Consideradas e Rejeitadas

### A. Manter o bloqueio e só alinhar prompts e código
Alinhar o texto do Researcher e do Validator com `_is_bound` e informar as retiradas.
**Rejeitada:** resolve a contradição, mas mantém o comportamento que esvazia planos de modelos que
planejam em passos finos; o desfecho passa a depender do estilo de planejamento do modelo.

### B. Nó de "exploração livre" sem hipótese
**Rejeitada pelo pesquisador:** uma exploração está sempre ligada a um problema e é, no fundo, uma
hipótese; nós soltos enfraquecem a rastreabilidade.

### C. Exigir hipótese própria para toda subtarefa (inclusive preparação e baseline)
**Rejeitada:** força o Researcher a inventar "hipóteses" para etapas que não afirmam nada (foi o que o
campo `hypothesis` da EDA fez), poluindo o grafo e o veredito.

### D. Papel decidido só pelo `task_type`
**Rejeitada na revisão:** pré-processamento e baseline aparecem como `model_impl` ou `validation`; a regra
os classificaria como `teste` e criaria hipóteses absurdas ("o pré-processamento melhora a acurácia").
A estrutura do DAG (ter dependentes) é o sinal mais confiável.

### E. Tornar `papel` obrigatório e reprovar o plano sem ele
**Rejeitada:** troca um bloqueio por formato por outro; o papel é declarado quando possível e inferido
quando não.

### F. Referência R = melhor resultado validado até o momento
**Rejeitada na revisão:** depende da ordem de execução e é autorreferente quando o melhor resultado é da
mesma abordagem; toda abordagem testada depois de um resultado ótimo seria refutada.

### G. Ligação inteiramente pelo Curator, depois da sessão
**Rejeitada:** a ligação do DAG é determinística e não precisa de LLM; adiar deixa a sessão sem veredito
durante a execução.

### H. Remover o teto `HYPOTHESES_PER_CYCLE`
**Não adotada agora:** o teto controla o tamanho do ciclo no Pi 5 e o custo por ciclo; transformá-lo em
ordenação (§5) elimina a perda de subtarefas e preserva o controle. Ver questão em aberto 3.

---

## Consequências

### Positivas
- Planos em passos finos executam; o desfecho deixa de depender do estilo de planejamento do modelo.
- Nenhum nó solto: toda execução tem um caminho até o `Problema`.
- A exploração aparece como árvore (hipóteses derivadas; variações e replicações como experimentos da
  mesma hipótese).
- Replicação passa a ser possível e pode contestar uma validação.
- A proporção de testes por origem da hipótese vira métrica do comportamento dos agentes.

### Negativas / Trade-offs
- Hipóteses do sistema podem sair genéricas; mitigação: formato fixo com métrica e referência fixada,
  chave estruturada e sugestão do Curator.
- Mais relações no grafo (`PREPARA`, `REFERENCIA_DE`) e propriedades novas (`papel`, `origem=sistema`,
  chave estruturada).
- Hipóteses concluídas podem mudar de status com novas evidências; leitores do grafo que assumiam status
  final precisam lidar com isso.
- O Researcher perde a "punição" por não declarar hipótese; a qualidade passa a ser cobrada pela medida
  do §8 e pelas sugestões do Curator.

---

## Questões em aberto (para o pesquisador)

1. **Critério de solução.** Nenhuma das 12 execuções fechou por `solucao_encontrada`, mesmo com acurácia
   validada 1,0 acima do alvo 0,95. O veredito (ADR 015 §9.5) cresce com o número de evidências
   independentes: com evidências perfeitas, 1 evidência dá no máximo `(1/3)² ≈ 0,11` (o teto observado), e
   são precisas cerca de 3 para passar de `SOLUTION_MIN_VERDICT = 0,3`; abaixo disso pesam `m = 0,5` sem
   baseline e `d` reduzido em nova seed ou sessão. Este ADR não muda o veredito; com §4.3 (replicação
   permitida), o Researcher passa a ter como acumular evidências. A calibração (Etapa 2) decide se uma única
   evidência validada que atinge o alvo deve bastar.
2. **Hipótese do sistema no modo `assisted`.** Proposta: segue a regra das hipóteses de agentes (aguarda
   aprovação). Alternativa: executa e fica marcada para revisão.
3. **Teto por ciclo.** Proposta: ordenar (§5). Alternativa: remover o teto e deixar só os limites de sessão.
4. **Teto de tentativas das hipóteses do sistema (§3.6).** Proposta: depois de 3 tentativas na sessão, a
   hipótese do sistema deixa de prender a sessão (sem bloqueá-la). Alternativa: sem teto, aceitando sessões
   que vão até `limite_ciclos` enquanto o veredito não for calibrado.

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-hypothesis-linking` | `hypothesis-loop` | §2–§8: papel do experimento, ligações derivadas, hipótese do sistema (chave, ciclo de vida, R fixada), novos testes de hipótese concluída, fila por ciclo, retorno ao Researcher, motivos de retirada |
| `v18.7-graph-exploration-relations` | `knowledge-graph` | §2–§4, §9: `papel`, `origem=sistema`, chave estruturada, referência R fixada, `abandonada_por`, `PREPARA`, `REFERENCIA_DE`, `DERIVADA_DE -> Hipotese`, leitura compatível |
| `v18.7-exploration-metrics` | `operation-metrics`, `benchmark` | §8.4: contadores por papel e origem, substituição de `reprovacoes_sem_hipotese`; também ADR 022 §6.3 e §7 (hash do contrato por tentativa, tokens do contrato por execução) |

A mudança `v18.7-hypothesis-linking` também atualiza o cenário "Baseline sem hipótese" de
`pipeline-robustness` e o tratamento de resultado negativo (§8.2) em `hypothesis-loop`.

---

## Revisão

Revisar depois da primeira bateria com este ADR implementado: comparar, por combinação, o número de
modelos treinados, as paradas por `hipoteses_nao_testadas`, a proporção de hipóteses do sistema e quantas
foram abandonadas.
