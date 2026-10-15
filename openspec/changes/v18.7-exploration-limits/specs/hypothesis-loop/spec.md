# Delta: hypothesis-loop

Testes sem chamada paga: grafo em memória (`GraphStore` de teste), Researcher, Validator e Curator simulados por respostas gravadas, `UsageTracker` com leitores injetados e pedidos ao pesquisador por um gate simulado com a interface de `v18.7-persistent-human-gate`. Nos cenários, "pedido `<motivo>`" designa o pedido do gate persistente com a `decisao` e o `motivo` do catálogo do design §10 (por exemplo, pedido `saturacao` é `decisao = "decidir_continuidade"`, `motivo = "saturacao"`; pedido `restricao_duvidosa` é `decisao = "restringir_direcao"`, `motivo = "restricao_duvidosa"`). Os pedidos `estagnacao`, `saturacao`, `intervencoes_esgotadas`, `cobertura_saturada`, `varias_compativeis`, `aguarda_experimento_fisico` e `planos_rejeitados` têm todos `decisao = "decidir_continuidade"`; os pedidos `decidir_objetivo_atingido` e `confirmar_problema` usam o próprio nome como `decisao` (o segundo com `motivo = "revisao_objetivo"`). São os nomes do catálogo de `v18.7-persistent-human-gate` (design §1.1 daquela mudança), sem nome próprio desta mudança.

## MODIFIED Requirements

### Requirement: Autonomia governada pelo SessionMode
O sistema SHALL exigir aprovação do pesquisador, no modo `assisted`, para hipóteses propostas por agentes ou derivadas de oportunidades, e SHALL executar, nos modos `semi` e `auto`, todas as hipóteses executáveis do plano, em ordem de prioridade, sem teto por ciclo. O sistema MUST NOT retirar subtarefa com o motivo `hipotese_adiada_por_prioridade` (ADR 021 §5.1).
(Antes: `semi` e `auto` executavam só as `HYPOTHESES_PER_CYCLE` de maior prioridade.)

#### Scenario: Modo assistido
- **GIVEN** modo `assisted` e uma hipótese com `origem="researcher"`
- **WHEN** o ciclo chega à execução
- **THEN** a hipótese só é executada após aprovação; se rejeitada, fica `abandonada` com motivo

#### Scenario: Modo autônomo sem teto
- **GIVEN** modo `auto` e um plano com 4 hipóteses propostas de prioridades 0,9, 0,7, 0,5 e 0,3, cada uma testada por uma subtarefa sem dependências
- **WHEN** o ciclo executa
- **THEN** as 4 hipóteses ficam `em_teste` e as 4 subtarefas executam, despachadas na ordem 0,9, 0,7, 0,5, 0,3
- **AND** o evento `hypothesis_cycle` não contém o motivo `hipotese_adiada_por_prioridade` em `retiradas_por_motivo`

### Requirement: Exploração contínua até solução, falta de caminhos ou limite
O sistema SHALL repetir o ciclo planejar → executar → consolidar → sugerir até que ocorra um destes: objetivo atingido com a política `parar` (ou o pesquisador encerrar ao ser perguntado), falta de caminhos promissores, limite de uso (tokens, tempo, custo, egresso, retentativas, conexão), saturação no modo `auto`, planos rejeitados somente com `ON_PLAN_REJECTIONS=parar` (com `explorar`, o padrão, a rejeição consecutiva aciona o Curator e a sessão segue), interrupção pelo pesquisador ou falha. O sistema MUST NOT encerrar a sessão por número de ciclos nem por número de execuções de agente (ADR 021 §5.1, §5.4).
(Antes: também fechava com `limite_ciclos` ao atingir `MAX_EXPLORATION_CYCLES` e o critério de solução exigia veredito ≥ `SOLUTION_MIN_VERDICT`.)

#### Scenario: Sem teto de ciclos
- **GIVEN** modo `auto`, limites de tokens, tempo e custo folgados e um Researcher simulado que sempre traz uma subtarefa nova executável
- **WHEN** a sessão passa de 25 ciclos
- **THEN** a sessão continua e nenhum `motivo_parada` `limite_ciclos` é gravado

#### Scenario: Sem caminhos
- **WHEN** não há hipótese nova, nem aprovada pendente, nem sugestão do Curator
- **THEN** a sessão fecha com `motivo_parada="sem_caminhos_promissores"`

