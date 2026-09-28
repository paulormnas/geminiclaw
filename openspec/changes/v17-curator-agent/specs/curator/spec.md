# Delta: curator

## ADDED Requirements

### Requirement: Papel Curator
O sistema SHALL oferecer o agente Curator, executado em processo, responsável por registrar o
conhecimento interpretado no grafo: descobertas, oportunidades, caminhos sem conclusão e
confirmação de similaridades.

#### Scenario: Checkpoint de consolidação
- **WHEN** um ciclo de planejamento termina
- **THEN** o Curator consolida as sinalizações pendentes e os novos resultados da sessão

#### Scenario: Falha do Curator
- **WHEN** a chamada ao LLM do Curator falha
- **THEN** a sessão continua e as pendências permanecem para a próxima execução

### Requirement: Revisão antes de criar
As ferramentas de escrita do Curator SHALL buscar nós semelhantes antes de criar
`Descoberta`, `Oportunidade` ou caminho sem conclusão, e SHALL recusar a criação de duplicatas.

#### Scenario: Duplicata
- **GIVEN** uma `Descoberta` existente com similaridade 0,93 à proposta
- **WHEN** `create_discovery` é chamado
- **THEN** a criação é recusada e o ID existente é devolvido com orientação para `reinforce_discovery`

#### Scenario: Variação sem diferença explícita
- **GIVEN** uma `Descoberta` existente com similaridade 0,78
- **WHEN** `create_discovery` é chamado sem `diferenca`
- **THEN** a criação é recusada

#### Scenario: Variação justificada
- **WHEN** `create_discovery` é chamado com `variacao_de` e `diferenca` preenchidos
- **THEN** a descoberta é criada ligada à original
- **AND** `nos_consultados` contém os IDs verificados

### Requirement: Somente conhecimento significativo com evidência
O sistema SHALL criar uma `Descoberta` somente se ela apontar um novo caminho de pesquisa ou
documentar um caminho explorado, e SHALL exigir evidência ligada.

#### Scenario: Sem evidência
- **WHEN** `create_discovery(tipo="funciona", evidencia_ids=[])` é chamado
- **THEN** a criação é recusada

#### Scenario: Caminho sem conclusão
- **GIVEN** uma hipótese interrompida por limite de tempo
- **WHEN** a sessão termina
- **THEN** o Curator registra uma `Descoberta(tipo="caminho_sem_conclusao")` com `ponto_de_parada`, `motivo` e `proximo_passo_sugerido`

### Requirement: Veredito calculado sem LLM
O sistema SHALL recalcular, de forma determinística, o veredito das hipóteses e descobertas
afetadas após cada subtarefa, mantendo `SUSTENTA`/`REFUTA` com peso e os atalhos
`FUNCIONOU_PARA`/`FALHOU_PARA`.

#### Scenario: Recálculo após resultado
- **WHEN** um novo resultado validado é ingerido para uma hipótese
- **THEN** `suporte`, `certeza`, `veredito` e `n_tentativas` da hipótese são atualizados
- **AND** existe `Resultado-SUSTENTA->Hipotese` ou `Resultado-REFUTA->Hipotese` com `peso` igual ao `w` calculado

#### Scenario: Atalho contestado
- **GIVEN** `Abordagem-FUNCIONOU_PARA->Problema` com descoberta de veredito 0,2
- **WHEN** novas evidências levam o veredito a 0,05
- **THEN** a aresta passa a `status="contestada"`

#### Scenario: Descoberta condicional
- **GIVEN** uma descoberta com `filtro_condicoes = {"dataset_ids": ["d1"]}`
- **WHEN** o veredito é recalculado
- **THEN** apenas tentativas com o dataset `d1` entram na conta

### Requirement: Promoção de configuração
O sistema SHALL promover uma configuração a `Abordagem(tipo="configuracao")` quando ela tiver
ao menos 3 resultados positivos validados em ao menos 2 projetos.

#### Scenario: Critério não atingido
- **WHEN** a configuração tem 3 positivos validados em um único projeto
- **THEN** nenhuma abordagem é criada

#### Scenario: Critério atingido
- **WHEN** a configuração tem 3 positivos validados em 2 projetos
- **THEN** uma `Abordagem(tipo="configuracao")` é criada com `VARIANTE_DE` a abordagem base
- **AND** reexecutar a detecção não cria outra

### Requirement: Sinalizações de outros agentes
O sistema SHALL permitir que Researcher, Developer e Validator sinalizem pontos ao Curator, que
decide registrar ou descartar cada um com motivo.

#### Scenario: Sinalização registrada
- **WHEN** o Developer chama `flag_for_curator(tipo="falha_relevante", ...)`
- **THEN** a sinalização aparece em `pending_flags` no próximo checkpoint
- **AND** após a revisão fica marcada como `registrada` ou `descartada` com motivo

### Requirement: Revisão da fila de similaridade
O Curator SHALL revisar pares da fila por ordem de prioridade dentro do seu orçamento, criando
`SEMELHANTE_A` apenas para pares confirmados.

#### Scenario: Orçamento
- **GIVEN** 50 pares pendentes e `CURATOR_QUEUE_BATCH=20`
- **WHEN** o Curator executa
- **THEN** no máximo 20 pares são revisados e os demais continuam pendentes

### Requirement: Duplicatas de abordagem fundidas sem apagar
O sistema SHALL fundir abordagens duplicadas marcando a duplicada como `fundida` com
`FUNDIDA_EM`, sem apagar nós ou arestas.

#### Scenario: Fusão
- **WHEN** "resnet18" é fundida em "ResNet-18"
- **THEN** ambas existem, a primeira com `status="fundida"`, e o veredito da canônica passa a incluir as tentativas da fundida

### Requirement: Nenhuma remoção pelo Curator
As ferramentas do Curator MUST NOT apagar nós ou arestas nem executar Cypher de escrita.

#### Scenario: Inventário
- **WHEN** as ferramentas do Curator são inspecionadas
- **THEN** nenhuma remove dados, e a única consulta livre usa o papel somente-leitura
