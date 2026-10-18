# Delta: benchmark

## ADDED Requirements

### Requirement: Métrica do critério no grafo arquivado
O sistema SHALL incluir no `grafo_projeto.json` de cada repetição os nós `Metrica` ligados por `MEDE` a `Resultado` do projeto e essas arestas, para que o veredito possa ser recalculado do arquivo (ADR 025 §3, etapa 1).

#### Scenario: Resultado com métrica
- **GIVEN** um projeto com um `Resultado` ligado por `MEDE` à `Metrica` `acuracia`
- **WHEN** a repetição é arquivada
- **THEN** `grafo_projeto.json` contém o nó `Metrica` `acuracia` e a aresta `MEDE`
- **AND** os nós e arestas do projeto que já eram arquivados continuam iguais

#### Scenario: Métrica compartilhada entre resultados
- **WHEN** dez `Resultado` medem a mesma `Metrica`
- **THEN** o nó `Metrica` aparece uma única vez
