# Delta: reproduction-validation

## ADDED Requirements

### Requirement: Reprodução só por decisão do pesquisador
O sistema SHALL iniciar uma reprodução somente pelo comando `federation reproduce <cid>`
seguido de confirmação explícita do pesquisador depois de exibir autor, código, pacotes,
datasets e custo estimado, e MUST NOT reproduzir automaticamente (ADR 013 §3, §4).

#### Scenario: Confirmação negada
- **WHEN** o pesquisador responde "N" ao resumo da reprodução
- **THEN** nenhum container é criado e nada é registrado como reprodução

#### Scenario: Nenhum gatilho automático
- **WHEN** a sincronização recebe 10 registros `experimento` relevantes
- **THEN** nenhuma reprodução é iniciada

### Requirement: Execução determinística sem LLM, no sandbox
O sistema SHALL executar o código publicado sem alterações no sandbox, com pacotes nas versões
publicadas, datasets públicos verificados por sha256, parâmetros e seed publicados e execução
sem rede, e MUST NOT chamar modelos de linguagem durante a reprodução (ADR 013 §3, ADR 014,
ADR 019 §5).

#### Scenario: Sem LLM
- **WHEN** uma reprodução completa roda com o provedor LLM simulado
- **THEN** o provedor não recebe nenhuma chamada

#### Scenario: Hash do código divergente
- **GIVEN** um registro cujo código inline não confere com `hash_codigo`
- **WHEN** a reprodução é pedida
- **THEN** o resultado é `inconclusiva` com motivo `hash_divergente` e nada é executado

#### Scenario: Dataset privado
- **GIVEN** um registro `experimento` com dataset `{"nome": "x.csv", "privado": true}`
- **WHEN** a reprodução é pedida
- **THEN** o resultado é `inconclusiva` com motivo `dado_privado` sem executar

#### Scenario: Sem dados locais
- **WHEN** o container de execução da reprodução é criado
- **THEN** as únicas montagens são o diretório da reprodução, as dependências e os ativos verificados

### Requirement: Comparação com tolerância
O sistema SHALL considerar uma métrica reproduzida quando `|obtido − publicado| ≤
max(tol_abs, tol_rel × |publicado|)`, usando a tolerância declarada pelo autor (limitada a
`FEDERATION_REPRO_MAX_REL_TOL`) ou a padrão do nó, e SHALL classificar o resultado em
`confirmada`, `refutada` ou `inconclusiva`.

#### Scenario: Dentro da tolerância
- **GIVEN** publicado `"0.953"`, obtido 0,947 e tolerância relativa padrão 0,02
- **WHEN** a comparação roda
- **THEN** a métrica está dentro e, sendo a única, o resultado é `confirmada`

#### Scenario: Fora da tolerância
- **GIVEN** publicado `"0.953"` e obtido 0,80
- **WHEN** a comparação roda
- **THEN** o resultado é `refutada`

#### Scenario: Tolerância exagerada do autor
- **GIVEN** tolerância relativa declarada de 0,9
- **WHEN** a comparação roda
- **THEN** é usada a tolerância 0,2 e o registro informa o limite aplicado

#### Scenario: Falha de execução
- **GIVEN** o script termina com erro de importação
- **WHEN** a reprodução termina
- **THEN** o resultado é `inconclusiva` com motivo `erro_execucao`

### Requirement: Registro de reprodução assinado e revisado
O sistema SHALL montar um registro `reproducao` com referência ao `experimento`, resultado,
métricas publicadas e obtidas, tolerâncias usadas, ambiente efetivo e hash do código
verificado, e SHALL publicá-lo somente pela caixa de saída com revisão humana.

#### Scenario: Registro montado
- **WHEN** uma reprodução `confirmada` termina
- **THEN** existe um candidato `reproducao` na caixa de saída com `refs` contendo o `cid` do experimento e o ambiente efetivo

### Requirement: Limites de custo
O sistema SHALL interromper a reprodução que exceder `FEDERATION_REPRO_MAX_MINUTES`, com
resultado `inconclusiva` (`tempo_excedido`), e SHALL recusar novas reproduções além de
`FEDERATION_REPRO_MAX_PER_DAY` no dia.

#### Scenario: Limite diário
- **GIVEN** `FEDERATION_REPRO_MAX_PER_DAY=3` e três reproduções no dia
- **WHEN** o pesquisador pede a quarta
- **THEN** o pedido é recusado com mensagem que cita o limite
