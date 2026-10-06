# Delta: domain-search

## ADDED Requirements

### Requirement: Texto canônico hierárquico do domínio
O sistema SHALL montar o texto vetorizado de um `Dominio` com termo, nível, caminho completo da grande área até
o termo, os ancestrais por nível e os sinônimos aprovados, em campos nomeados e em ordem fixa, por uma função
pura que recebe os ancestrais já resolvidos.

#### Scenario: Especialidade com todos os ancestrais
- **GIVEN** a especialidade "Conjuntos" sob "Álgebra", "Matemática" e "Ciências Exatas e da Terra"
- **WHEN** o texto canônico é montado
- **THEN** ele contém `Caminho: Ciências Exatas e da Terra > Matemática > Álgebra > Conjuntos`
- **AND** contém as linhas `Grande área`, `Área` e `Subárea` com os ancestrais correspondentes

#### Scenario: Grande área
- **GIVEN** a grande área "Ciências Exatas e da Terra"
- **WHEN** o texto canônico é montado
- **THEN** só há as linhas `Domínio`, `Nível` e `Caminho`, e o caminho tem um só elemento

#### Scenario: Sinônimos candidatos ficam de fora
- **GIVEN** um domínio com `sinonimos=["set theory"]` e `sinonimos_candidatos=["conjuntos fuzzy"]`
- **WHEN** o texto canônico é montado
- **THEN** a linha `Sinônimos` contém `set theory` e não contém `conjuntos fuzzy`

#### Scenario: Texto estável
- **GIVEN** o mesmo domínio e os mesmos ancestrais
- **WHEN** o texto é montado duas vezes
- **THEN** os textos são idênticos e têm o mesmo `text_hash`

### Requirement: Payload hierárquico no índice
O sistema SHALL gravar no ponto do `Dominio` os campos `nivel`, `caminho_ids` (da raiz ao próprio nó, em ordem),
`caminho_termos`, `caminho_completo` e `codigo_cnpq`.

#### Scenario: Ordem do caminho
- **GIVEN** a especialidade "Conjuntos" do exemplo acima
- **WHEN** o ponto é indexado
- **THEN** `caminho_ids` tem quatro IDs, do primeiro (grande área) ao último (o próprio nó)
- **AND** `nivel` é `especialidade` e `caminho_completo` é `true`

#### Scenario: Candidato sem pai
- **GIVEN** um termo `candidato` sem aresta `SUBAREA_DE`
- **WHEN** o ponto é indexado
- **THEN** `caminho_ids` tem um só elemento e `caminho_completo` é `false`

#### Scenario: Cadeia interrompida
- **GIVEN** um domínio cujo pai não existe no grafo
- **WHEN** o ponto é indexado
- **THEN** a escrita do nó não falha, `caminho_completo` é `false` e um aviso estruturado é registrado

### Requirement: Reconciliação por ancestral
O sistema SHALL marcar como `pendente` os descendentes de um domínio cujo termo ou sinônimos aprovados mudam, em
lotes de `DOMAIN_REINDEX_BATCH`, para que a reconciliação do índice os revetorize.

#### Scenario: Renomeação de uma área
- **GIVEN** uma área com 3 subáreas e 10 especialidades indexadas
- **WHEN** o termo da área é alterado
- **THEN** as 13 descendentes ficam com `estado_vetorizacao="pendente"` e a reconciliação atualiza o texto e o
  `text_hash` de cada uma

#### Scenario: Lote limitado
- **GIVEN** `DOMAIN_REINDEX_BATCH=200` e 450 descendentes
- **WHEN** o termo do ancestral muda
- **THEN** a marcação é feita em três lotes de no máximo 200

### Requirement: Busca hierárquica de domínios
O sistema SHALL buscar domínios por similaridade semântica e devolver, para cada candidato, o termo, o nível, o
caminho completo, o score, o status e os sinônimos, ordenados por score, com preferência pelo nível mais
específico quando a pontuação está dentro de `DOMAIN_SPECIFICITY_MARGIN` do melhor resultado.

#### Scenario: Caminho completo no resultado
- **GIVEN** um índice com a hierarquia de Ciência da Computação
- **WHEN** o agente busca "inteligência artificial"
- **THEN** o primeiro resultado traz `caminho` desde a grande área e `nivel`

#### Scenario: Preferência pelo mais específico
- **GIVEN** uma área e uma subárea filha com scores 0,72 e 0,71 e `DOMAIN_SPECIFICITY_MARGIN=0.03`
- **WHEN** a busca é feita
- **THEN** a subárea vem antes da área

#### Scenario: Fora da margem vale o score
- **GIVEN** uma área com score 0,80 e uma subárea filha com score 0,70
- **WHEN** a busca é feita
- **THEN** a área vem antes da subárea

#### Scenario: Restrição à subárvore
- **GIVEN** `dentro_de` igual ao código CNPq de uma área
- **WHEN** a busca é feita
- **THEN** todos os resultados têm essa área em `caminho_ids`

#### Scenario: Nível máximo
- **GIVEN** `nivel_maximo="area"`
- **WHEN** a busca é feita
- **THEN** nenhum resultado é `subarea` nem `especialidade`