#### Scenario: Planos rejeitados com a política explorar
- **GIVEN** `ON_PLAN_REJECTIONS=explorar` (padrão), `MAX_PLAN_RETRIES=5`, `EXPLORATION_MAX_INTERVENTIONS=3` e nenhuma intervenção feita, em qualquer modo
- **WHEN** o Validator rejeita 5 planos consecutivos com `issues` conhecidas
- **THEN** a sessão não fecha e nenhum pedido `planos_rejeitados` é registrado
- **AND** o Curator simulado é chamado em modo intervenção com as últimas `issues`, o evento `estagnacao_intervencao` registra `origem = "planos_rejeitados"` e `intervencao = 1`, e as `issues` e as sugestões chegam ao Researcher no plano seguinte
- **AND** `rejected_plans` volta a 0

#### Scenario: Planos rejeitados com intervenções esgotadas na política explorar
- **GIVEN** `ON_PLAN_REJECTIONS=explorar`, `MAX_PLAN_RETRIES=5` e `intervencoes = EXPLORATION_MAX_INTERVENTIONS`
- **WHEN** o Validator rejeita 5 planos consecutivos
- **THEN** o Curator não é chamado, o evento `intervencoes_esgotadas` e o pedido `intervencoes_esgotadas` são registrados sem bloquear a sessão, `rejected_plans` volta a 0 e a sessão não fecha por `planos_rejeitados`

#### Scenario: Planos rejeitados em sequência no modo automático com a política parar
- **GIVEN** `ON_PLAN_REJECTIONS=parar`, modo `auto` e `MAX_PLAN_RETRIES=5`
- **WHEN** o Validator rejeita 5 planos consecutivos
- **THEN** a sessão fecha com `motivo_parada="planos_rejeitados"`, com checkpoint
- **AND** retomar essa sessão exige confirmação do pesquisador

#### Scenario: Planos rejeitados em sequência no modo assistido com a política parar
- **GIVEN** `ON_PLAN_REJECTIONS=parar`, modo `assisted` (ou `semi`) e `MAX_PLAN_RETRIES=5`
- **WHEN** o Validator rejeita 5 planos consecutivos
- **THEN** um pedido `planos_rejeitados` com as últimas `issues` é registrado e a sessão não fecha antes da resposta
- **AND** a resposta `continuar` zera a contagem e a resposta `parar` fecha com `planos_rejeitados`

#### Scenario: Valor inválido de ON_PLAN_REJECTIONS
- **GIVEN** `ON_PLAN_REJECTIONS=sempre`
- **WHEN** `src/config.py` é importado
- **THEN** a inicialização falha com `ConfigurationError` que cita `ON_PLAN_REJECTIONS` e os valores `explorar` e `parar`

## ADDED Requirements

### Requirement: Objetivo do Problema por tipo
Todo `Problema` SHALL ter um objetivo com `tipo` em `limiar`, `discriminacao`, `cobertura` ou `fronteira`, e o sistema SHALL aplicar, por código determinístico, os critérios de atingimento, avanço e saturação do tipo (ADR 021 §5.2). Nesta etapa o sistema SHALL implementar `limiar`, `discriminacao` e a forma mínima de `cobertura`, e SHALL recusar `fronteira` com a mensagem "tipo `fronteira` ainda não suportado; será especificado com a V19 (equipamentos)". Um `criterio_sucesso` sem `tipo` SHALL ser lido como `limiar`.

#### Scenario: Problema antigo sem tipo
- **GIVEN** um `Problema` com `criterio_sucesso = {metrica: "acuracia", alvo: 0.95, delta_min: 0.01}`
- **WHEN** o objetivo é avaliado
- **THEN** o tipo efetivo é `limiar` e o grafo não é reescrito

#### Scenario: Fronteira recusada
- **GIVEN** modo `auto` e um plano com `objetivo = {tipo: "fronteira"}`
- **WHEN** o plano é validado
- **THEN** o plano é reprovado de forma determinística, sem chamada ao LLM, com a mensagem que cita a V19

