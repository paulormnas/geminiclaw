# Especificação: hypothesis-loop

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md), [`v18.6-hypothesis-closure`](../../changes/archive/v18.6-hypothesis-closure/proposal.md), [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md), [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md), [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Hipóteses formais no plano
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O Researcher SHALL declarar as hipóteses do plano e SHOULD referenciar em cada subtarefa de teste a hipótese que ela testa (`hypothesis_ref`) e declarar o `papel` de cada subtarefa. O sistema SHALL gravar as hipóteses declaradas como nós `Hipotese` ligados ao problema. A falta de `hypothesis_ref` ou de `papel` MUST NOT reprovar o plano nem retirar a subtarefa: o sistema SHALL derivar a ligação e registrá-la.
(Antes: cada subtarefa SHALL referenciar a hipótese que testa, e a subtarefa sem referência era retirada por `sem_hipotese`.)

#### Scenario: Plano com hipótese
- **WHEN** o Researcher gera um plano com a hipótese `h1` e duas subtarefas com `hypothesis_ref="h1"`
- **THEN** existe `Hipotese(status="proposta")` com `SOBRE->Problema`
- **AND** os experimentos das duas subtarefas têm `TESTA->` essa hipótese

#### Scenario: Hipótese repetida
- **GIVEN** uma hipótese do projeto com similaridade 0,94 à nova
- **WHEN** o plano é gravado
- **THEN** a hipótese existente é reutilizada

#### Scenario: Plano em passos finos executa
- **GIVEN** modo `auto` e o plano `eda` (`task_type="eda"`), `preprocessar_dados` (`model_impl`, sem `hypothesis_ref`, critérios "proporção de nulos <= 0"), `baseline_majoritario` (`validation`, `papel="referencia"`), `treinar_knn` (`hypothesis_ref="h1"`, critério "acurácia no teste >= 0.9") e `treinar_rf` (sem `hypothesis_ref`, `approach={"nome": "random forest", "tipo": "algoritmo"}`), as três últimas dependentes de `preprocessar_dados`
- **WHEN** `prepare_cycle` roda
- **THEN** `CycleOutcome.dropped` é vazio
- **AND** as cinco subtarefas estão em `CycleOutcome.tasks`
- **AND** `retiradas_por_motivo` do evento `hypothesis_cycle` é `{}`

#### Scenario: Plano sem papel não é reprovado
- **GIVEN** um plano em que nenhuma subtarefa tem `papel` e uma tem `papel = "exploratoria"`
- **WHEN** o Validator checa a estrutura do plano
- **THEN** o plano não é reprovado por causa de `papel`
- **AND** a subtarefa com `papel = "exploratoria"` é classificada como se não tivesse o campo, e o retorno ao Researcher registra `papel_invalido`

### Requirement: Autonomia governada pelo SessionMode
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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

### Requirement: Decisões de caminho registradas
_Origem: [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md)_
O sistema SHALL registrar cada escolha entre alternativas como `Decisao`, com o que foi
escolhido, o que foi descartado e por quê, e SHALL avaliar a decisão quando o resultado da
escolha tiver evidência moderada.

#### Scenario: Alternativa descartada
- **WHEN** o Researcher escolhe `h1` e descarta "rede neural profunda" por tamanho do dataset
- **THEN** existem `Decisao-ESCOLHEU->h1` e `Decisao-DESCARTOU {motivo}->` um nó da alternativa

#### Scenario: Avaliação posterior
- **WHEN** o veredito da hipótese escolhida chega a −0,4
- **THEN** a decisão recebe `resultado_posterior="nao_acertada"` e o valor do veredito (−0,4) fica registrado na
  trilha de auditoria da decisão (o nó `Decisao` guarda só o texto `acertada`/`nao_acertada`; o schema não tem campo
  para o valor)

### Requirement: Sugestões do Curator e respostas obrigatórias
_Origem: [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md)_
O Curator SHALL sugerir caminhos ao Researcher a cada ciclo, a partir de fontes permitidas, e o
Researcher SHALL responder a cada sugestão aceitando ou recusando com motivo.

#### Scenario: Sugestão aceita
- **WHEN** o Researcher aceita uma sugestão baseada em um caminho sem conclusão
- **THEN** uma hipótese com `origem="curator"` e `DERIVADA_DE` a descoberta é criada

#### Scenario: Sugestão sem resposta
- **WHEN** o plano não responde a uma sugestão pendente
- **THEN** o plano volta ao Researcher uma vez pedindo a resposta

### Requirement: Oportunidades só com decisão humana
_Origem: [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md)_
O sistema SHALL investigar oportunidades apenas após aprovação do pesquisador por
`geminiclaw opportunities approve`, em qualquer modo.

#### Scenario: Oportunidade documentada
- **GIVEN** uma oportunidade com `status="documentada"`
- **WHEN** o Curator gera sugestões
- **THEN** essa oportunidade não é sugerida

#### Scenario: Oportunidade aprovada
- **WHEN** o pesquisador aprova a oportunidade e ela vira hipótese
- **THEN** existe `Oportunidade-GEROU->Hipotese` e a oportunidade fica `em_investigacao`

### Requirement: Exploração contínua até solução, falta de caminhos ou limite
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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

### Requirement: Resultado negativo na revisão
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O revisor SHALL devolver `outcome = "resultado_negativo"` quando a subtarefa tem hipótese resolvida (declarada ou do sistema), todos os artefatos esperados foram resolvidos e as únicas reprovações são comparações determinísticas com a métrica presente e numérica, com os demais critérios aprovados. Em qualquer outro caso de reprovação, inclusive falha de execução e artefato ou `metrics.json` ausente, o `outcome` SHALL ser `reprovado`. O revisor MUST NOT registrar o motivo `sem_hipotese`. Quando a hipótese da subtarefa tem `origem = "sistema"`, o revisor SHALL registrar o motivo `hipotese_do_sistema` em `motivos`, no resultado e no evento `subtask_review`, sem alterar `status` nem `outcome`.
(Antes: o revisor registrava `sem_hipotese` quando só faltava a hipótese para o resultado ser negativo.)

#### Scenario: Acurácia abaixo do alvo numa subtarefa com hipótese
- **GIVEN** a subtarefa `treinar_rl` com `hypothesis_id` resolvido, artefatos presentes e `metrics.json` com `accuracy` 0.933
- **WHEN** o revisor avalia "acurácia no teste >= 0.95"
- **THEN** `outcome` é `resultado_negativo`
- **AND** o evento `subtask_review` registra `outcome = "resultado_negativo"`

#### Scenario: Métrica ausente não é resultado negativo
- **GIVEN** a mesma subtarefa com `metrics.json` sem acurácia
- **WHEN** o revisor avalia o mesmo critério
- **THEN** `outcome` é `reprovado`

#### Scenario: Artefato ausente não é resultado negativo
- **GIVEN** a acurácia 0.933 e um artefato esperado `missing`
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`

#### Scenario: Recurso desligado
- **GIVEN** `NEGATIVE_RESULT_AS_PROGRESS=false`
- **WHEN** o revisor avalia o primeiro cenário
- **THEN** `outcome` é `reprovado`

#### Scenario: Resultado negativo de hipótese do sistema
- **GIVEN** a subtarefa `treinar_rf` testando a hipótese do sistema `hs1`, artefatos presentes e `metrics.json` com `accuracy` 0.80
- **WHEN** o revisor avalia "acurácia no teste >= 0.9"
- **THEN** `outcome` é `resultado_negativo`
- **AND** `motivos` é `["hipotese_do_sistema"]`

#### Scenario: Hipótese do sistema com artefato ausente
- **GIVEN** a mesma subtarefa com `accuracy` 0.80 e o artefato esperado `modelo_rf.joblib` `missing`
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`
- **AND** `motivos` é `["hipotese_do_sistema"]`

#### Scenario: Hipótese do sistema com critério qualitativo reprovado
- **GIVEN** a mesma subtarefa com `accuracy` 0.80, artefatos presentes e o critério "gráfico de importância gerado", e o provedor falso devolve `{"status": "fail"}` para esse critério
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`

#### Scenario: Falha de execução não é resultado negativo
- **GIVEN** a subtarefa `treinar_rf` da hipótese do sistema `hs1` com `agent_status = "error"`
- **WHEN** a ingestão grava o `Experimento`
- **THEN** o `Experimento` tem `status = "falha"`
- **AND** nenhum `Resultado` dessa subtarefa tem `REFUTA->hs1`

#### Scenario: Preparação com limiar não atingido
- **GIVEN** a subtarefa `preprocessar_dados` com `papel_decidido = "preparacao"`, sem hipótese, e `metrics.json` com `proporcao_nulos` 0.1
- **WHEN** o revisor avalia "proporção de nulos <= 0"
- **THEN** `outcome` é `reprovado`
- **AND** `motivos` é vazio

### Requirement: Resultado negativo conclui a subtarefa e conta como progresso
_Origem: [`v18.6-hypothesis-closure`](../../changes/archive/v18.6-hypothesis-closure/proposal.md)_
O laço SHALL marcar a subtarefa com resultado negativo como `concluded_negative`, SHALL não
repeti-la, SHALL tratá-la como concluída para as dependentes e SHALL contá-la como progresso no
disjuntor. O próximo ciclo SHALL receber o feedback do resultado negativo com a hipótese, a métrica,
o valor e o limiar.

#### Scenario: Dependente roda
- **GIVEN** `comparar` depende de `treinar_rl`, e `treinar_rl` teve resultado negativo
- **WHEN** o DAG avança
- **THEN** `comparar` é executada
- **AND** `treinar_rl` não é executada de novo

#### Scenario: Disjuntor não dispara
- **GIVEN** `CIRCUIT_BREAKER_STALL_CYCLES=2` e dois ciclos seguidos em que só houve resultados
  negativos novos
- **WHEN** o segundo ciclo termina
- **THEN** o disjuntor de zero progresso não dispara

#### Scenario: Feedback ao Researcher
- **GIVEN** um resultado negativo da hipótese `h2` com acurácia 0.933 e limiar 0.95
- **WHEN** o próximo ciclo de planejamento é montado
- **THEN** o feedback contém "h2", "0.933" e "0.95" e pede outra abordagem

### Requirement: Ingestão do resultado negativo como evidência
_Origem: [`v18.6-hypothesis-closure`](../../changes/archive/v18.6-hypothesis-closure/proposal.md)_
A ingestão SHALL gravar o `Experimento` de uma subtarefa com resultado negativo com
`status = "sucesso"` e `criterio_plano_atendido = false`, de modo que o `Resultado` validado entre
no veredito da hipótese como tentativa com valor.

#### Scenario: Veredito recebe a tentativa
- **GIVEN** o vocabulário semeado, um `Problema` com métrica `acuracia`, alvo 0.95 e `delta_min`
  0.01, e uma hipótese testada por uma subtarefa com resultado negativo de acurácia 0.933
- **WHEN** a ingestão termina e o veredito da hipótese é recalculado
- **THEN** `n_tentativas` da hipótese é 1
- **AND** existe uma aresta `Resultado-REFUTA->Hipotese`

### Requirement: Sinal de resultado sem `MEDE`
_Origem: [`v18.6-hypothesis-closure`](../../changes/archive/v18.6-hypothesis-closure/proposal.md)_
A ingestão SHALL registrar o evento `resultado_sem_mede` quando o nome base de um `Resultado`
corresponde à métrica do `Problema` e a aresta `MEDE` não foi criada, com o motivo
(`metrica_nao_aprovada`, `qualificador_excluido` ou `resolucao_falhou`).

#### Scenario: Métrica candidata
- **GIVEN** a `Metrica` do `Problema` com status `candidato`
- **WHEN** a ingestão grava um `Resultado` `accuracy`
- **THEN** o evento `resultado_sem_mede` é registrado com motivo `metrica_nao_aprovada`

### Requirement: Conferência do veredito no início da sessão
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)_
Com projeto ativo, o sistema SHALL conferir antes do primeiro planejamento se a `Metrica` do
`Problema` está aprovada no vocabulário. Se não estiver, o sistema SHALL registrar o evento
`veredito_indisponivel` com o motivo e a correção e avisar ao pesquisador. Em nenhum modo a sessão
MUST terminar por isso; no modo `auto` o sistema SHALL exigir que o Researcher defina a métrica no plano
(requisito "Definição de métricas pelo agente no modo auto").
(Antes: no modo `auto` a sessão terminava com `erro` antes de planejar.)

#### Scenario: Modo auto sem métrica aprovada
- **GIVEN** um projeto cujo `Problema` usa uma `Metrica` `candidato`
- **WHEN** a sessão inicia no modo `auto`
- **THEN** o Researcher é chamado e o prompt de planejamento exige a chave `metricas`
- **AND** o evento `veredito_indisponivel` é registrado com `modo = "auto"`
- **AND** a sessão não termina com `erro`

#### Scenario: Modo assistido sem métrica aprovada
- **GIVEN** o mesmo projeto
- **WHEN** a sessão inicia no modo `assisted`
- **THEN** o aviso é impresso e a sessão segue
- **AND** o prompt de planejamento não exige `metricas`

### Requirement: Evidência das afirmações sem código de referência
_Origem: [`v18.6-hypothesis-closure`](../../changes/archive/v18.6-hypothesis-closure/proposal.md)_
O construtor de evidência das conclusões do relatório SHALL incluir, para toda frase sem código de
referência, a tabela dos `Resultado`s validados da sessão (nome, qualificador, valor, subtarefa,
`exec_id`), dentro de `CLAIM_EVIDENCE_MAX_CHARS`. Quando há `relatorio_final.md`, o sistema SHALL
gravar `afirmacoes.json`, com `motivo_vazio` se não houver afirmações.

#### Scenario: Frase sem código recebe a tabela
- **GIVEN** a conclusão "O Random Forest atingiu acurácia de 0,97 no teste" sem código de referência
  e um `Resultado` validado `random_forest.accuracy` 0.9667
- **WHEN** o pacote de evidência é montado
- **THEN** o pacote contém um item com a linha de `random_forest.accuracy` e o valor 0.9667

#### Scenario: Relatório sem afirmações
- **GIVEN** um relatório final cuja verificação não produziu afirmações
- **WHEN** a sessão fecha
- **THEN** `afirmacoes.json` existe com `"afirmacoes": []` e `motivo_vazio` preenchido

### Requirement: Fechamento por falta de caminhos promissores
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)_
A sessão SHALL fechar com `sem_caminhos_promissores` somente quando não há hipótese `em_teste` do
projeto sem tentativa (`n_tentativas = 0`), exceto as retiradas pela governança, e não há sugestão
pendente do Curator. Quando os ciclos ociosos se esgotam com hipótese sem tentativa, a sessão SHALL
fechar com `motivo_parada = "hipoteses_nao_testadas"`, registrar o evento `hipoteses_sem_tentativa` com o
motivo e a lista das hipóteses, e MUST NOT registrar resultado de erro.
(Antes: fechava com `erro` e a mesma mensagem.)

#### Scenario: Hipótese no plano sem tentativa
- **GIVEN** a hipótese `h1` `em_teste`, no plano, com `n_tentativas = 0`, e um ciclo sem subtarefa nova
- **WHEN** o laço decide se há caminho aberto
- **THEN** a sessão não fecha com `sem_caminhos_promissores`
- **AND** o feedback do ciclo cita `h1`

#### Scenario: Ciclos ociosos esgotados
- **GIVEN** dois ciclos ociosos e `h1` ainda sem tentativa
- **WHEN** o segundo ciclo ocioso termina
- **THEN** a sessão fecha com `motivo_parada = "hipoteses_nao_testadas"`
- **AND** o evento `hipoteses_sem_tentativa` leva `motivo_parada` e a lista com `h1`
- **AND** nenhum resultado da sessão tem `status = "error"`

#### Scenario: Retomada recusada
- **GIVEN** uma sessão fechada com `hipoteses_nao_testadas`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a retomada é recusada com mensagem que cita `hipoteses_nao_testadas`

#### Scenario: Todas as hipóteses testadas
- **GIVEN** todas as hipóteses `em_teste` com ao menos uma tentativa e nenhuma sugestão do Curator
- **WHEN** um ciclo não traz subtarefa nova
- **THEN** a sessão fecha com `sem_caminhos_promissores`

### Requirement: Definição de métricas pelo agente no modo auto
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)_
No modo `auto`, quando a `Metrica` do `Problema` não está aprovada, o Researcher SHALL definir no plano uma
métrica ou um conjunto de métricas (`metricas`, cada uma com `nome`, `sentido`, `limiar` e `justificativa`), o
Validator SHALL validar a definição na validação do plano quanto a adequação ao tipo de problema, plausibilidade do
limiar e ausência de métrica de vaidade ou vazamento, e o sistema SHALL gravar a(s) `Metrica`(s) como aprovada(s) pelo
Validator, e usar a principal no `criterio_sucesso` do `Problema`, somente depois dessa validação. Uma `Metrica`
aprovada pelo pesquisador SHALL ter precedência e uma rejeitada por ele SHALL NOT ser aprovada pelo agente.

#### Scenario: Definição validada
- **GIVEN** modo `auto` e `Problema` com `Metrica` `acuracia` em `candidato`
- **WHEN** o plano traz `metricas = [{nome: "acuracia", sentido: "maior_melhor", limiar: 0.95, justificativa: "..."}]` e o Validator aprova as métricas
- **THEN** a `Metrica` fica `aprovado` com `origem_definicao = "agente"` e `aprovada_por = "validator"`
- **AND** `criterio_sucesso.alvo` do `Problema` é 0.95 (quando o `Problema` não tinha `alvo`)
- **AND** o evento `metricas_definidas` é registrado
- **AND** `verdict_availability()` devolve `None`

#### Scenario: Validator reprova a definição
- **GIVEN** o mesmo plano
- **WHEN** o Validator devolve `metricas_status = "revision_needed"`
- **THEN** o plano é reprovado, o Researcher recebe as `issues` e a `Metrica` continua `candidato`

#### Scenario: Plano sem métricas no modo auto
- **GIVEN** a definição é exigida
- **WHEN** o plano chega sem `metricas`
- **THEN** o plano é reprovado deterministicamente, sem chamada ao LLM, com a correção

#### Scenario: Reprovação repetida não aprova por cansaço
- **GIVEN** a definição é exigida e o Validator reprova as métricas `PLAN_REJECTION_STALL_LIMIT` vezes com a mesma assinatura
- **WHEN** o ciclo de planejamento continua
- **THEN** o plano não é aprovado com avisos e nenhuma `Metrica` é gravada

#### Scenario: Precedência do pesquisador
- **GIVEN** a `Metrica` `acuracia` aprovada pelo pesquisador e `Problema` com `alvo` 0.9
- **WHEN** o agente propõe `acuracia` com limiar 0.99
- **THEN** o nó e o `criterio_sucesso` não mudam

#### Scenario: Métrica rejeitada pelo pesquisador
- **GIVEN** uma `Metrica` `rejeitado` chamada `acuracia_balanceada`
- **WHEN** o agente propõe `acuracia_balanceada` e o Validator aprova
- **THEN** nenhuma `Metrica` é aprovada e o evento `metricas_nao_aplicadas` cita `rejeitada_pelo_pesquisador`

#### Scenario: Sentido divergente
- **GIVEN** a `Metrica` candidata `rmse` com `sentido = "menor_melhor"`
- **WHEN** o agente propõe `rmse` com `sentido = "maior_melhor"`
- **THEN** a definição é descartada com motivo `sentido_divergente`

### Requirement: Papel do experimento decidido por ordem fixa
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O sistema SHALL decidir o papel (`teste`, `preparacao`, `referencia`) de cada subtarefa não concluída nesta ordem: (1) `papel` declarado válido; (2) `hypothesis_ref` resolvido para hipótese aceita → `teste`; (3) `task_type` `eda` ou `synthesis` → `preparacao`; (4) sinal de teste → `teste`, mesmo com dependentes; (5) subtarefa com dependentes no plano → `preparacao`; (6) demais → `preparacao` ligada ao `Problema`. Sinal de teste SHALL ser um critério de validação com limiar numérico sobre a métrica principal M do Problema (nome ou sinônimo, sem qualificador ou com qualificador de teste) ou `approach.tipo = "algoritmo"`. O papel `referencia` MUST vir só da declaração. O sistema SHALL gravar o papel no `Experimento` da subtarefa.

#### Scenario: Pré-processamento é preparação
- **GIVEN** `preprocessar_dados` (`model_impl`, sem `hypothesis_ref`, sem `approach`, critério "proporção de nulos <= 0") com três subtarefas dependentes
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "preparacao"` e `papel_fonte = "estrutura_dag"`

#### Scenario: Teste que alimenta comparação continua teste
- **GIVEN** `treinar_rf` sem `hypothesis_ref`, com critério "accuracy >= 0.9" e a dependente `comparar_modelos`
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "teste"` e `papel_fonte = "sinal_de_teste"`

#### Scenario: Limiar sobre outra grandeza não é sinal de teste
- **GIVEN** `dividir_treino_teste` sem `hypothesis_ref`, `approach={"nome": "split estratificado", "tipo": "protocolo"}`, critério "proporção de teste >= 0.2" e sem dependentes
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "preparacao"` e `papel_fonte = "residual"`

#### Scenario: Limiar de validação cruzada não é sinal de teste
- **GIVEN** uma subtarefa sem `hypothesis_ref`, sem `approach` e com o critério "cv_accuracy >= 0.8"
- **WHEN** o papel é decidido
- **THEN** `papel_fonte` não é `sinal_de_teste`

#### Scenario: EDA com abordagem preenchida
- **GIVEN** `eda` com `task_type = "eda"` e `approach={"nome": "análise exploratória", "tipo": "algoritmo"}`, sem `papel`
- **WHEN** o papel é decidido
- **THEN** `papel_decidido = "preparacao"` e `papel_fonte = "task_type"`

#### Scenario: Papel gravado no experimento
- **GIVEN** `baseline_majoritario` declarado com `papel = "referencia"` e executado com sucesso
- **WHEN** a ingestão grava o `Experimento`
- **THEN** o `Experimento` tem `papel = "referencia"` e nenhuma aresta `TESTA`

### Requirement: Preparação ligada às hipóteses que serve
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Depois da validação do DAG, o sistema SHALL ligar o `Experimento` de cada `preparacao` por `PREPARA` a toda hipótese testada por subtarefa que dependa dela, direta ou transitivamente, ou ao `Problema` quando não houver nenhuma. Quando um teste de um ciclo posterior depende de uma preparação já concluída, o sistema SHALL acrescentar a aresta `PREPARA` ao `Experimento` existente. `prepare_cycle` MUST NOT rodar sobre um plano cujo DAG é inválido.

#### Scenario: Preparação de duas hipóteses
- **GIVEN** `preprocessar_dados` com dependentes `treinar_knn` (testa `h1`) e `treinar_rf` (testa `h2`), e `comparar_modelos` (testa `h3`) dependente de `treinar_knn`
- **WHEN** o ciclo executa e a ingestão grava `preprocessar_dados`
- **THEN** o `Experimento` de `preprocessar_dados` tem `PREPARA->h1`, `PREPARA->h2` e `PREPARA->h3`, com `origem = "derivado"`

#### Scenario: Preparação sem hipótese dependente
- **GIVEN** `eda` sem dependentes
- **WHEN** a ingestão grava `eda`
- **THEN** o `Experimento` de `eda` tem `PREPARA->Problema` e nenhuma `PREPARA->Hipotese`
- **AND** nenhum nó `Hipotese` é criado a partir do campo `hypothesis` da `eda`

#### Scenario: Ligação incremental
- **GIVEN** `preprocessar_dados` concluída no ciclo 1 com `PREPARA->h1`, e o plano do ciclo 2 com `treinar_svm` (testa `h4`) dependente de `preprocessar_dados`
- **WHEN** `prepare_cycle` do ciclo 2 roda
- **THEN** o `Experimento` existente de `preprocessar_dados` ganha `PREPARA->h4`
- **AND** nenhum `Experimento` novo é criado para `preprocessar_dados`

#### Scenario: DAG inválido não chega à governança
- **GIVEN** um plano em que `a` depende de `b` e `b` depende de `a`
- **WHEN** o laço processa o plano
- **THEN** `prepare_cycle` não é chamado e o feedback ao Researcher cita o grafo de dependências inválido

### Requirement: Referência do Problema registrada
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Na ingestão de um `Experimento` com `papel = "referencia"`, o sistema SHALL ligar cada `Resultado` com `MEDE->M` ao `Problema` por `REFERENCIA_DE`, SHALL registrar o evento `referencia_sem_metrica` quando não houver `Resultado` de M, e MUST NOT usar esse valor no veredito.

#### Scenario: Baseline declarado
- **GIVEN** `baseline_majoritario` com `papel = "referencia"` e `metrics.json` com `accuracy` 0.62 e `tempo_s` 0.3
- **WHEN** a ingestão termina
- **THEN** o `Resultado` `accuracy` tem `REFERENCIA_DE->Problema`
- **AND** o `Resultado` `tempo_s` não tem `REFERENCIA_DE`
- **AND** o veredito de todas as hipóteses do projeto é o mesmo de antes da ingestão

#### Scenario: Referência sem a métrica
- **GIVEN** `baseline_majoritario` com `papel = "referencia"` e `metrics.json` só com `f1_macro` 0.4
- **WHEN** a ingestão termina
- **THEN** o evento `referencia_sem_metrica` é registrado com `subtarefa = "baseline_majoritario"`

### Requirement: Hipótese do sistema para teste sem hipótese aceita
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Para uma subtarefa `teste` sem `hypothesis_ref`, com `hypothesis_ref` recusado por `id_inexistente` ou `sem_enunciado`, ou declarada `papel: "teste"` sem `hypothesis_ref`, o sistema SHALL usar uma `Hipotese` `origem = "sistema"` com `SOBRE->Problema` e `PROPOE->Abordagem`, enunciado no formato "a abordagem A melhora a métrica M do Problema P em relação à referência R", chave `(problema, abordagem canônica, métrica)` e referência R fixada na criação (resultado medido de `referencia` do Problema; senão o baseline numérico do critério; senão `indisponivel`). O sistema SHALL reutilizar a hipótese que já tem a mesma chave, SHALL registrar o evento `hipotese_derivada` com a subtarefa e o motivo, e MUST NOT retirar a subtarefa.

#### Scenario: Teste sem hipótese declarada
- **GIVEN** `treinar_rf` sem `hypothesis_ref`, `approach={"nome": "random forest", "tipo": "algoritmo"}` e um `Resultado` `accuracy` 0.62 com `REFERENCIA_DE->Problema`
- **WHEN** `prepare_cycle` roda
- **THEN** existe uma `Hipotese` com `origem = "sistema"`, `SOBRE->P`, `PROPOE->` a abordagem `random forest`, `chave_estruturada = "<P.id>|<abordagem.id>|<acuracia.id>"` e `referencia_fixada.valor = 0.62` com `origem_referencia = "referencia_medida"`
- **AND** `treinar_rf.hypothesis_id` é o `id` dessa hipótese
- **AND** o evento `hipotese_derivada` tem `subtarefa = "treinar_rf"` e `motivo = "sem_hypothesis_ref"`

#### Scenario: Referência fixada não muda
- **GIVEN** a hipótese do sistema do cenário anterior e, depois, um novo `Resultado` `accuracy` 0.70 com `REFERENCIA_DE->Problema`
- **WHEN** um plano posterior traz `treinar_rf` de novo sem `hypothesis_ref`
- **THEN** a mesma hipótese é reutilizada com `referencia_fixada.valor = 0.62`

#### Scenario: Sem referência medida
- **GIVEN** nenhum `Resultado` com `REFERENCIA_DE->Problema` e o critério do Problema sem baseline numérico
- **WHEN** a hipótese do sistema é criada
- **THEN** `referencia_fixada` tem `valor = null` e `origem_referencia = "indisponivel"`

#### Scenario: Referência inexistente no plano
- **GIVEN** `treinar_knn` com `hypothesis_ref = "h9"`, sem `h9` declarada no plano nem no grafo, e critério "accuracy >= 0.9"
- **WHEN** `prepare_cycle` roda
- **THEN** `treinar_knn` não está em `CycleOutcome.dropped`
- **AND** o evento `hipotese_derivada` tem `motivo = "ref_id_inexistente"`

#### Scenario: Variação reutiliza a hipótese
- **GIVEN** a hipótese do sistema de `random forest` e um plano posterior com `treinar_rf_200_arvores` sem `hypothesis_ref`, a mesma abordagem e `parameters = {"n_estimators": 200}`
- **WHEN** o ciclo executa
- **THEN** nenhuma hipótese nova é criada
- **AND** o novo `Experimento` tem `TESTA->` a mesma hipótese e `APLICOU {config: {"n_estimators": 200}}->` a abordagem

#### Scenario: Abordagens diferentes não se fundem
- **GIVEN** dois testes sem `hypothesis_ref` no mesmo plano, com abordagens `random forest` e `gradient boosting`
- **WHEN** `prepare_cycle` roda
- **THEN** existem duas hipóteses do sistema com chaves diferentes

#### Scenario: Texto livre afirmativo vira enunciado
- **GIVEN** `treinar_svm` sem `hypothesis_ref`, `approach={"nome": "svm", "tipo": "algoritmo"}` e `hypothesis = "SVM com kernel RBF supera a referência em acurácia"`
- **WHEN** a hipótese do sistema é criada
- **THEN** o `enunciado` é "SVM com kernel RBF supera a referência em acurácia"

#### Scenario: Texto livre negativo não vira enunciado
- **GIVEN** a mesma subtarefa com `hypothesis = "Não se testa hipótese; produz o modelo"`
- **WHEN** a hipótese do sistema é criada
- **THEN** o `enunciado` segue o formato fixo e contém "svm" e "acuracia" ou "acurácia"

### Requirement: Ciclo de vida da hipótese do sistema
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Uma hipótese do sistema sem tentativa SHALL ir a `abandonada` com `abandonada_por = "sistema"` e `motivo_abandono` quando todas as suas subtarefas de origem forem retiradas pela governança (exceto por `hipotese_aguarda_aprovacao` e, enquanto `v18.7-exploration-limits` não o remove, `hipotese_adiada_por_prioridade`), saírem da fila num replanejamento ou esgotarem as retentativas sem execução. Quando um plano posterior trouxer a mesma chave, o sistema SHALL reabri-la, preservando o histórico: em `em_teste` no `semi` e no `auto`; no `assisted`, em `em_teste` só quando `ApprovalPort.previously_approved` (interface comum de `v18.7-persistent-human-gate`) confirmar no gate persistente um pedido `aprovar_hipotese` daquele id autorizado por humano, e em `proposta` em qualquer outro caso. A trilha de auditoria do grafo MUST NOT servir de prova de aprovação. Hipótese abandonada pelo pesquisador MUST NOT ser reaberta pelo sistema.

#### Scenario: Retentativas esgotadas sem execução
- **GIVEN** a hipótese do sistema `hs1` com `n_tentativas = 0` e a única subtarefa de origem `treinar_rf` marcada `abandonada` no DAG por retentativas esgotadas
- **WHEN** o ciclo termina
- **THEN** `hs1` tem `status = "abandonada"`, `abandonada_por = "sistema"` e `motivo_abandono = "tentativas_esgotadas_sem_execucao"`
- **AND** `hs1` não aparece em `untested_hypotheses()`

#### Scenario: Reabertura pela chave
- **GIVEN** `hs1` abandonada pelo sistema, modo `auto`
- **WHEN** um plano posterior traz um teste sem `hypothesis_ref` com a mesma abordagem
- **THEN** `hs1` volta a `em_teste`, sem `abandonada_por`
- **AND** o evento `hipotese_derivada` tem `reaberta = true`

#### Scenario: Reabertura no assistido com aprovação no gate
- **GIVEN** modo `assisted`, `hs1` abandonada pelo sistema e um `FakeGate` com pedido `aprovar_hipotese` de `hs1.id`, `estado = "autorizada"` e `resolvido_por = "terminal"`
- **WHEN** um plano posterior traz um teste que deriva a chave de `hs1`
- **THEN** `hs1` volta a `em_teste`

#### Scenario: Reabertura no assistido sem aprovação no gate
- **GIVEN** modo `assisted`, `hs1` abandonada pelo sistema, uma nota de auditoria no grafo com `decisao = "aprovada"` para `hs1` e nenhum pedido `aprovar_hipotese` autorizado de `hs1.id` no gate
- **WHEN** um plano posterior traz um teste que deriva a chave de `hs1`
- **THEN** `hs1` volta a `proposta` e o teste é retirado com `hipotese_aguarda_aprovacao`

#### Scenario: Interface provisória antes do gate
- **GIVEN** modo `assisted`, a implementação provisória `NoGateApprovalPort` e `hs1` aprovada num ciclo anterior pelo `Approver` injetado
- **WHEN** `hs1` é reaberta pela chave
- **THEN** `previously_approved` devolve `False` e `hs1` volta a `proposta`

#### Scenario: Aguardar aprovação não abandona
- **GIVEN** modo `assisted`, a hipótese do sistema `hs2` pendente e a subtarefa retirada com `hipotese_aguarda_aprovacao`
- **WHEN** `prepare_cycle` termina
- **THEN** `hs2` continua `proposta`

#### Scenario: Abandono do pesquisador não reabre
- **GIVEN** uma hipótese do sistema com a chave `K` abandonada pelo pesquisador
- **WHEN** um plano posterior traz um teste que deriva a chave `K`
- **THEN** a subtarefa é retirada com `hipotese_equivalente_a_hipotese_abandonada`
- **AND** a hipótese continua `abandonada`

#### Scenario: Hipótese do sistema com tentativa não é abandonada
- **GIVEN** `hs1` com `n_tentativas = 2` e um replanejamento que remove da fila sua única subtarefa pendente
- **WHEN** `prepare_cycle` roda
- **THEN** `hs1` não muda de status

### Requirement: Aprovação da hipótese do sistema por modo
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
No modo `assisted`, a hipótese do sistema SHALL aguardar a aprovação do pesquisador como as hipóteses de agentes, pedida e conferida pela interface comum `ApprovalPort` (`src/human_approval.py`) de `v18.7-persistent-human-gate`: com `PersistentGateApprover`, um pedido `aprovar_hipotese` por hipótese no gate persistente, e MUST NOT usar o `terminal_approver`. Se esta mudança for mergeada antes daquela, SHALL criar `src/human_approval.py` com o mesmo `Protocol` e usar a implementação provisória `NoGateApprovalPort` (envolve o `Approver` injetado; sem TTY, o item fica pendente). Nos modos `semi` e `auto`, SHALL seguir com a aprovação do plano pelo Validator, sem pedido ao pesquisador.

#### Scenario: Assistido
- **GIVEN** modo `assisted`, uma `ApprovalPort` que não responde e a hipótese do sistema `hs1` derivada no ciclo
- **WHEN** o ciclo chega à execução
- **THEN** o teste de `hs1` é retirado com `hipotese_aguarda_aprovacao`
- **AND** o item apresentado à `ApprovalPort` tem `origem = "sistema"`

#### Scenario: Aprovação pelo gate persistente
- **GIVEN** modo `assisted`, `PersistentGateApprover` sobre um `FakeGate` e a hipótese do sistema `hs1` derivada no ciclo
- **WHEN** o ciclo chega à execução
- **THEN** existe um pedido `aprovar_hipotese` com `referencia = hs1.id`, o `terminal_approver` não é chamado e o teste de `hs1` é retirado com `hipotese_aguarda_aprovacao`
- **AND** depois que o terminal responde `aprovar` e o pedido é consumido por `consume_authorized`, o teste de `hs1` entra em `CycleOutcome.tasks` no ciclo seguinte

#### Scenario: Automático
- **GIVEN** modo `auto` e a hipótese do sistema `hs1` derivada no ciclo
- **WHEN** o ciclo chega à execução
- **THEN** `hs1` está em `selection.execute` e tem `status = "em_teste"`
- **AND** o `Approver` não é chamado

### Requirement: Hipótese derivada de outra hipótese
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O sistema SHALL aceitar em `derivada_de` de uma hipótese declarada o `id` de uma `Hipotese` do projeto ou o `ref` de outra hipótese declarada antes no mesmo plano, e SHALL gravar `DERIVADA_DE` entre as duas. IDs inexistentes ou de outro projeto MUST ser ignorados.

#### Scenario: Refinamento
- **GIVEN** a hipótese do sistema `hs1` (kNN) no projeto
- **WHEN** o plano declara `h2` "padronizar os atributos melhora o kNN" com `derivada_de = ["<hs1.id>"]`
- **THEN** existe `h2-DERIVADA_DE->hs1`

#### Scenario: ID de outro projeto
- **WHEN** o plano declara `h3` com `derivada_de = ["<id de Hipotese de outro projeto>"]`
- **THEN** `h3` é criada sem aresta `DERIVADA_DE` para esse nó

### Requirement: Hipótese concluída recebe novos testes
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
A governança SHALL deixar executar testes de hipóteses `validada` e `refutada`, sem mudar o status no meio do ciclo. Só MUST NOT executar testes de hipótese abandonada ou rejeitada pelo pesquisador (`abandonada_por = "pesquisador"`); a abandonada pelo agente não bloqueia e volta como `proposta` pela governança do modo (decisão do pesquisador, 2026-10-15).

#### Scenario: Replicação de hipótese validada
- **GIVEN** `h1` `validada` e um plano com `treinar_knn_seed2` (`hypothesis_ref = "<h1.id>"`)
- **WHEN** `prepare_cycle` roda
- **THEN** `treinar_knn_seed2` está em `CycleOutcome.tasks`
- **AND** `h1` continua `validada` até o fim do ciclo

#### Scenario: Hipótese abandonada pelo pesquisador
- **GIVEN** `h5` `abandonada` com `abandonada_por = "pesquisador"` e um plano com `hypothesis_ref = "<h5.id>"`
- **WHEN** `prepare_cycle` roda
- **THEN** a subtarefa é retirada com `hipotese_hipotese_abandonada`

#### Scenario: Hipótese abandonada pelo agente
- **GIVEN** `h6` `abandonada` com `abandonada_por = "agente"` (alternativa descartada pelo Researcher), modo `assisted` e um plano com `hypothesis_ref = "<h6.id>"`
- **WHEN** `prepare_cycle` roda
- **THEN** `h6` volta a `proposta` e a subtarefa é retirada com `hipotese_aguarda_aprovacao`
- **AND** a retirada não grava `abandonada_por = "pesquisador"`

### Requirement: Transições de status nos dois sentidos ao fim do ciclo
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Ao fim de cada ciclo, e nunca no meio dele, o sistema SHALL aplicar a todas as hipóteses não abandonadas a regra do veredito com `DECISION_EVAL_MIN_VERDICT`: `>= limiar` → `validada`; `<= -limiar` → `refutada`; uma hipótese concluída com veredito entre os dois SHALL voltar a `em_teste`. Cada transição SHALL ser registrada com o status e o veredito anteriores e novos. Quando uma hipótese concluída reabre, a `Oportunidade` ligada por `GEROU` SHALL voltar de `concluida` a `em_investigacao`; quando reabre ou muda de lado, as decisões com `ESCOLHEU->` ela SHALL ser reavaliadas e as arestas `FUNCIONOU_PARA`/`FALHOU_PARA` de descobertas `SOBRE->` ela SHALL passar a `status = "contestada"`.

#### Scenario: Replicação que contesta a validação
- **GIVEN** `DECISION_EVAL_MIN_VERDICT=0.3`, `h1` `validada` e, depois de uma replicação no ciclo, veredito 0.12
- **WHEN** o ciclo termina
- **THEN** `h1` volta a `em_teste`
- **AND** o evento `hipotese_transicao` tem `status_anterior = "validada"`, `status_novo = "em_teste"` e `veredito_novo = 0.12`

#### Scenario: Mudança de lado
- **GIVEN** `DECISION_EVAL_MIN_VERDICT=0.3`, `h1` `validada` e veredito −0.35 ao fim do ciclo (`<= -0.3`)
- **WHEN** o ciclo termina
- **THEN** `h1` fica `refutada`
- **AND** a decisão com `ESCOLHEU->h1` e `resultado_posterior = "acertada"` passa a `nao_acertada`

#### Scenario: Oportunidade reaberta
- **GIVEN** `DECISION_EVAL_MIN_VERDICT=0.3`, `Oportunidade` `concluida` com `GEROU->h1`, `h1` `validada`, e veredito 0.1 ao fim do ciclo (entre −0.3 e 0.3)
- **WHEN** o ciclo termina
- **THEN** a oportunidade fica `em_investigacao`
- **AND** a decisão com `ESCOLHEU->h1` fica com `resultado_posterior` vazio

#### Scenario: Atalho contestado pela reabertura
- **GIVEN** `Abordagem-FUNCIONOU_PARA {descoberta_id: d1}->Problema`, `d1` com `SOBRE->h1`, e `h1` reaberta no fim do ciclo
- **WHEN** os efeitos são revistos
- **THEN** a aresta `FUNCIONOU_PARA` tem `status = "contestada"`

#### Scenario: Nada muda no meio do ciclo
- **GIVEN** `h1` `validada` e o veredito recalculado para 0.1 depois da primeira subtarefa do ciclo
- **WHEN** a segunda subtarefa do mesmo ciclo é despachada
- **THEN** `h1` continua `validada`

### Requirement: Só decisão humana ou integridade impede a execução
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
A governança SHALL retirar subtarefas somente pelos motivos `hipotese_rejeitada_pelo_pesquisador`, `hipotese_aguarda_aprovacao`, `hipotese_abandonada_pelo_pesquisador`, `hipotese_hipotese_abandonada`, `hipotese_equivalente_a_hipotese_abandonada`, `hipotese_oportunidade_nao_aprovada`, `hipotese_direcao_restrita` (quando definido), `hipotese_adiada_por_prioridade` (enquanto existir) e `depende_de_subtarefa_retirada`. Uma preparação SHALL ser retirada só quando todas as hipóteses que serve foram retiradas; preparação ligada só ao `Problema` MUST NOT ser retirada por motivo de hipótese. O sistema MUST NOT produzir `sem_hipotese`, `hipotese_id_inexistente`, `hipotese_sem_enunciado` nem `hipotese_ja_concluida_ou_abandonada`.

#### Scenario: Rejeição parcial não derruba a preparação compartilhada
- **GIVEN** modo `assisted`, `preprocessar_dados` servindo `h1` e `h2`, e o `Approver` rejeita `h1` e aprova `h2`
- **WHEN** `prepare_cycle` roda
- **THEN** `treinar_h1` é retirada com `hipotese_rejeitada_pelo_pesquisador`
- **AND** `preprocessar_dados` e `treinar_h2` ficam em `CycleOutcome.tasks`

#### Scenario: Preparação que só servia a hipótese rejeitada
- **GIVEN** `limpar_textos` servindo só `h1`, e o `Approver` rejeita `h1`
- **WHEN** `prepare_cycle` roda
- **THEN** `limpar_textos` é retirada com `hipotese_rejeitada_pelo_pesquisador`

#### Scenario: Teste que depende de teste retirado
- **GIVEN** `comparar` (testa `h3`, aprovada) dependente de `treinar_h1`, e `h1` rejeitada
- **WHEN** `prepare_cycle` roda
- **THEN** `comparar` é retirada com `depende_de_subtarefa_retirada`

#### Scenario: Motivos removidos
- **GIVEN** qualquer plano das cenas desta spec
- **WHEN** `prepare_cycle` roda
- **THEN** nenhum valor de `CycleOutcome.dropped` é `sem_hipotese`, `hipotese_id_inexistente`, `hipotese_sem_enunciado` ou `hipotese_ja_concluida_ou_abandonada`

### Requirement: Replanejamento substitui a fila
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Quando o Researcher replaneja, o plano novo SHALL substituir a fila: toda subtarefa do plano anterior não concluída e não retirada que esteja ausente do plano novo SHALL ser registrada com `removida_pelo_replanejamento` no evento `hypothesis_cycle`, fora de `retiradas_por_motivo`.

#### Scenario: Item removido da fila
- **GIVEN** modo `assisted`, o ciclo 1 com `treinar_svm` fora da execução por `hipotese_aguarda_aprovacao` (sua hipótese segue pendente, a subtarefa continua na fila), e o plano do ciclo 2 sem `treinar_svm`
- **WHEN** `prepare_cycle` do ciclo 2 roda
- **THEN** `removidas_pelo_replanejamento` contém `treinar_svm`
- **AND** `retiradas_por_motivo` não contém `removida_pelo_replanejamento`

#### Scenario: Hipótese do sistema da subtarefa removida
- **GIVEN** `treinar_svm` era a única origem da hipótese do sistema `hs3`, sem tentativa
- **WHEN** o ciclo 2 a remove da fila
- **THEN** `hs3` fica `abandonada` com `abandonada_por = "sistema"` e `motivo_abandono = "removida_pelo_replanejamento"`

### Requirement: Retiradas e ligações voltam ao Researcher
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O sistema SHALL entregar ao Researcher, no replanejamento seguinte e como dado delimitado (`<dado_nao_confiavel origem="ligacoes_e_retiradas_do_ciclo_anterior">`), até `LINKAGE_FEEDBACK_MAX_ITEMS` itens com a subtarefa, o papel, o motivo e o que o sistema fez, retiradas primeiro.

#### Scenario: Retorno do ciclo
- **GIVEN** o ciclo do cenário "Plano em passos finos executa", em que `treinar_rf` derivou a hipótese do sistema `hs1`
- **WHEN** o prompt do próximo plano é montado
- **THEN** o bloco `ligacoes_e_retiradas_do_ciclo_anterior` contém "preprocessar_dados", "preparação de", "treinar_rf" e o `id` de `hs1`
- **AND** contém "baseline_majoritario" com "referência do Problema"

#### Scenario: Baseline não declarado
- **GIVEN** `baseline_dummy` sem `papel`, sem `hypothesis_ref`, com critério "accuracy >= 0.3"
- **WHEN** o prompt do próximo plano é montado
- **THEN** o item de `baseline_dummy` sugere declarar `papel: referencia`

#### Scenario: Limite de itens
- **GIVEN** `LINKAGE_FEEDBACK_MAX_ITEMS=3`, duas retiradas e cinco ligações no ciclo
- **WHEN** o bloco é montado
- **THEN** o bloco tem 3 itens e as duas retiradas estão entre eles

### Requirement: Dados de ligação por ciclo
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O evento `hypothesis_cycle` SHALL trazer, além dos campos atuais, `papeis`, `papel_fonte`, `testes_por_origem`, `ligacoes_prepara`, `hipoteses_sistema_criadas`, `hipoteses_sistema_reutilizadas`, `hipoteses_sistema_reabertas`, `hipoteses_sistema_abandonadas` e `removidas_pelo_replanejamento`, só com contagens, IDs, códigos e nomes de subtarefa.

#### Scenario: Contagens do ciclo
- **GIVEN** o cenário "Plano em passos finos executa", com `h1` de `origem = "researcher"`
- **WHEN** o evento `hypothesis_cycle` é emitido
- **THEN** `papeis = {"teste": 2, "preparacao": 2, "referencia": 1}`
- **AND** `testes_por_origem` tem `researcher = 1` e `sistema = 1`
- **AND** `hipoteses_sistema_criadas = 1`
- **AND** o payload não contém o texto de nenhum enunciado

### Requirement: Hipóteses do sistema visíveis ao Curator e ao Researcher
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
O contexto de hipóteses entregue ao Researcher e ao Curator SHALL identificar as hipóteses com `origem = "sistema"`, e o sistema MUST NOT fundir hipóteses por ação do Curator.

#### Scenario: Hipótese do sistema no contexto
- **GIVEN** a hipótese do sistema `hs1` `em_teste`
- **WHEN** `open_hypotheses_view()` é chamado
- **THEN** o item de `hs1` tem `origem = "sistema"`

### Requirement: Reversão de Oportunidade fora do alcance dos agentes
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
A transição `concluida -> em_investigacao` de `Oportunidade` pelo orquestrador SHALL ser aceita pela validação do grafo só com a flag `revert_on_reopen`, passada exclusivamente pela revisão dos efeitos de `sync_statuses` ao fim do ciclo. Nenhuma ferramenta de agente (inclusive as do Curator), nenhum campo do plano e nenhuma saída de LLM MUST chegar a esse caminho, e a mesma transição sem a flag, ou por um `Actor` de agente, MUST ser recusada.

#### Scenario: Curator tenta reverter a oportunidade
- **GIVEN** uma `Oportunidade` `concluida`
- **WHEN** o `Actor` agente `Curator` atualiza `status` para `em_investigacao` por uma ferramenta de agente
- **THEN** a escrita é recusada e a oportunidade continua `concluida`

#### Scenario: Orquestrador sem a flag
- **GIVEN** uma `Oportunidade` `concluida`
- **WHEN** o `Actor` orquestrador atualiza `status` para `em_investigacao` sem `revert_on_reopen`
- **THEN** a escrita é recusada

#### Scenario: Plano com campo de reversão
- **GIVEN** um plano cujo JSON traz `"revert_on_reopen": true` numa subtarefa ou no envelope
- **WHEN** o plano é processado e o ciclo termina sem hipótese reaberta
- **THEN** nenhuma `Oportunidade` muda de status e o campo é descartado

### Requirement: Fonte do enunciado da hipótese do sistema registrada
_Origem: [`v18.7-hypothesis-linking`](../../changes/archive/v18.7-hypothesis-linking/proposal.md)_
Quando o enunciado de uma hipótese do sistema vier do campo livre `hypothesis` da subtarefa (texto de LLM), o sistema SHALL registrar `enunciado_fonte = "texto_livre"` na nota de auditoria da criação e no evento `hipotese_derivada`, e SHALL registrar `enunciado_fonte = "modelo"` quando usar o formato fixo. No modo `assisted`, o item de aprovação SHALL mostrar a fonte ao pesquisador.

#### Scenario: Enunciado vindo do texto livre
- **GIVEN** a subtarefa `teste` `treinar_rf` sem `hypothesis_ref` e com `hypothesis = "random forest melhora a acuracia"`, sendo `acuracia` a métrica M
- **WHEN** `prepare_cycle` cria a hipótese do sistema
- **THEN** a nota de auditoria e o evento `hipotese_derivada` têm `enunciado_fonte = "texto_livre"`

#### Scenario: Fonte mostrada no assistido
- **GIVEN** modo `assisted` e a mesma hipótese
- **WHEN** o item é apresentado à `ApprovalPort`
- **THEN** o item traz `origem = "sistema"` e `enunciado_fonte = "texto_livre"`

### Requirement: Aprovação de hipóteses no assisted pelo gate persistente
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
No modo `assisted`, cada hipótese proposta por agente ou derivada de oportunidade que aguarda aprovação SHALL virar um pedido `aprovar_hipotese` no gate persistente, com o enunciado e a justificativa sanitizados (até `GATE_QUESTION_MAX_CHARS`); a resposta do terminal (`aprovar`, `rejeitar` com motivo, `editar` com novo enunciado) SHALL ser aplicada pela sessão com o pesquisador como autor; `p` (pular) SHALL deixar o pedido pendente. Nenhuma leitura de terminal MUST ocorrer no processo da sessão (ADR 023 §4.1; substitui `terminal_approver`).

#### Scenario: Aprovação pelo terminal
- **GIVEN** uma sessão `assisted` com a hipótese `h1` (`origem="researcher"`) aguardando aprovação
- **WHEN** o terminal responde o pedido com `aprovar`
- **THEN** no ciclo seguinte `h1` é executada e a métrica `intervencoes_humanas` conta 1 aprovação

#### Scenario: Rejeição com motivo
- **WHEN** o terminal responde o pedido de `h1` com `rejeitar` e motivo "fora do escopo"
- **THEN** `h1` fica `abandonada` com motivo "fora do escopo" e não é executada

#### Scenario: Edição
- **WHEN** o terminal responde com `editar` e enunciado "Variante com dados normalizados"
- **THEN** `h1` é aprovada com o enunciado novo e a edição é contada em `intervencoes_humanas`

### Requirement: Interface comum de aprovação
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
O laço de hipóteses SHALL pedir e conferir aprovação do pesquisador só pela interface `ApprovalPort` (design §2.4): chamada com a lista de `ApprovalItem`, devolve só as decisões já respondidas (item ausente continua pendente), e `previously_approved(hypothesis_id, session_chain)` responde se existe pedido `aprovar_hipotese` desse id autorizado por fonte humana. A implementação de produção (`PersistentGateApprover`) SHALL ler e gravar só `gate_requests`; `previously_approved` MUST NOT consultar a trilha de auditoria do grafo nem outro registro que o processo da sessão possa gravar. Os testes SHALL usar `FakeGate`, que implementa a mesma interface.

#### Scenario: Só decisões respondidas
- **GIVEN** `PersistentGateApprover` e dois itens, `h1` com pedido autorizado (`aprovar`) e `h2` sem resposta
- **WHEN** o laço chama o aprovador
- **THEN** o dicionário devolvido tem só `h1`, com ação `aprovar`, e o pedido de `h1` fica com `consumido_em` preenchido

#### Scenario: Aprovação anterior vem do gate
- **GIVEN** a hipótese `h3` com uma nota de auditoria `decisao="aprovada"` gravada pela sessão no grafo e nenhum pedido `aprovar_hipotese` autorizado para `h3`
- **WHEN** `previously_approved("h3", cadeia)` é chamado
- **THEN** devolve `False`

#### Scenario: FakeGate com a mesma interface
- **WHEN** o teste de contrato roda os cenários acima com `FakeGate` no lugar de `PersistentGateApprover`
- **THEN** os resultados são os mesmos

### Requirement: Decisão ao atingir o objetivo pelo gate persistente
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Quando o critério de solução é atingido e a decisão cabe ao pesquisador (hoje, modo `assisted`; com `v18.7-exploration-limits`, política `perguntar`), a sessão SHALL criar o pedido `decidir_objetivo_atingido` com o melhor resultado validado e o valor do alvo, e SHALL fechar com `solucao_encontrada` na resposta `encerrar` ou continuar explorando na resposta `continuar` (ADR 023 §4.1; ADR 021 §5.3; substitui `terminal_solution_confirmer`).

#### Scenario: Encerrar
- **GIVEN** uma sessão `assisted` que atingiu o critério de solução
- **WHEN** o terminal responde `encerrar`
- **THEN** a sessão fecha com `motivo_parada="solucao_encontrada"`

#### Scenario: Continuar
- **WHEN** o terminal responde `continuar`
- **THEN** a sessão segue para o próximo ciclo e o pedido fica consumido

#### Scenario: Sem resposta com terminal ausente
- **GIVEN** o pedido pendente e o terminal ausente
- **WHEN** a sessão `assisted` lê a presença
- **THEN** a sessão fica `suspensa_sem_pesquisador` com o pedido ainda pendente

### Requirement: Pedidos de continuidade e de restrição pelo gate persistente
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Os pedidos ao pesquisador em estagnação no `assisted`, saturação, intervenções esgotadas, cobertura saturada, várias hipóteses compatíveis, experimento físico pendente ou planos rejeitados SHALL usar a decisão `decidir_continuidade`, com o subtipo em `motivo` (respostas `continuar`, `orientar` com texto, `parar` e, conforme o `motivo`, `aceitar_conjunto` ou `objetivo_atingido`, restritas às `opcoes` gravadas no pedido), e o caso duvidoso de restrição de direção SHALL usar `restringir_direcao` com `motivo="restricao_duvidosa"` (respostas `restringir` ou `liberar`), ambos pelo gate persistente; a orientação de `decidir_continuidade` SHALL chegar ao Researcher no replanejamento delimitada como dado (ADR 023 §4.1; ADR 021 §5.5 e §5.6). Os pontos que criam esses pedidos são de `v18.7-exploration-limits`.

#### Scenario: Parar por decisão do pesquisador
- **GIVEN** um pedido `decidir_continuidade` com `motivo="saturacao"` criado por uma sessão `semi` em `aguarda_pesquisador`
- **WHEN** o terminal responde `parar`
- **THEN** a sessão é encerrada pelo terminal com `motivo_parada="encerrada_pesquisador"` e relatório, sem criar processo novo

#### Scenario: Orientar
- **GIVEN** um pedido `decidir_continuidade` com `motivo="saturacao"` e `opcoes=["continuar","orientar","parar"]`, criado por uma sessão `semi` que ficou `aguarda_pesquisador`, e respostas gravadas para a continuação que registram o prompt recebido
- **WHEN** o terminal responde `orientar` com "priorize modelos lineares"
- **THEN** a sessão retomada recebe o texto no replanejamento dentro de `<mensagens_do_pesquisador>`

#### Scenario: Resposta fora das opções do pedido
- **GIVEN** um pedido `decidir_continuidade` com `motivo="estagnacao"` e `opcoes=["continuar","orientar","parar"]`
- **WHEN** o terminal tenta responder `aceitar_conjunto`
- **THEN** a resposta é recusada com a lista de opções válidas e o pedido continua `pendente`

### Requirement: Objetivo do Problema por tipo
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
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
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
Um ciclo em que as subtarefas novas foram retiradas só por pedido pendente ao pesquisador, ou em que só restam pedidos pendentes, MUST NOT contar como ciclo ocioso, como ciclo sem avanço nem como ciclo sem progresso do disjuntor (ADR 021 §5.6; ADR 023 §4.4).

#### Scenario: Aprovação pendente no assistido
- **GIVEN** modo `assisted`, `exploration.idle_cycles = 1` e um ciclo cujas subtarefas novas saem todas com `hipotese_aguarda_aprovacao`
- **WHEN** o ciclo termina
- **THEN** `idle_cycles` continua 1 e a contagem de ciclos sem avanço não muda

### Requirement: Estado da exploração no checkpoint
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL gravar em `payload["exploracao_estado"]` do checkpoint, a cada fim de ciclo, a contagem de ciclos sem avanço, as intervenções feitas, o melhor valor e o EP do `limiar`, o desfecho do `discriminacao`, a janela de novidade da `cobertura`, se o objetivo já foi atingido na sessão e a política efetiva, e SHALL restaurá-los na retomada.

#### Scenario: Retomada preserva intervenções
- **GIVEN** uma sessão fechada por `limite_tokens` com 2 intervenções feitas e 3 ciclos sem avanço
- **WHEN** a sessão é retomada
- **THEN** a nova sessão começa com 2 intervenções e 3 ciclos sem avanço

Os cenários "Modo autônomo" (`HYPOTHESES_PER_CYCLE=2`), "Solução encontrada no modo automático" (`SOLUTION_MIN_VERDICT`), "Solução encontrada no modo assistido" (pergunta no terminal) e "Teto de ciclos" saem pelos requisitos modificados acima; nenhum requisito inteiro é removido desta capacidade.