#### Scenario: Candidatos excluídos por padrão
- **GIVEN** um termo `candidato` muito similar à consulta
- **WHEN** a busca é feita sem `incluir_candidatos`
- **THEN** o candidato não aparece
- **AND** com `incluir_candidatos=true` ele aparece com `status="candidato"`

#### Scenario: Sem correspondência
- **GIVEN** que nenhum domínio atinge `DOMAIN_SEARCH_MIN_SCORE`
- **WHEN** a busca é feita
- **THEN** o resultado é vazio

#### Scenario: Limite de resultados
- **GIVEN** `limit=50`
- **WHEN** a busca é feita
- **THEN** no máximo 10 resultados são devolvidos

#### Scenario: Entrada vazia
- **WHEN** a busca recebe texto vazio
- **THEN** ocorre `ValueError`

#### Scenario: Entrada longa
- **GIVEN** `DOMAIN_SEARCH_MAX_QUERY_CHARS=300` e um texto de 2 000 caracteres
- **WHEN** a busca é feita
- **THEN** a consulta usa só os 300 primeiros caracteres e o truncamento é registrado

### Requirement: Ferramenta `buscar_dominio` somente leitura
O sistema SHALL oferecer ao Researcher e ao Curator a ferramenta `buscar_dominio`, que devolve até 10 candidatos
em texto curto com o caminho completo, sem escrever no grafo, em arquivo ou em rede, e SHALL NOT registrá-la para o
`developer`.

#### Scenario: Resposta curta e estável
- **WHEN** o Researcher chama `buscar_dominio` com "aprendizado de máquina"
- **THEN** a resposta lista candidatos no formato `<caminho>  (<nível>, score <valor>, id=<id>)`
- **AND** tem no máximo 2 000 caracteres

#### Scenario: Sem correspondência
- **GIVEN** que a busca não encontra candidato
- **WHEN** a ferramenta responde
- **THEN** a resposta contém `sem_correspondencia: true`

#### Scenario: `dentro_de` desconhecido
- **WHEN** a ferramenta recebe `dentro_de` que não é código nem ID de nenhum domínio
- **THEN** a resposta é um erro explícito e nenhuma busca global é feita

#### Scenario: Consulta tratada como dado
- **WHEN** o texto da consulta contém `}) DETACH DELETE (n) //`
- **THEN** nenhum comando é interpolado e o grafo não é alterado

#### Scenario: Telemetria sem a consulta
- **WHEN** a ferramenta é chamada
- **THEN** o evento `domain_search` registra `resultados`, `melhor_score` e `nivel_do_melhor`
- **AND** não contém o texto da consulta

#### Scenario: Papéis com a ferramenta
- **WHEN** as ferramentas dos papéis são montadas
- **THEN** `researcher` e `curator` têm `buscar_dominio` e `developer` não tem

### Requirement: Avaliação do modelo de embedding
O sistema SHALL oferecer um conjunto rotulado de consultas e um comando de avaliação que calcula `hit@1`, `hit@3` e a
posição média do primeiro acerto por idioma, fora do CI.

#### Scenario: Métricas por idioma
- **GIVEN** um conjunto com 2 consultas em português (1 acerta no topo) e 2 em inglês (nenhuma acerta nos 3 primeiros)
- **WHEN** a avaliação roda com um índice simulado
- **THEN** `hit@1` e `hit@3` do português são 0,5 e os do inglês são 0,0

#### Scenario: Código aceito em qualquer nível
- **GIVEN** uma consulta com dois códigos esperados (uma área e uma subárea dela)
- **WHEN** o resultado traz qualquer um dos dois
- **THEN** a consulta conta como acerto

## MODIFIED Requirements

### Requirement: Texto canônico do rótulo `Dominio`
(Origem: `v17-knowledge-semantic-index` §1, linha `Dominio`: `termo`, `sinonimos`.) O texto vetorizado do `Dominio`
SHALL ser o texto hierárquico definido em "Texto canônico hierárquico do domínio", e o payload SHALL incluir os
campos de "Payload hierárquico no índice".

#### Scenario: Reindexação dos domínios existentes
- **GIVEN** pontos `Dominio` indexados com o texto antigo (só termo e sinônimos)
- **WHEN** a reconciliação roda
- **THEN** os pontos são revetorizados com o texto hierárquico e ganham os campos do payload

### Requirement: Passo semântico de `resolve_domain`
(Origem: `v17-controlled-vocabulary` §2, passo 3.) O passo semântico de `resolve_domain` SHALL usar a busca
hierárquica de domínios, com status `semantico` quando o melhor score atinge `VOCAB_MATCH_THRESHOLD`, devolvendo as
demais como alternativas.

#### Scenario: Correspondência semântica
- **GIVEN** o termo "aprendizado de máquina" e uma subárea de Inteligência Artificial com score acima do limiar
- **WHEN** `resolve_domain` é chamado
- **THEN** o resultado tem status `semantico` e o nó dessa subárea
- **AND** as alternativas trazem outros nós com seus scores

#### Scenario: Abaixo do limiar
- **GIVEN** que o melhor score fica abaixo de `VOCAB_MATCH_THRESHOLD`
- **WHEN** `resolve_domain` é chamado
- **THEN** o status é `candidato_criado` e as três melhores ficam como `alternativas`
