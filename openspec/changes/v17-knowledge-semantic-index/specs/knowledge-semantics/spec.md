# Delta: knowledge-semantics

## ADDED Requirements

### Requirement: Vetor com o mesmo ID do nó
O sistema SHALL manter, para cada nó vetorizável, um ponto no Qdrant com o mesmo ID do nó, o
texto canônico do seu tipo e os metadados de embedding.

#### Scenario: Nó criado
- **WHEN** um `Problema` é criado
- **THEN** existe um ponto em `knowledge_nodes` com o mesmo ID, `tipo_no="Problema"` e `embedding_model`, `embedding_version`, `embedding_dim`, `text_hash`

#### Scenario: Tipos não vetorizados
- **WHEN** um `Experimento` ou `Resultado` é criado
- **THEN** nenhum ponto é gravado no Qdrant

### Requirement: Grafo como fonte da verdade
O sistema SHALL manter o nó válido mesmo que a vetorização falhe, e reconciliar depois.

#### Scenario: Qdrant indisponível
- **WHEN** a vetorização de um nó falha
- **THEN** o nó existe no grafo com `estado_vetorizacao="pendente"`
- **AND** a próxima reconciliação grava o ponto e muda o estado para `ok`

#### Scenario: Troca de modelo
- **WHEN** o modelo de embedding muda e a reconciliação roda
- **THEN** todos os pontos passam a ter os metadados do novo modelo

### Requirement: Consulta híbrida de experiência relacionada
O sistema SHALL responder "o que funcionou ou falhou em problemas parecidos" buscando problemas
similares no Qdrant e percorrendo o grafo a partir deles, com ranking por similaridade ×
confiança × recência.

#### Scenario: Experiência de outro projeto
- **GIVEN** um problema P2 similar (0,8) ao problema P1, com `Abordagem A-FUNCIONOU_PARA->P2`
- **WHEN** `related_experience(P1)` é chamado
- **THEN** a abordagem A aparece nos resultados com o problema P2 como origem

### Requirement: Faixas de similaridade
O sistema SHALL classificar pares de nós em duplicata (≥ 0,90), relacionado (0,70–0,90, ou
0,60–0,90 entre domínios diferentes) ou ignorado, com limiares configuráveis por modelo.

#### Scenario: Faixa baixa no mesmo domínio
- **WHEN** dois `Problema`s do mesmo domínio têm similaridade 0,65
- **THEN** o par não entra na fila

#### Scenario: Faixa baixa entre domínios
- **WHEN** um `Problema` de química e um de história têm similaridade 0,65
- **THEN** o par entra na fila como `relacionado`, com `entre_dominios=true`

#### Scenario: Duplicata
- **WHEN** duas `Abordagem`s têm similaridade 0,93
- **THEN** o par entra na fila como `duplicata`

### Requirement: Sem limite de conexões
O sistema MUST NOT limitar a quantidade de candidatos por nó ou por domínio; o volume é
controlado pela confirmação e pela prioridade de revisão.

#### Scenario: Muitos vizinhos
- **WHEN** um nó tem 50 vizinhos acima do limiar
- **THEN** 50 pares entram na fila

### Requirement: Fila de revisão fora do grafo
O sistema SHALL guardar os pares candidatos na tabela `similarity_queue`, e SHALL criar arestas
`SEMELHANTE_A` somente para pares confirmados.

#### Scenario: Candidato não vira aresta
- **WHEN** um par entra na fila
- **THEN** nenhuma aresta `SEMELHANTE_A` é criada até a confirmação

#### Scenario: Prioridade entre domínios
- **GIVEN** dois pares com o mesmo score, um entre domínios e outro não
- **WHEN** `next_batch` é chamado
- **THEN** o par entre domínios vem primeiro

#### Scenario: Par já avaliado
- **GIVEN** um par descartado
- **WHEN** a varredura o encontra de novo com os mesmos textos
- **THEN** ele não é reinserido
- **AND** se o texto de um dos nós mudar, o par pode voltar à fila

### Requirement: Oportunidades entre projetos exigem evidência
O sistema SHALL enfileirar pares `Descoberta→Problema` de projetos diferentes somente quando a
descoberta tiver `|veredito| ≥ 0,3`.

#### Scenario: Descoberta fraca
- **WHEN** uma descoberta com veredito 0,2 é similar (0,75) a um problema de outro projeto
- **THEN** o par não entra na fila

### Requirement: Calibração informada
O sistema SHALL calcular a taxa de confirmação da fila e sugerir ajustes de limiar, sem
alterar limiares automaticamente.

#### Scenario: Taxa baixa
- **GIVEN** 5% de confirmação na faixa 0,60–0,70 nos últimos 30 dias
- **WHEN** `geminiclaw knowledge stats` é executado
- **THEN** o relatório sugere subir o limite inferior e nenhuma configuração é alterada
