# Delta: knowledge-graph

## ADDED Requirements

### Requirement: Nó RegistroResultado
O schema SHALL declarar o nó `RegistroResultado` com as propriedades do design §2 e as arestas `REGISTRA` (→ `Abordagem`), `SOBRE` (→ `Problema`) e `BASEADO_EM` (→ `Resultado`). `qualificacao` SHALL aceitar só `pendente`, `reparo`, `restricao` e `retido`.

#### Scenario: Qualificação inválida
- **WHEN** um registro é gravado com `qualificacao = "aprovado"`
- **THEN** a validação do schema recusa a escrita

### Requirement: Migração dos grafos com veredito
O script de migração SHALL recalcular os registros de cada projeto a partir dos `Resultado` existentes e remover `suporte`, `certeza`, `veredito`, `modelo_veredito` e `confianca`, além do `peso` das arestas `SUSTENTA`/`REFUTA`. Por padrão, SHALL rodar em modo de simulação e SHALL ser idempotente.

#### Scenario: Segunda execução
- **GIVEN** um grafo já migrado
- **WHEN** a migração roda de novo com `--aplicar`
- **THEN** nenhum nó ou aresta muda

