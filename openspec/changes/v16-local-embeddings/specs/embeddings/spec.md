# Delta: embeddings

## ADDED Requirements

### Requirement: Embeddings gerados localmente
O sistema SHALL gerar todo embedding com um modelo executado no próprio computador, por meio
da interface `EmbeddingProvider`.

#### Scenario: Indexação usa o provedor local
- **WHEN** um documento é indexado no Qdrant
- **THEN** os vetores são produzidos por `get_embedding_provider()`
- **AND** nenhuma requisição de rede é feita durante o cálculo

#### Scenario: Busca usa o mesmo modelo
- **WHEN** uma busca semântica é feita
- **THEN** o vetor da consulta é produzido por `embed_query` do mesmo provedor que gerou os vetores armazenados

### Requirement: Nenhum conteúdo de pesquisa enviado a provedores externos
O sistema MUST NOT enviar textos ou vetores de embedding a serviços externos (Google, OpenAI,
Anthropic ou quaisquer outros).

#### Scenario: Não há fábrica de embedding remota
- **WHEN** a lista de provedores de embedding registrados é inspecionada
- **THEN** todos são backends locais, e nenhum aceita URL de serviço

#### Scenario: Modo offline
- **GIVEN** `EMBEDDING_OFFLINE=true` e o modelo em cache
- **WHEN** o provedor é inicializado
- **THEN** nenhum download é tentado

### Requirement: Versão do embedding como metadado
O sistema SHALL gravar em cada ponto do Qdrant os campos `embedding_model`,
`embedding_version`, `embedding_dim` e `text_hash`.

#### Scenario: Metadados presentes
- **WHEN** um trecho é indexado
- **THEN** o payload do ponto contém os quatro campos com os valores do provedor atual
- **AND** o texto de origem do trecho é recuperável pelo payload ou por `document_chunks`

### Requirement: Remoção dos vetores aleatórios
O sistema MUST NOT gerar vetores aleatórios ou fictícios em código de produção.

#### Scenario: Busca retorna o documento relevante
- **GIVEN** dois trechos indexados, um sobre "cristalografia de raios X" e outro sobre "receitas de pão"
- **WHEN** a busca é feita por "difração de raios X em cristais"
- **THEN** o trecho de cristalografia é o primeiro resultado

### Requirement: Proteção contra mistura de modelos
O sistema SHALL impedir que vetores de modelos ou versões diferentes sejam comparados entre si.

#### Scenario: Dimensão incompatível
- **GIVEN** uma coleção criada com dimensão 384 e um modelo configurado de dimensão 768
- **WHEN** o indexador inicializa
- **THEN** a coleção não é recriada automaticamente
- **AND** a busca semântica dessa coleção é desabilitada com mensagem indicando `geminiclaw embeddings reindex`

#### Scenario: Pontos desatualizados na busca
- **GIVEN** pontos gravados com uma versão anterior do modelo
- **WHEN** uma busca é feita
- **THEN** esses pontos são excluídos dos resultados e um aviso informa quantos estão desatualizados

### Requirement: Reindexação sob confirmação
O sistema SHALL oferecer o comando `geminiclaw embeddings reindex`, que revetoriza os pontos
desatualizados a partir do texto de origem após confirmação do pesquisador.

#### Scenario: Reindexação confirmada
- **GIVEN** 10 pontos com versão antiga e texto de origem disponível
- **WHEN** o comando é executado e o pesquisador confirma
- **THEN** os 10 pontos passam a ter os metadados da versão atual
- **AND** o relatório final informa 10 atualizados

#### Scenario: Reindexação recusada
- **WHEN** o pesquisador não confirma
- **THEN** nenhum ponto é alterado
