# Delta: web-interface

## ADDED Requirements

### Requirement: Subgrafo do projeto com filtros validados
`GET /api/projects/{id}/graph` SHALL devolver os nós e arestas do projeto por `ReadOnlyGraphStore.project_subgraph`, filtrados por rótulo, estado e domínio, e MUST recusar rótulo fora de `src/knowledge/schema.py` (ADR 027 §6.5; ADR 015 §11).

#### Scenario: Filtro por rótulo e estado
- **GIVEN** um projeto com 3 `Hipotese` (2 `validada`) e 4 `Experimento`
- **WHEN** `?rotulos=Hipotese&estado=validada`
- **THEN** a resposta traz exatamente as 2 hipóteses validadas e `total_nos=2`

#### Scenario: Rótulo inválido
- **WHEN** `?rotulos=Hipotese) DETACH DELETE n //`
- **THEN** a resposta é 400 e nenhuma consulta é feita

#### Scenario: Projeto isolado
- **GIVEN** os projetos A e B
- **WHEN** o grafo de A é pedido
- **THEN** nenhum nó exclusivo de B aparece

### Requirement: Limite de nós sem corte silencioso
Acima de `WEB_GRAPH_MAX_NODES`, a resposta SHALL cortar por vizinhança das hipóteses (design §1), MUST informar `omitidos` por rótulo e um cursor, e a interface MUST oferecer "Carregar mais".

#### Scenario: Limite
- **GIVEN** `WEB_GRAPH_MAX_NODES=5`, as hipóteses H1 (mais recente, 2 resultados) e H2 (5 resultados)
- **WHEN** o grafo é pedido sem filtro
- **THEN** vêm H1 com os 2 resultados dela e H2 com 1, `omitidos={"Resultado":4}` e um cursor; "Carregar mais" traz os 4 restantes sem repetir nós

### Requirement: Detalhe, vizinhos e auditoria
O detalhe SHALL trazer propriedades saneadas e limitadas, vizinhos agrupados por relação com contagem e paginação e, sob pedido, o histórico de auditoria; nó fora do projeto e sem vizinhança direta com ele MUST responder 404.

#### Scenario: Domínio compartilhado
- **GIVEN** o `Dominio` D ligado aos projetos A e B
- **WHEN** o detalhe de D é pedido por A
- **THEN** a resposta é 200 e os vizinhos de D que são de B aparecem só com id, rótulo e título

#### Scenario: Nó de outro projeto
- **GIVEN** uma `Hipotese` só de B
- **WHEN** o detalhe é pedido por A
- **THEN** a resposta é 404

#### Scenario: Propriedade longa
- **GIVEN** `WEB_GRAPH_PROPERTY_MAX_CHARS=10` e uma descrição de 50 caracteres
- **THEN** a descrição vem com 10 caracteres e `truncado` a indica

#### Scenario: Ver completo
- **WHEN** `GET .../properties/descricao`
- **THEN** vem a descrição de 50 caracteres inteira

#### Scenario: Vizinhos paginados por relação
- **GIVEN** um `Dominio` com 450 vizinhos por `NO_DOMINIO`
- **THEN** o detalhe mostra o grupo com contagem 450 e as páginas 1 a 3 trazem 200, 200 e 50

#### Scenario: Escrita impossível
- **WHEN** o código das rotas tenta `update_node`
- **THEN** levanta `ReadOnlyViolation`

### Requirement: Canvas e alternativa acessível
A página SHALL mostrar o subgrafo no Cytoscape.js e uma lista equivalente navegável por teclado, com seleção sincronizada; rótulos de nó MUST ser texto.

#### Scenario: Seleção sincronizada
- **GIVEN** MSW com um subgrafo de 3 nós
- **WHEN** o usuário seleciona o segundo nó na lista por teclado
- **THEN** o detalhe dele abre e o nó correspondente fica selecionado na instância do Cytoscape

#### Scenario: Expandir vizinhos
- **WHEN** o usuário pede "Expandir" num nó
- **THEN** os vizinhos retornados entram no canvas e na lista, sem duplicar nós já presentes

#### Scenario: Movimento reduzido
- **GIVEN** `prefers-reduced-motion: reduce`
- **THEN** o layout é aplicado com `animate: false`

#### Scenario: Título com marcação
- **GIVEN** um nó com título `<b onmouseover=alert(1)>x</b>`
- **THEN** o texto aparece literal na lista e no detalhe, e nenhum elemento `b` é criado
