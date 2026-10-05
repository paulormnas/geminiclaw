# Delta: communication-eval

## ADDED Requirements

### Requirement: Avaliação pós-execução
O sistema SHALL calcular a avaliação de comunicação somente a partir do que a sessão já gravou
(banco e pasta da sessão), depois da execução, e SHALL NOT alterar o estado nem o resultado da
sessão avaliada.

#### Scenario: Avaliação não escreve na sessão
- **GIVEN** uma sessão concluída
- **WHEN** a avaliação roda
- **THEN** nenhum arquivo da pasta da sessão nem registro de `agent_events` é criado ou alterado
- **AND** o resultado é gravado em `communication_eval.json` fora da pasta da sessão avaliada

#### Scenario: Evento esperado ausente
- **GIVEN** uma sessão sem eventos `subtask_review`
- **WHEN** a avaliação roda
- **THEN** os campos de revisor trazem `null` e o relatório diz que não há revisões a avaliar,
  sem erro e sem zeros inventados

### Requirement: Verdade determinística por subtarefa
O sistema SHALL classificar cada tentativa de subtarefa revisada como `fulfilled`,
`unfulfilled` ou `indeterminate` a partir de artefatos esperados (comparador tolerante),
critérios com métrica nomeada contra `metrics.json` e código de saída do sandbox, sem usar LLM.

#### Scenario: Artefatos e métrica cumpridos
- **GIVEN** os artefatos esperados presentes e `metrics.json` com `accuracy` 0,95 para o critério
  "acurácia >= 0.9"
- **WHEN** a verdade é calculada
- **THEN** a tentativa é `fulfilled`

#### Scenario: Artefato com outro prefixo
- **GIVEN** `eda_*.png` esperado e `iris_hist.png` em disco, como no benchmark de 2026-10-01
- **WHEN** a verdade é calculada
- **THEN** a verificação de artefato é `ok` e a tentativa é `fulfilled`

#### Scenario: Artefato ausente
- **GIVEN** um artefato esperado sem arquivo equivalente
- **WHEN** a verdade é calculada
- **THEN** a tentativa é `unfulfilled` e a verificação lista o artefato

#### Scenario: Só critérios qualitativos
- **GIVEN** nenhum artefato esperado e critérios sem métrica nomeada
- **WHEN** a verdade é calculada
- **THEN** a tentativa é `indeterminate`

#### Scenario: Código de saída não decide sozinho
- **GIVEN** um `sandbox_run` com `exit_code=0`, nenhum artefato esperado e critérios qualitativos
- **WHEN** a verdade é calculada
- **THEN** a tentativa é `indeterminate`

#### Scenario: Artefatos sobrescritos por tentativa posterior
- **GIVEN** um artefato com mtime posterior ao evento de revisão da tentativa avaliada
- **WHEN** a verdade é calculada
- **THEN** a tentativa é `indeterminate` com `detail="artefatos sobrescritos"`

### Requirement: Veredito do revisor contra a verdade
O sistema SHALL comparar cada veredito do revisor com a verdade determinística, classificando em
acerto, falso reprovado, falso aprovado ou indeterminada, e SHALL reportar as taxas por modelo
do revisor, listando os desacordos.

#### Scenario: Falso reprovado
- **GIVEN** uma revisão `fail` e verdade `fulfilled`
- **WHEN** a avaliação roda
- **THEN** a matriz conta um falso reprovado e a lista de desacordos traz tarefa, tentativa e
  assinatura

#### Scenario: Falso aprovado
- **GIVEN** uma revisão `pass` e verdade `unfulfilled`
- **WHEN** a avaliação roda
- **THEN** a matriz conta um falso aprovado

#### Scenario: Indeterminadas fora das taxas
- **GIVEN** 4 revisões determináveis (3 acertos, 1 falso reprovado) e 2 indeterminadas
- **WHEN** as taxas são calculadas
- **THEN** `false_reject_rate` usa só as determináveis e `indeterminate_share` é 2/6

#### Scenario: Denominador zero
- **GIVEN** nenhuma tentativa `unfulfilled`
- **WHEN** `false_accept_rate` é calculada
- **THEN** o valor é `null`, não zero

### Requirement: Taxa de resolução das reprovações
O sistema SHALL calcular, para planos e subtarefas, a fração de reprovações seguidas de
aprovação no mesmo alvo e o número de reprovações consecutivas até a aprovação, e SHALL
reportar à parte as reprovações sem evento seguinte.

