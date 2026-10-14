# Especificação: hypothesis-loop

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md), [`v18.6-hypothesis-closure`](../../changes/archive/v18.6-hypothesis-closure/proposal.md), [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)

## Requirements

### Requirement: Hipóteses formais no plano
_Origem: [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md)_
O Researcher SHALL declarar as hipóteses do plano, cada subtarefa SHALL referenciar a hipótese
que testa, e o sistema SHALL gravá-las como nós `Hipotese` ligados ao problema.

#### Scenario: Plano com hipótese
- **WHEN** o Researcher gera um plano com a hipótese `h1` e duas subtarefas com `hypothesis_ref="h1"`
- **THEN** existe `Hipotese(status="proposta")` com `SOBRE->Problema`
- **AND** os experimentos das duas subtarefas têm `TESTA->` essa hipótese

#### Scenario: Hipótese repetida
- **GIVEN** uma hipótese do projeto com similaridade 0,94 à nova
- **WHEN** o plano é gravado
- **THEN** a hipótese existente é reutilizada

### Requirement: Autonomia governada pelo SessionMode
_Origem: [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md)_
O sistema SHALL exigir aprovação do pesquisador, no modo `assisted`, para hipóteses propostas
por agentes ou derivadas de oportunidades, e SHALL executar, nos modos `semi` e `auto`, as de
maior prioridade dentro do orçamento.

#### Scenario: Modo assistido
- **GIVEN** modo `assisted` e uma hipótese com `origem="researcher"`
- **WHEN** o ciclo chega à execução
- **THEN** a hipótese só é executada após aprovação; se rejeitada, fica `abandonada` com motivo

#### Scenario: Modo autônomo
- **GIVEN** modo `auto`, 4 hipóteses propostas e `HYPOTHESES_PER_CYCLE=2`
- **WHEN** o ciclo executa
- **THEN** as 2 de maior prioridade são executadas

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
_Origem: [`v18-hypothesis-loop`](../../changes/archive/v18-hypothesis-loop/proposal.md)_
O sistema SHALL repetir o ciclo planejar → executar → consolidar → sugerir até encontrar uma
solução, não haver caminhos promissores ou atingir um limite de uso.

#### Scenario: Solução encontrada no modo automático
- **GIVEN** modo `auto`
- **WHEN** uma hipótese sobre o problema atinge veredito ≥ `SOLUTION_MIN_VERDICT` e o melhor resultado atinge o alvo
- **THEN** a sessão fecha com `motivo_parada="solucao_encontrada"`

#### Scenario: Solução encontrada no modo assistido
- **GIVEN** modo `assisted`
- **WHEN** o critério de solução é atingido
- **THEN** o pesquisador escolhe entre encerrar e continuar explorando

#### Scenario: Sem caminhos
- **WHEN** não há hipótese nova, nem aprovada pendente, nem sugestão do Curator
- **THEN** a sessão fecha com `motivo_parada="sem_caminhos_promissores"`

#### Scenario: Planos rejeitados em sequência
- **WHEN** o Validator rejeita `MAX_PLAN_RETRIES` planos consecutivos
- **THEN** a sessão fecha com `motivo_parada="planos_rejeitados"`, com checkpoint
- **AND** retomar essa sessão exige confirmação do pesquisador

#### Scenario: Teto de ciclos
- **WHEN** a exploração atinge `MAX_EXPLORATION_CYCLES` ciclos
- **THEN** a sessão fecha com `motivo_parada="limite_ciclos"`, com checkpoint
- **AND** retomar essa sessão não exige confirmação

### Requirement: Resultado negativo na revisão
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)_
O revisor SHALL devolver `outcome = "resultado_negativo"` quando a subtarefa tem hipótese
resolvida, todos os artefatos esperados foram resolvidos e as únicas reprovações são comparações
determinísticas com a métrica presente e numérica. Em qualquer outro caso de reprovação, o
`outcome` SHALL ser `reprovado`. Quando a reprovação for exatamente essa comparação determinística e a única
razão de não ser `resultado_negativo` for a falta de `hypothesis_id`, o revisor SHALL registrar o motivo
`sem_hipotese` em `motivos`, no resultado e no evento `subtask_review`, sem alterar `status` nem `outcome`.

#### Scenario: Acurácia abaixo do alvo numa subtarefa com hipótese
- **GIVEN** a subtarefa `treinar_rl` com `hypothesis_id` resolvido, artefatos presentes e
  `metrics.json` com `accuracy` 0.933
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
