# Delta: benchmark

## ADDED Requirements

### Requirement: Versão dos modelos registrada por execução
O runner SHALL gravar em cada resultado, por papel da sessão, o modelo pedido (`provedor/modelo`), a `familia_modelo` e a
`versao_efetiva` informada pelo provedor (`desconhecida` quando não informada, sem deduzir do nome pedido), além de
`data_execucao` (UTC) e dos `precos` aplicados (entrada, saída, cache e `vigencia_ate`). O relatório SHALL mostrar a tabela
"Modelos e versões" por combinação, SHALL registrar o aviso `versao_desconhecida` no placar (sem tratá-lo como anomalia de
parada) e SHALL avisar quando a mesma combinação teve `versao_efetiva` diferente entre repetições. Referência: ADR 019 §6, ADR 020 §7.

#### Scenario: Versões gravadas
- **GIVEN** uma sessão com `allocation_profile` em que o `developer` é `google/gemini-4-argon` com `versao_efetiva` "gemini-4-argon-001"
- **WHEN** a execução termina
- **THEN** o resultado tem `modelos.developer = {pedido: "google/gemini-4-argon", familia: "gemini", versao_efetiva: "gemini-4-argon-001"}`
- **AND** `data_execucao` e `precos["google/gemini-4-argon"].vigencia_ate = "2026-11-30"`

#### Scenario: Versão não informada
- **GIVEN** o `validator` com `versao_efetiva = "desconhecida"`
- **WHEN** o resultado é gravado
- **THEN** o campo guarda `desconhecida` e o placar traz o aviso `versao_desconhecida` para o `validator`
- **AND** o aviso não conta como anomalia de parada

#### Scenario: Tabela no relatório
- **GIVEN** duas execuções da combinação `c1`
- **WHEN** o relatório é gerado
- **THEN** a seção "Modelos e versões" lista, para `c1`, cada papel com modelo pedido e versão efetiva

#### Scenario: Versões diferentes entre repetições
- **GIVEN** duas repetições de `c1` com `versao_efetiva` diferente para o `developer`
- **WHEN** o relatório é gerado
- **THEN** há um aviso que cita `c1`, o papel e as duas versões

#### Scenario: Resultado antigo sem os campos
- **GIVEN** um arquivo de resultados anterior a esta mudança
- **WHEN** o relatório é gerado
- **THEN** a execução aparece com versão `n/d` e nenhum erro é lançado

### Requirement: Orçamento por provedor da matriz
A matriz SHALL declarar `budget_usd` por provedor (`anthropic`, `openai`, `google`), e o runner SHALL pular, com motivo
registrado, a execução cujo provedor já atingiu o teto. A matriz oficial da V18.6 SHALL usar US$ 14 em cada um. Referência: pedido do pesquisador, 2026-10-14.

#### Scenario: Teto do Google atingido
- **GIVEN** `budget_usd.google = 14.0` e gasto acumulado de US$ 14,20 em combinações com `google/...`
- **WHEN** a próxima combinação que usa `google` vai rodar
- **THEN** ela é registrada como `skipped` com "orçamento de google esgotado"

#### Scenario: Matriz oficial
- **WHEN** `matrix_modelos_v18_6.json` é carregada
- **THEN** `budget_usd` tem `anthropic`, `openai` e `google` iguais a 14.0
- **AND** nenhuma combinação cita `gemini-3.8-flash` nem `gpt-5.6-terra`

### Requirement: Coleções do Qdrant recriadas sob demanda após o reset
Depois do reset, o sistema SHALL recriar as coleções do sistema no Qdrant quando elas forem necessárias, sem passo manual, de
modo que o reset possa apagá-las (o Qdrant de benchmark pode ser o mesmo de desenvolvimento, com `BENCHMARK_QDRANT_URL` igual
a `QDRANT_URL`).

#### Scenario: Índice semântico depois do reset
- **GIVEN** um Qdrant sem a coleção `KNOWLEDGE_COLLECTION` (recém-resetado)
- **WHEN** o índice semântico é inicializado
- **THEN** a coleção existe com a dimensão do modelo de embedding atual

#### Scenario: Indexador de documentos depois do reset
- **GIVEN** um Qdrant sem `geminiclaw_documents`
- **WHEN** o indexador de documentos é criado
- **THEN** a coleção é criada