#### Scenario: Reprovação resolvida
- **GIVEN** a sequência do alvo `modelo`: reprovada, reprovada, aprovada
- **WHEN** a resolução é calculada
- **THEN** as duas reprovações contam como resolvidas e `attempts_to_resolve` é 2

#### Scenario: Reprovação final sem evento seguinte
- **GIVEN** a sequência do alvo `eda`: aprovada, reprovada (fim da sessão)
- **WHEN** a resolução é calculada
- **THEN** a reprovação conta em `unresolved_tail` e fora do denominador

#### Scenario: Plano aprovado com avisos
- **GIVEN** reprovações do plano seguidas de `approved_with_warnings`
- **WHEN** a resolução é calculada
- **THEN** a última reprovação conta como resolvida

### Requirement: Detecção de laços de reprovação
O sistema SHALL detectar laços (`LOOP_MIN_LENGTH` ou mais reprovações consecutivas do mesmo
alvo com a mesma assinatura) e SHALL reportar, por sessão, o número de laços, o comprimento
máximo e a fração das reprovações que ocorreram em laço, separando Validator e revisor.

#### Scenario: Laço de três
- **GIVEN** `LOOP_MIN_LENGTH=3` e três reprovações do alvo `modelo` com a mesma assinatura
- **WHEN** os laços são detectados
- **THEN** há um laço de comprimento 3 atribuído ao revisor

#### Scenario: Duas reprovações iguais não são laço
- **GIVEN** `LOOP_MIN_LENGTH=3` e duas reprovações seguidas com a mesma assinatura
- **WHEN** os laços são detectados
- **THEN** nenhum laço é registrado

#### Scenario: Assinaturas diferentes
- **GIVEN** três reprovações seguidas do mesmo alvo com assinaturas diferentes
- **WHEN** os laços são detectados
- **THEN** nenhum laço é registrado

### Requirement: Reparos do planejador medidos
O sistema SHALL reportar, por sessão e por modelo do Researcher, quantos planos receberam reparo
do normalizador e a contagem por tipo de reparo.

#### Scenario: Contagem de reparos
- **GIVEN** 3 planos gerados, 2 com eventos `plan_normalized` de tipos `coerce_list` e
  `snake_case_name`
- **WHEN** a avaliação roda
- **THEN** `plans=3`, `with_repair=2` e `by_kind` traz as contagens de cada tipo

### Requirement: Juiz de perguntas de `ask_researcher` independente
O sistema SHALL avaliar cada evento `ask_researcher` com um juiz LLM configurado por
`COMM_EVAL_JUDGE_PROVIDER` e `COMM_EVAL_JUDGE_MODEL`, SHALL recusar a avaliação com erro
explícito se a configuração estiver ausente, e SHALL recusar o evento cujo agente de origem usa
o mesmo provedor do juiz.

#### Scenario: Juiz sem configuração
- **GIVEN** `COMM_EVAL_JUDGE_PROVIDER` ausente
- **WHEN** a avaliação do juiz é solicitada
- **THEN** a avaliação do juiz termina com erro que nomeia a variável ausente
- **AND** o restante da avaliação (verdade, laços) continua

#### Scenario: Mesmo provedor
- **GIVEN** um evento perguntado por um agente do provedor `google` e um juiz do provedor `google`
- **WHEN** o juiz é chamado
- **THEN** o evento é marcado `judge_skipped: same_provider` e nenhuma chamada é feita

#### Scenario: Nota válida
- **GIVEN** um juiz de provedor diferente que devolve `{"necessidade": 3, "clareza": 2,
  "justificativa": "..."}`
- **WHEN** o evento é avaliado
- **THEN** as notas são gravadas com o modelo e a versão da rubrica

#### Scenario: Saída inválida
- **GIVEN** um juiz que devolve texto sem JSON válido duas vezes
- **WHEN** o evento é avaliado
- **THEN** o evento é marcado `judge_error` e nenhuma nota é gravada

#### Scenario: Critérios de resposta só com resposta
- **GIVEN** um evento sem resposta registrada
- **WHEN** o evento é avaliado
- **THEN** só `necessidade` e `clareza` são avaliadas; `resposta` e `efeito` ficam ausentes

#### Scenario: Efeito determinístico
- **GIVEN** uma resposta com a opção escolhida e a opção aparece no prompt da tentativa seguinte
- **WHEN** `efeito` é calculado
- **THEN** o valor vem do código, sem chamada ao juiz

