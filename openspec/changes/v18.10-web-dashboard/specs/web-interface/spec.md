# Delta: web-interface

## ADDED Requirements

### Requirement: Painel do projeto
`GET /api/projects/{id}/dashboard` SHALL devolver as contagens por rótulo e por estado, as sessões e o custo do projeto no formato do design §2, lendo só por `ReadOnlyGraphStore` e transação somente leitura (ADR 027 §6.2, §6.4).

#### Scenario: Contagens por estado com zeros
- **GIVEN** um projeto com 3 hipóteses `validada` e 1 `refutada`
- **WHEN** o painel do projeto é pedido
- **THEN** `contagens.Hipotese.total` é 4, `por_estado.validada` é 3, `por_estado.refutada` é 1 e `por_estado.proposta` é 0

#### Scenario: Isolamento entre projetos
- **GIVEN** os projetos A (2 experimentos) e B (5 experimentos)
- **WHEN** o painel de A é pedido
- **THEN** `contagens.Experimento.total` é 2

#### Scenario: Custo não registrado
- **GIVEN** 3 linhas de `token_usage` das sessões do projeto, uma com `estimated_cost_usd` nulo
- **WHEN** o painel é pedido
- **THEN** `custo.custo_usd` soma só as duas com valor e `custo.sem_custo_registrado` é 1

#### Scenario: Rótulos do esquema
- **GIVEN** um rótulo novo acrescentado ao esquema de teste
- **WHEN** o painel é pedido
- **THEN** `contagens` traz o rótulo novo com total 0, sem mudança no código do painel

#### Scenario: Rótulo ausente no banco
- **GIVEN** um grafo sem nenhum `RegistroResultado`
- **WHEN** o painel é pedido
- **THEN** `contagens.RegistroResultado.total` é 0 e a resposta é 200

#### Scenario: Escrita impossível
- **GIVEN** a rota do painel
- **WHEN** o código da consulta tenta `create_node`
- **THEN** levanta `ReadOnlyViolation`, e o teste estático confirma que os módulos do painel não importam a fábrica de escrita

#### Scenario: Projeto malformado
- **WHEN** `GET /api/projects/../x/dashboard` ou um id fora do formato
- **THEN** a resposta é 400 ou 404, sem consulta ao banco com o valor bruto

### Requirement: Painel global
`GET /api/dashboard` SHALL somar os blocos de todos os projetos e listar cada projeto com hipóteses, experimentos, resultados e última atividade.

#### Scenario: Soma
- **GIVEN** os projetos A (2 experimentos) e B (5)
- **WHEN** o painel global é pedido
- **THEN** `contagens.Experimento.total` é 7 e `projetos` tem duas linhas

### Requirement: Cache curto do painel
A resposta SHALL ser reaproveitada por `WEB_DASHBOARD_CACHE_SECONDS` (padrão 15) e `?atualizar=1` MUST ignorar o cache.

#### Scenario: Cache e atualização
- **GIVEN** relógio simulado e um painel pedido em t=0
- **WHEN** um experimento novo entra e o painel é pedido em t=10 e depois com `?atualizar=1`
- **THEN** a resposta em t=10 é a antiga e a com `atualizar=1` traz a contagem nova

### Requirement: Página do painel
O frontend SHALL mostrar cartões de contagem, barras por estado com o valor escrito e tabela equivalente para leitor de tela, e a tabela de sessões recentes.

#### Scenario: Renderização
- **GIVEN** MSW com o painel do design §2
- **WHEN** `/p/X/painel` abre
- **THEN** o cartão "Hipóteses" mostra 12, a barra "validada" tem o texto "4" e existe uma tabela acessível com as mesmas contagens

#### Scenario: Custo sem registro
- **GIVEN** `sem_custo_registrado: 2`
- **THEN** a página mostra "sem custo registrado em 2 chamadas"

#### Scenario: Texto com marcação
- **GIVEN** um título de sessão `<img src=x onerror=alert(1)>`
- **THEN** o texto aparece literalmente e nenhum elemento `img` é criado