### Requirement: Objetivo proposto no plano no modo auto
No modo `auto`, quando o `Problema` não tem objetivo válido, o Researcher SHALL propor a chave `objetivo` no plano, o Validator SHALL aprová-la na validação do plano (mesma chamada) e o sistema SHALL gravá-la no `criterio_sucesso` com `definido_por = "agente"` e emitir o evento `objetivo_definido` somente depois dessa aprovação. Um plano sem `objetivo` enquanto ele é exigido SHALL ser reprovado de forma determinística. No `assisted` e no `semi`, uma revisão do objetivo proposta no plano SHALL virar pedido `confirmar_problema` e MUST NOT ser aplicada antes da resposta. O sistema MUST NOT aceitar `ao_atingir_objetivo` vindo do plano (ADR 021 §5.2, §5.3).

#### Scenario: Objetivo aprovado no auto
- **GIVEN** modo `auto` e um `Problema` sem objetivo válido
- **WHEN** o plano traz `objetivo = {tipo: "discriminacao", hipoteses_concorrentes: [{ref: "h1", predicao: "A"}, {ref: "h2", predicao: "B"}]}` e o Validator simulado devolve `objetivo_status = "approved"`
- **THEN** `criterio_sucesso.tipo` é `discriminacao` com `definido_por = "agente"` e as duas hipóteses têm `concorrente = true` e `predicao`
- **AND** o evento `objetivo_definido` é registrado

#### Scenario: Plano sem objetivo exigido
- **GIVEN** o objetivo é exigido no `auto`
- **WHEN** o plano chega sem `objetivo`
- **THEN** o plano é reprovado sem chamada ao LLM e o Researcher recebe a correção

#### Scenario: Política vinda do plano é ignorada
- **WHEN** o plano do `auto` traz `objetivo.ao_atingir_objetivo = "continuar"` e o objetivo é aprovado
- **THEN** `criterio_sucesso` não tem `ao_atingir_objetivo` e o evento `objetivo_definido` registra `politica_ignorada = true`

#### Scenario: Revisão no modo semi
- **GIVEN** modo `semi` e um `Problema` `limiar` confirmado pelo pesquisador
- **WHEN** o plano propõe `objetivo = {tipo: "cobertura"}`
- **THEN** um pedido `confirmar_problema` com a proposta é registrado e `criterio_sucesso.tipo` continua `limiar`

### Requirement: Objetivo atingido no limiar sem filtro de veredito
No tipo `limiar`, o objetivo SHALL ser atingido quando um `Resultado` validado pelo Validator, que `MEDE` a métrica principal, com qualificador vazio ou `teste`, de `Experimento` que não seja `referencia`, alcança o `alvo` (quando definido) e supera a referência em `delta_min` (quando há referência). O sistema MUST NOT usar o veredito da hipótese nessa decisão (ADR 021 §5.2, rejeitada J).

#### Scenario: Resultado validado atinge o alvo com veredito baixo
- **GIVEN** `criterio_sucesso = {tipo: "limiar", metrica: "acuracia", sentido: "maior_melhor", alvo: 0.95, delta_min: 0.01}`, baseline 0.33 e um `Resultado` validado de acurácia 1.0 numa hipótese com veredito 0.11
- **WHEN** o objetivo é avaliado
- **THEN** `atingido` é verdadeiro

#### Scenario: Alvo atingido sem o ganho mínimo
- **GIVEN** `alvo` 0.90, `delta_min` 0.05, baseline 0.89 e um `Resultado` validado de 0.92
- **WHEN** o objetivo é avaliado
- **THEN** `atingido` é falso

#### Scenario: Resultado não validado ou de referência
- **GIVEN** um `Resultado` 0.99 `nao_validado` e outro 0.99 validado de um `Experimento` com `papel = "referencia"`
- **WHEN** o objetivo é avaliado
- **THEN** `atingido` é falso

### Requirement: Desfechos do objetivo de discriminação
No tipo `discriminacao`, o Validator da revisão SHALL conferir o resultado validado de uma subtarefa com `discrimina` contra a `predicao` de cada concorrente listada (`confirma`, `contraria` ou `inconclusiva`; sem predição declarada, `inconclusiva` sem LLM), e o sistema SHALL decidir o desfecho só pelas conferências validadas, nunca pelo veredito: uma compatível e as demais contrariadas atinge o objetivo (`uma_compativel`); todas contrariadas registra `todas_contrariadas` e pede hipóteses novas ao Researcher; várias compatíveis sem experimento que as distinga gera o pedido `varias_compativeis`; quando o único experimento que as distinguiria é `experimento_fisico`, o desfecho é `aguarda_experimento_fisico`, a subtarefa MUST NOT executar no sandbox e um pedido é registrado (ADR 021 §5.2).