### Requirement: Dados enviados ao juiz externo
O sistema SHALL recusar juiz de provedor externo ao nó quando `COMM_EVAL_ALLOW_EXTERNAL_JUDGE`
for falso (padrão), SHALL redigir o texto enviado (decimais e sequências longas de dígitos,
nomes de arquivos de entrada e de artefatos, URLs, e-mails) e SHALL truncar o contexto em
`COMM_EVAL_JUDGE_CONTEXT_CHARS`.

#### Scenario: Juiz externo não habilitado
- **GIVEN** `COMM_EVAL_ALLOW_EXTERNAL_JUDGE=false` e um juiz de provedor de nuvem
- **WHEN** o juiz é chamado
- **THEN** a avaliação do juiz é recusada com erro explícito e nada sai do nó

#### Scenario: Redação
- **GIVEN** um contexto com "acurácia 0.9667 em iris.csv, ver https://exemplo.org e a@b.c"
- **WHEN** `redact_for_judge` é aplicada
- **THEN** o texto contém `<num>`, `<arquivo>`, `<url>` e `<email>` e nenhum dos valores originais

#### Scenario: Truncamento
- **GIVEN** `COMM_EVAL_JUDGE_CONTEXT_CHARS=400` e um contexto de 2 000 caracteres
- **WHEN** o texto é montado
- **THEN** o contexto enviado tem no máximo 400 caracteres

### Requirement: Teto de custo do juiz
O sistema SHALL parar o juiz ao atingir `COMM_EVAL_MAX_USD` (padrão `0`, que não permite
chamada paga), marcando os eventos restantes `judge_skipped: budget`.

#### Scenario: Teto zero
- **GIVEN** `COMM_EVAL_MAX_USD=0` e um juiz de provedor pago
- **WHEN** o juiz é solicitado
- **THEN** nenhuma chamada é feita e todos os eventos ficam `judge_skipped: budget`

#### Scenario: Teto atingido no meio
- **GIVEN** `COMM_EVAL_MAX_USD=0.01` e custo acumulado que ultrapassa o teto no terceiro evento
- **WHEN** o juiz avalia 5 eventos
- **THEN** os eventos 1 a 3 têm nota e os eventos 4 e 5 ficam `judge_skipped: budget`

### Requirement: Calibração humana do juiz
O sistema SHALL gerar uma amostra determinística e estratificada de `COMM_EVAL_CALIBRATION_SIZE`
eventos para rotulagem humana, SHALL calcular o kappa de Cohen ponderado entre juiz e humano por
critério, e SHALL marcar como `não calibrado` toda nota do juiz quando o kappa de algum critério
estiver abaixo de `COMM_EVAL_MIN_KAPPA` ou houver menos eventos rotulados que o tamanho da
amostra.

#### Scenario: Amostra reprodutível
- **GIVEN** o mesmo conjunto de eventos e a mesma semente
- **WHEN** a amostra é gerada duas vezes
- **THEN** as duas amostras são idênticas e cada papel que perguntou aparece na amostra, se
  houver eventos dele

#### Scenario: Concordância total
- **GIVEN** notas do juiz iguais às do humano em 20 eventos
- **WHEN** o kappa é calculado
- **THEN** o kappa é 1,0 e as notas saem sem o selo `não calibrado`

#### Scenario: Concordância baixa
- **GIVEN** `COMM_EVAL_MIN_KAPPA=0.6` e kappa de 0,4 em `necessidade`
- **WHEN** o relatório é gerado
- **THEN** todas as notas do juiz trazem `não calibrado` e o relatório mostra o kappa 0,4

#### Scenario: Poucos rótulos
- **GIVEN** 12 eventos rotulados e `COMM_EVAL_CALIBRATION_SIZE=20`
- **WHEN** o relatório é gerado
- **THEN** as notas trazem `não calibrado` mesmo com kappa alto

#### Scenario: Mudança de modelo invalida a calibração
- **GIVEN** rótulos calibrados com o modelo A e o juiz agora configurado com o modelo B
- **WHEN** o relatório é gerado
- **THEN** a calibração é tratada como ausente e as notas trazem `não calibrado`

### Requirement: Integração com o relatório do benchmark
O sistema SHALL incluir o bloco de comunicação no relatório do benchmark sem alterar a saída
atual de `summarize_events`, e SHALL executar a avaliação somente depois da execução quando
`--eval-comm` for informado.

#### Scenario: Saída atual preservada
- **WHEN** `summarize_events` roda sobre os mesmos eventos antes e depois da mudança
- **THEN** o resultado é idêntico

#### Scenario: Ordem de execução
- **WHEN** o benchmark roda com `--eval-comm`
- **THEN** a avaliação começa depois do término da sessão avaliada
