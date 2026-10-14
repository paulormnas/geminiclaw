# Delta: hypothesis-loop

## MODIFIED Requirements

### Requirement: Conferência do veredito no início da sessão
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

### Requirement: Fechamento por falta de caminhos promissores
A sessão SHALL fechar com `sem_caminhos_promissores` somente quando não há hipótese `em_teste` do
projeto sem tentativa (`n_tentativas = 0`), exceto as retiradas pela governança, e não há sugestão
pendente do Curator. Quando os ciclos ociosos se esgotam com hipótese sem tentativa, a sessão SHALL
fechar com `motivo_parada = "hipoteses_nao_testadas"`, registrar o evento `hipoteses_sem_tentativa` com o
motivo e a lista das hipóteses, e MUST NOT registrar resultado de erro.
(Antes: fechava com `erro` e a mesma mensagem.)

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

### Requirement: Resultado negativo na revisão
O revisor SHALL devolver `outcome = "resultado_negativo"` quando a subtarefa tem hipótese
resolvida, todos os artefatos esperados foram resolvidos e as únicas reprovações são comparações
determinísticas com a métrica presente e numérica. Em qualquer outro caso de reprovação, o
`outcome` SHALL ser `reprovado`. Quando a reprovação for exatamente essa comparação determinística e a única
razão de não ser `resultado_negativo` for a falta de `hypothesis_id`, o revisor SHALL registrar o motivo
`sem_hipotese` em `motivos`, no resultado e no evento `subtask_review`, sem alterar `status` nem `outcome`.

#### Scenario: Subtarefa sem hipótese
- **GIVEN** a acurácia 0.933 numa subtarefa sem `hypothesis_id`
- **WHEN** o revisor avalia "acurácia no teste >= 0.95"
- **THEN** `outcome` é `reprovado`
- **AND** `motivos` contém `sem_hipotese`

#### Scenario: Evento da revisão
- **GIVEN** o mesmo caso
- **WHEN** a revisão é registrada
- **THEN** o evento `subtask_review` leva `motivos = ["sem_hipotese"]`

#### Scenario: Reprovação com hipótese não leva o motivo
- **GIVEN** a acurácia 0.933 numa subtarefa com `hypothesis_id`
- **WHEN** o revisor avalia o mesmo critério
- **THEN** `motivos` é vazio

#### Scenario: Reprovação sem hipótese por outra causa não leva o motivo
- **GIVEN** uma subtarefa sem `hypothesis_id` cuja métrica está ausente de `metrics.json`
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado` e `motivos` é vazio

## ADDED Requirements

### Requirement: Definição de métricas pelo agente no modo auto
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