#### Scenario: Uma compatível
- **GIVEN** concorrentes `h1`, `h2`, `h3` e conferências validadas: `h1` confirma, `h2` contraria, `h3` contraria
- **WHEN** o objetivo é avaliado
- **THEN** `atingido` é verdadeiro com `desfecho = "uma_compativel"` e a hipótese `h1` no evento `objetivo_atingido`

#### Scenario: Todas contrariadas
- **GIVEN** conferências validadas que contrariam `h1` e `h2`
- **WHEN** o ciclo termina
- **THEN** o evento `objetivo_desfecho` registra `todas_contrariadas`, a sessão não fecha e o feedback do próximo plano pede hipóteses novas

#### Scenario: Várias compatíveis
- **GIVEN** `h1` e `h2` compatíveis e nenhuma subtarefa na fila nem no último plano com `discrimina` cobrindo as duas
- **WHEN** a saturação do tipo é avaliada
- **THEN** um pedido `varias_compativeis` é registrado e a sessão não fecha com `saturacao`

#### Scenario: Experimento físico
- **GIVEN** `h1` e `h2` compatíveis e a única subtarefa com `discrimina = ["h1", "h2"]` marcada `experimento_fisico = true`
- **WHEN** o ciclo é preparado
- **THEN** a subtarefa é retirada com o código `experimento_fisico`, nenhuma execução no sandbox ocorre, o desfecho `aguarda_experimento_fisico` é registrado com o nome da subtarefa e um pedido `aguarda_experimento_fisico` é registrado

#### Scenario: Concorrente sem predição
- **GIVEN** a concorrente `h2` sem `predicao`
- **WHEN** a revisão de uma subtarefa com `discrimina = ["h1", "h2"]` é registrada
- **THEN** a conferência de `h2` é `inconclusiva` mesmo que o parecer do LLM diga `contraria`

### Requirement: Cobertura mínima
No tipo `cobertura`, o objetivo SHALL ser atingido só por decisão do pesquisador; avanço SHALL ser hipótese nova gravada no ciclo (não reutilizada pela deduplicação); quando a média de hipóteses novas por ciclo nos últimos `COVERAGE_NOVELTY_WINDOW` ciclos (padrão 5) for `<= COVERAGE_NOVELTY_MIN_RATE` (padrão 0.2), o sistema SHALL emitir `cobertura_aviso` e registrar o pedido `cobertura_saturada`, e MUST NOT fechar a sessão por isso (ADR 021 §5.2).

#### Scenario: Aviso de novidade baixa
- **GIVEN** `COVERAGE_NOVELTY_WINDOW=5`, `COVERAGE_NOVELTY_MIN_RATE=0.2` e 5 ciclos com 1, 0, 0, 0, 0 hipóteses novas
- **WHEN** o quinto ciclo termina
- **THEN** o evento `cobertura_aviso` é registrado com taxa 0.2 e um pedido `cobertura_saturada` é registrado
- **AND** a sessão continua

#### Scenario: Pesquisador declara o objetivo atingido
- **GIVEN** o pedido `cobertura_saturada` pendente
- **WHEN** o pesquisador responde `objetivo_atingido`
- **THEN** a sessão fecha com `motivo_parada = "solucao_encontrada"` e o marco `objetivo_atingido` é gravado no `Problema`

### Requirement: Política ao atingir o objetivo
Atingir o objetivo SHALL gerar, uma vez por sessão, o evento `objetivo_atingido` e o marco `objetivo_atingido` no `Problema`. O que acontece depois SHALL seguir `criterio_sucesso.ao_atingir_objetivo`: `parar` fecha com `solucao_encontrada`; `perguntar` registra o pedido `decidir_objetivo_atingido` (encerrar ou continuar) e segue com o que não depende dele; `continuar` segue explorando até limites, falta de caminho, pesquisador ou falha. Sem política declarada, SHALL valer `perguntar` no `assisted` e `parar` no `semi` e no `auto` (ADR 021 §5.3).

#### Scenario: Padrão do modo automático
- **GIVEN** modo `auto`, `Problema` `limiar` sem `ao_atingir_objetivo` e um resultado validado que atinge o alvo
- **WHEN** o ciclo termina
- **THEN** a sessão fecha com `solucao_encontrada` e o evento `objetivo_atingido` registra `politica = "parar"`

