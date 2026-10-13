# Delta: hypothesis-loop

## ADDED Requirements

### Requirement: Resultado negativo na revisão
O revisor SHALL devolver `outcome = "resultado_negativo"` quando a subtarefa tem hipótese
resolvida, todos os artefatos esperados foram resolvidos e as únicas reprovações são comparações
determinísticas com a métrica presente e numérica. Em qualquer outro caso de reprovação, o
`outcome` SHALL ser `reprovado`.

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

#### Scenario: Subtarefa sem hipótese
- **GIVEN** a acurácia 0.933 numa subtarefa sem `hypothesis_id`
- **WHEN** o revisor avalia
- **THEN** `outcome` é `reprovado`

#### Scenario: Recurso desligado
- **GIVEN** `NEGATIVE_RESULT_AS_PROGRESS=false`
- **WHEN** o revisor avalia o primeiro cenário
- **THEN** `outcome` é `reprovado`

### Requirement: Resultado negativo conclui a subtarefa e conta como progresso
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
A ingestão SHALL registrar o evento `resultado_sem_mede` quando o nome base de um `Resultado`
corresponde à métrica do `Problema` e a aresta `MEDE` não foi criada, com o motivo
(`metrica_nao_aprovada`, `qualificador_excluido` ou `resolucao_falhou`).

#### Scenario: Métrica candidata
- **GIVEN** a `Metrica` do `Problema` com status `candidato`
- **WHEN** a ingestão grava um `Resultado` `accuracy`
- **THEN** o evento `resultado_sem_mede` é registrado com motivo `metrica_nao_aprovada`

### Requirement: Conferência do veredito no início da sessão
Com projeto ativo, o sistema SHALL conferir antes do primeiro planejamento se a `Metrica` do
`Problema` está aprovada no vocabulário. Se não estiver, o sistema SHALL registrar o evento
`veredito_indisponivel` com o motivo e a correção e avisar no banner. No modo `auto`, a sessão
MUST terminar com `erro` antes de planejar.

#### Scenario: Modo auto sem métrica aprovada
- **GIVEN** um projeto cujo `Problema` usa uma `Metrica` `candidato`
- **WHEN** a sessão inicia no modo `auto`
- **THEN** a sessão termina com `erro` sem chamar o Researcher
- **AND** a mensagem cita `scripts/seed_vocabulary.py`

#### Scenario: Modo assistido sem métrica aprovada
- **GIVEN** o mesmo projeto
- **WHEN** a sessão inicia no modo `assisted`
- **THEN** o banner mostra o aviso e a sessão segue

### Requirement: Evidência das afirmações sem código de referência
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

## MODIFIED Requirements

### Requirement: Fechamento por falta de caminhos promissores
A sessão SHALL fechar com `sem_caminhos_promissores` somente quando não há hipótese `em_teste` do
projeto sem tentativa (`n_tentativas = 0`), exceto as retiradas pela governança, e não há sugestão
pendente do Curator. Quando os ciclos ociosos se esgotam com hipótese sem tentativa, a sessão SHALL
fechar com `erro` e a mensagem que lista as hipóteses.
(Antes: hipóteses presentes no plano eram ignoradas ao decidir se havia caminho aberto.)

#### Scenario: Hipótese no plano sem tentativa
- **GIVEN** a hipótese `h1` `em_teste`, no plano, com `n_tentativas = 0`, e um ciclo sem subtarefa nova
- **WHEN** o laço decide se há caminho aberto
- **THEN** a sessão não fecha com `sem_caminhos_promissores`
- **AND** o feedback do ciclo cita `h1`

#### Scenario: Ciclos ociosos esgotados
- **GIVEN** dois ciclos ociosos e `h1` ainda sem tentativa
- **WHEN** o segundo ciclo ocioso termina
- **THEN** a sessão fecha com `erro` e a mensagem "hipóteses sem tentativa após 2 ciclos ociosos: h1"

#### Scenario: Todas as hipóteses testadas
- **GIVEN** todas as hipóteses `em_teste` com ao menos uma tentativa e nenhuma sugestão do Curator
- **WHEN** um ciclo não traz subtarefa nova
- **THEN** a sessão fecha com `sem_caminhos_promissores`
