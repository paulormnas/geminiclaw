# Delta: hypothesis-loop

## ADDED Requirements

### Requirement: Hipóteses formais no plano
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
O Curator SHALL sugerir caminhos ao Researcher a cada ciclo, a partir de fontes permitidas, e o
Researcher SHALL responder a cada sugestão aceitando ou recusando com motivo.

#### Scenario: Sugestão aceita
- **WHEN** o Researcher aceita uma sugestão baseada em um caminho sem conclusão
- **THEN** uma hipótese com `origem="curator"` e `DERIVADA_DE` a descoberta é criada

#### Scenario: Sugestão sem resposta
- **WHEN** o plano não responde a uma sugestão pendente
- **THEN** o plano volta ao Researcher uma vez pedindo a resposta

### Requirement: Oportunidades só com decisão humana
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
- **THEN** a sessão fecha registrando o motivo, com checkpoint