#### Scenario: Padrão do modo assistido
- **GIVEN** modo `assisted` e o mesmo caso
- **WHEN** o ciclo termina
- **THEN** um pedido `decidir_objetivo_atingido` é registrado, nenhuma leitura de `stdin` ocorre e a sessão não fecha antes da resposta
- **AND** a resposta `encerrar` fecha com `solucao_encontrada`

#### Scenario: Continuar além do alvo
- **GIVEN** modo `auto` com `ao_atingir_objetivo = "continuar"`, `EXPLORATION_STALL_CYCLES=5`, `EXPLORATION_PATIENCE_GROWTH=0.5`, `f = 0` e o objetivo atingido no ciclo 3
- **WHEN** os ciclos 4 a 10 terminam sem avanço (7 ciclos, acima da paciência de 5 que acionaria a intervenção sem a política `continuar`)
- **THEN** a sessão continua, o evento `objetivo_atingido` aparece uma única vez e nenhum evento `estagnacao_intervencao` é registrado

### Requirement: Estagnação leva a intervenção do Curator
O sistema SHALL contar os ciclos sem avanço rumo ao objetivo, conforme o tipo, e só o avanço SHALL zerar a contagem. No `limiar`, avanço SHALL ser o melhor valor elegível do ciclo superar o melhor anterior em mais que `SATURATION_SE_MULTIPLIER × EP` (padrão 1.0), com `EP = s / √n` das réplicas elegíveis da hipótese do melhor valor (`n ≥ 2`); com `n < 2`, qualquer melhora validada SHALL ser avanço, registrada com `avanco_sem_incerteza = true` (design §5.1); resultados negativos, refutações, replicações, hipóteses novas fora da `cobertura` e execuções, sozinhos, MUST NOT zerá-la. Quando a contagem atinge a paciência `ceil(EXPLORATION_STALL_CYCLES × (1 + EXPLORATION_PATIENCE_GROWTH × intervencoes) × (1 + f))`, com `f` a maior fração consumida entre os limites ativos (0 no modo sem limite), e as intervenções feitas são menos que `EXPLORATION_MAX_INTERVENTIONS`, o sistema SHALL acionar o Curator em modo intervenção, emitir `estagnacao_intervencao` e, no `assisted`, registrar também o pedido `estagnacao`; a sessão MUST NOT fechar por estagnação. `EXPLORATION_STALL_CYCLES=0` SHALL desligar estagnação, intervenção e saturação sem afetar os limites de uso (ADR 021 §5.5).

#### Scenario: Primeira intervenção
- **GIVEN** modo `auto`, `EXPLORATION_STALL_CYCLES=5`, `EXPLORATION_PATIENCE_GROWTH=0.5`, `f = 0` e 5 ciclos seguidos sem avanço com resultados negativos validados
- **WHEN** o quinto ciclo termina
- **THEN** o Curator simulado é chamado com o contexto de intervenção, suas sugestões entram como pendentes e o evento `estagnacao_intervencao` registra `intervencao = 1` e `paciencia = 5`
- **AND** a sessão não fecha

#### Scenario: Paciência cresce
- **GIVEN** uma intervenção feita, `EXPLORATION_STALL_CYCLES=5`, `EXPLORATION_PATIENCE_GROWTH=0.5` e 50% do limite de custo consumido
- **WHEN** a paciência é calculada
- **THEN** o valor é 12

#### Scenario: Avanço zera a contagem
- **GIVEN** `EXPLORATION_STALL_CYCLES=5`, `SATURATION_SE_MULTIPLIER=1.0` e 4 ciclos sem avanço num `limiar` com melhor valor 0.90 e EP 0.01 (réplicas da hipótese do melhor valor, `n ≥ 2`)
- **WHEN** o quinto ciclo traz um resultado validado de 0.93, acima de `0.90 + 1.0 × 0.01 = 0.91`
- **THEN** a contagem de ciclos sem avanço volta a 0 e nenhuma intervenção é feita

#### Scenario: Melhora dentro do erro não é avanço
- **GIVEN** o mesmo estado
- **WHEN** o quinto ciclo traz um resultado validado de 0.905, abaixo de 0.91
- **THEN** a contagem passa a 5 e a primeira intervenção é feita

