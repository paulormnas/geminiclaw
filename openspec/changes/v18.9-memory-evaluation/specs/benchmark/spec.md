# Delta: benchmark

## ADDED Requirements

### Requirement: Candidatos estruturais sem LLM
O sistema SHALL gerar candidatos dos tipos `transferencia`, `composicao` e `pouco_explorado` a partir de uma vista do grafo até um instante `t`, sem chamada de LLM, com os atributos e a ordenação do design §2.

#### Scenario: Transferência
- **GIVEN** os Problemas P e P' com semelhança 0.8, a abordagem A com registro `atingiu_alvo` em P' e nenhum registro de A em P
- **WHEN** os candidatos de P são gerados
- **THEN** existe um candidato `transferencia` (P, A) com `origem_ids` contendo o registro de P'

#### Scenario: Semelhança abaixo do limiar
- **GIVEN** a semelhança entre P e P' de 0.5 e `CANDIDATE_MIN_SIMILARITY=0.60`
- **WHEN** os candidatos de P são gerados
- **THEN** não há candidato `transferencia` vindo de P'

#### Scenario: Sem futuro
- **GIVEN** um grafo cortado em `t`
- **WHEN** os candidatos são gerados
- **THEN** nenhum nó ou registro com `criado_em > t` influencia a saída

### Requirement: Replay com AUC e linhas de base
O replay SHALL calcular a AUC da ordenação padrão e das linhas de base (aleatória, só semelhança e só grau), com intervalo por bootstrap, e SHALL gravar `replay.json` com o commit, os sha256 dos grafos e as sementes.

#### Scenario: Ordem perfeita
- **GIVEN** um corpus sintético em que os positivos são exatamente os candidatos mais bem ordenados
- **WHEN** o replay roda
- **THEN** a AUC da ordenação padrão é 1.0 e a da aleatória fica entre 0.4 e 0.6

#### Scenario: Corpus sem positivos
- **WHEN** o replay roda sobre grafos sem eventos depois de nenhum corte
- **THEN** o replay termina com erro explícito, sem gravar AUC

### Requirement: Métricas do núcleo com origem declarada
`scripts/memory_eval/metrics.py` SHALL calcular `taxa_sucesso`, `taxa_validas`, `ganho_base` e `falhas_repetidas` por braço, com intervalo de 95% por bootstrap e o n de explorações, a partir de explorações arquivadas.

#### Scenario: Falha repetida
- **GIVEN** uma exploração com as falhas `oom` (abordagem A), `oom` (abordagem A) e `instalacao_pacotes` (ambiente)
- **WHEN** as métricas são calculadas
- **THEN** `falhas_repetidas = 1/3`

### Requirement: Famílias de Problemas relacionados
O gerador SHALL produzir famílias de `k` Problemas que compartilham a abordagem plantada e famílias de controle com abordagens diferentes, com `verdade.json` contendo a `familia` e fora do alcance dos agentes.

#### Scenario: Família reprodutível
- **WHEN** a mesma família é gerada duas vezes com a mesma semente
- **THEN** os sha256 dos dados e da verdade são iguais