#### Scenario: Estagnação desligada
- **GIVEN** `EXPLORATION_STALL_CYCLES=0`
- **WHEN** 30 ciclos terminam sem avanço
- **THEN** nenhum evento `estagnacao_intervencao` nem `saturacao_avaliada` é registrado

### Requirement: Saturação depois das intervenções
Esgotadas as `EXPLORATION_MAX_INTERVENTIONS` intervenções sem avanço, o sistema SHALL avaliar a saturação do tipo (evento `saturacao_avaliada`). No `limiar`, a saturação SHALL ser confirmada só com ao menos `SATURATION_MIN_REPLICATES` réplicas validadas da hipótese do melhor valor e nenhuma melhora no período acima de `SATURATION_SE_MULTIPLIER × EP`. Confirmada: no `auto` a sessão SHALL fechar com `motivo_parada = "saturacao"`; no `assisted` e no `semi` SHALL registrar o pedido `saturacao` e seguir. Sem saturação avaliável ou não confirmada, em qualquer modo SHALL emitir `intervencoes_esgotadas`, registrar o pedido de mesmo nome e seguir. O modo sem limite MUST NOT desligar a saturação (ADR 021 §5.5).

#### Scenario: Saturação no auto
- **GIVEN** modo `auto`, `EXPLORATION_MAX_INTERVENTIONS=3`, 3 intervenções sem avanço, `SATURATION_MIN_REPLICATES=3`, `SATURATION_SE_MULTIPLIER=1.0` e a hipótese do melhor valor com réplicas 0.940, 0.950 e 0.945 (`s = 0.005`, `EP = 0.005 / √3 ≈ 0.0029`)
- **WHEN** a paciência seguinte se esgota sem nenhum resultado elegível acima de `0.950 + 1.0 × 0.0029`
- **THEN** o evento `saturacao_avaliada` registra `confirmada` com o melhor valor, o EP e as 3 réplicas, e a sessão fecha com `motivo_parada = "saturacao"`, com checkpoint

#### Scenario: Saturação no semi
- **GIVEN** o mesmo estado em modo `semi`
- **WHEN** a paciência seguinte se esgota
- **THEN** o pedido `saturacao` é registrado e a sessão não fecha

#### Scenario: Réplicas insuficientes
- **GIVEN** modo `auto`, 3 intervenções sem avanço e só 2 réplicas da melhor hipótese
- **WHEN** a paciência seguinte se esgota
- **THEN** o evento `intervencoes_esgotadas` e o pedido de mesmo nome são registrados e a sessão não fecha

#### Scenario: Resposta continuar
- **GIVEN** o pedido `intervencoes_esgotadas` pendente
- **WHEN** o pesquisador responde `continuar`
- **THEN** a contagem de intervenções e de ciclos sem avanço volta a 0

### Requirement: Restrições de direção aplicadas ao plano e à revisão
O sistema SHALL aplicar a todo plano as restrições ativas do `Problema` e do `Projeto` (ADR 021 §5.5): hipótese cuja abordagem canônica consta da restrição, ou cujo enunciado com a abordagem tem similaridade semântica `>= RESTRICTION_SIMILARITY` (padrão 0.80) com a direção restrita, SHALL ir a `abandonada` com `abandonada_por = "pesquisador"`, e suas subtarefas SHALL sair com `hipotese_direcao_restrita`, com o evento `restricao_retirada` (`restricao_id`, `hipotese_id`, `criterio`, `similaridade`). O Validator do plano SHALL receber as restrições ativas como dado delimitado, e cada caso apontado como duvidoso SHALL virar o pedido `restricao_duvidosa`, com a subtarefa retirada (`hipotese_aguarda_decisao_restricao`) enquanto pendente. O Validator da revisão SHALL conferir a subtarefa executada contra as restrições; violação SHALL deixar o resultado não validado com o motivo `direcao_restrita` e registrar o pedido.

#### Scenario: Retirada por abordagem
- **GIVEN** uma restrição ativa do `Problema` com `abordagens = ["sintese_com_reagente_x"]`
- **WHEN** o plano traz uma hipótese com a abordagem `sintese_com_reagente_x`
- **THEN** a hipótese fica `abandonada` com `abandonada_por = "pesquisador"`, a subtarefa sai com `hipotese_direcao_restrita` e o evento `restricao_retirada` registra `criterio = "abordagem"`

#### Scenario: Retirada por similaridade
- **GIVEN** `RESTRICTION_SIMILARITY=0.80`, uma restrição ativa e um índice semântico simulado que devolve 0.86 para a hipótese `h2`
- **WHEN** o ciclo é preparado
- **THEN** `h2` é retirada com `criterio = "similaridade"` e `similaridade = 0.86`

#### Scenario: Restrição revogada
- **GIVEN** a mesma restrição com `status = "revogada"`
- **WHEN** um plano novo traz a mesma abordagem
- **THEN** nenhuma retirada por restrição ocorre

#### Scenario: Caso duvidoso
- **GIVEN** o Validator do plano simulado devolve `restricoes_duvidosas = [{task_name: "t3", restricao_id: "r1"}]`
- **WHEN** o ciclo é preparado
- **THEN** `t3` sai com `hipotese_aguarda_decisao_restricao` e um pedido `restricao_duvidosa` é registrado

#### Scenario: Violação na revisão
- **GIVEN** o Validator da revisão simulado devolve `viola_restricao = "r1"` para uma subtarefa cuja métrica passa no critério
- **WHEN** a revisão é registrada
- **THEN** o resultado não é validado, `motivos` contém `direcao_restrita` e um pedido `restricao_duvidosa` é registrado

### Requirement: Disjuntor por novos experimentos e resultados
Na exploração com projeto, o disjuntor de zero progresso SHALL medir progresso pelo aumento do número de `Experimento` executados na sessão ou de `Resultado` desses experimentos no grafo, ou pela mudança na assinatura dos erros, e não pelo surgimento de nomes de subtarefa novos (ADR 021 §5.6). Replicações e variações com o mesmo `task_name` SHALL contar como progresso. `CIRCUIT_BREAKER_STALL_CYCLES` continua configurável.

#### Scenario: Replicação com o mesmo nome
- **GIVEN** `CIRCUIT_BREAKER_STALL_CYCLES=2` e dois ciclos seguidos em que a única subtarefa executada foi `treinar_rf` (já concluída antes), cada um gravando um `Experimento` e um `Resultado` novos
- **WHEN** o segundo ciclo termina
- **THEN** o disjuntor não dispara

#### Scenario: Nada novo no grafo
- **GIVEN** `CIRCUIT_BREAKER_STALL_CYCLES=2` e três ciclos sem `Experimento` nem `Resultado` novos e com a mesma assinatura de erros
- **WHEN** o terceiro ciclo termina
- **THEN** o disjuntor dispara com o evento `circuit_breaker` e `stalled_cycles = 2`

### Requirement: Espera por pedido do pesquisador fora dos contadores
Um ciclo em que as subtarefas novas foram retiradas só por pedido pendente ao pesquisador, ou em que só restam pedidos pendentes, MUST NOT contar como ciclo ocioso, como ciclo sem avanço nem como ciclo sem progresso do disjuntor (ADR 021 §5.6; ADR 023 §4.4).

#### Scenario: Aprovação pendente no assistido
- **GIVEN** modo `assisted`, `exploration.idle_cycles = 1` e um ciclo cujas subtarefas novas saem todas com `hipotese_aguarda_aprovacao`
- **WHEN** o ciclo termina
- **THEN** `idle_cycles` continua 1 e a contagem de ciclos sem avanço não muda

### Requirement: Estado da exploração no checkpoint
O sistema SHALL gravar em `payload["exploracao_estado"]` do checkpoint, a cada fim de ciclo, a contagem de ciclos sem avanço, as intervenções feitas, o melhor valor e o EP do `limiar`, o desfecho do `discriminacao`, a janela de novidade da `cobertura`, se o objetivo já foi atingido na sessão e a política efetiva, e SHALL restaurá-los na retomada.

#### Scenario: Retomada preserva intervenções
- **GIVEN** uma sessão fechada por `limite_tokens` com 2 intervenções feitas e 3 ciclos sem avanço
- **WHEN** a sessão é retomada
- **THEN** a nova sessão começa com 2 intervenções e 3 ciclos sem avanço

Os cenários "Modo autônomo" (`HYPOTHESES_PER_CYCLE=2`), "Solução encontrada no modo automático" (`SOLUTION_MIN_VERDICT`), "Solução encontrada no modo assistido" (pergunta no terminal) e "Teto de ciclos" saem pelos requisitos modificados acima; nenhum requisito inteiro é removido desta capacidade.
