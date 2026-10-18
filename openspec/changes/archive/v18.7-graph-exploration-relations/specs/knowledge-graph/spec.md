# Delta: knowledge-graph

Os cenários usam o `InMemoryGraphStore`, salvo o da migração (AGE real, marcador `integration`). Nenhum cenário chama provedor LLM.

## ADDED Requirements

### Requirement: Papel do experimento
O schema SHALL aceitar a propriedade opcional `Experimento.papel` com os valores `teste`, `preparacao` e `referencia`, e SHALL recusar qualquer outro valor. A leitura do papel SHALL devolver `teste` para um `Experimento` sem a propriedade, sem reescrever o nó (ADR 021 §2 e §9).

#### Scenario: Papel válido
- **WHEN** um `Experimento` é criado com `papel = "preparacao"`
- **THEN** a escrita é aceita e `experiment_role(node)` devolve `"preparacao"`

#### Scenario: Papel inválido
- **WHEN** um `Experimento` é criado com `papel = "exploracao"`
- **THEN** a escrita é recusada com `InvalidEnumValueError` listando `teste`, `preparacao` e `referencia`

#### Scenario: Experimento antigo sem papel
- **GIVEN** um `Experimento` gravado sem `papel`
- **WHEN** `experiment_role(node)` é chamado
- **THEN** devolve `"teste"`
- **AND** o nó continua sem a propriedade `papel`

### Requirement: Hipótese de origem sistema com chave e referência fixadas
O schema SHALL aceitar `Hipotese.origem = "sistema"`. Uma `Hipotese` com essa origem MUST ter, na criação, `chave_estruturada` no formato `"<problema_id>|<abordagem_id>|<metrica_id>"` e `referencia_fixada` com `valor` (número finito ou `null`), `origem_referencia` (`referencia_medida`, `criterio_problema` ou `indisponivel`), `metrica_id` e `fixada_em`. Cada um dos três componentes de `chave_estruturada` MUST seguir `^[A-Za-z0-9._-]{1,128}$` (identificadores conferidos no grafo, nunca texto de LLM), e a escrita com componente fora desse padrão MUST ser recusada. `chave_estruturada` e `referencia_fixada` MUST ser imutáveis depois da criação (ADR 021 §3.3 e §3.4; parecer de segurança, item b).

#### Scenario: Hipótese do sistema completa
- **WHEN** uma `Hipotese` é criada com `origem = "sistema"`, `chave_estruturada = "prb_1|abd_2|met_3"` e `referencia_fixada = {"valor": 0.62, "origem_referencia": "referencia_medida", "metrica_id": "met_3", "resultado_id": "res_9", "fixada_em": "2026-10-20T12:00:00+00:00"}`
- **THEN** a escrita é aceita
- **AND** `find_nodes("Hipotese", {"chave_estruturada": "prb_1|abd_2|met_3"})` devolve esse nó

#### Scenario: Hipótese do sistema sem chave
- **WHEN** uma `Hipotese` com `origem = "sistema"` é criada sem `chave_estruturada`
- **THEN** a escrita é recusada indicando o campo `chave_estruturada`

#### Scenario: Chave com componente inválido
- **WHEN** uma `Hipotese` com `origem = "sistema"` é criada com `chave_estruturada = "prb_1|abd 2; MATCH (n)|met_3"`
- **THEN** a escrita é recusada indicando `chave_estruturada`

#### Scenario: Referência mal formada
- **WHEN** uma `Hipotese` com `origem = "sistema"` é criada com `referencia_fixada = {"valor": "alto", "origem_referencia": "referencia_medida", "metrica_id": "met_3", "fixada_em": "2026-10-20T12:00:00+00:00"}`
- **THEN** a escrita é recusada indicando `referencia_fixada.valor`

#### Scenario: Referência não muda
- **GIVEN** uma hipótese do sistema com `referencia_fixada.valor = 0.62`
- **WHEN** `update_node` tenta gravar `referencia_fixada` com `valor = 0.70`
- **THEN** a alteração é recusada com `ImmutableFieldError`

#### Scenario: Chave não pode ser acrescentada depois
- **GIVEN** uma `Hipotese` com `origem = "researcher"` sem `chave_estruturada`
- **WHEN** `update_node` tenta gravar `chave_estruturada`
- **THEN** a alteração é recusada com `ImmutableFieldError`

### Requirement: Autor do abandono
O schema SHALL aceitar as propriedades opcionais `Hipotese.abandonada_por` (`pesquisador`, `sistema`, `agente`) e `Hipotese.motivo_abandono`. Somente uma escrita com `Actor` `pesquisador` MUST gravar `abandonada_por = "pesquisador"`, trocar esse valor ou mudar o `status` de uma hipótese abandonada pelo pesquisador. O abandono pelo Researcher (`agente`, decisão de não explorar um caminho) MUST NOT bloquear novos testes; só `pesquisador` bloqueia, e `sistema` SHALL ser usado apenas em retiradas por regra determinística do orquestrador. A leitura do autor de uma hipótese `abandonada` sem a propriedade (nó antigo) SHALL devolver `pesquisador` somente quando a trilha de auditoria do nó tiver uma nota do `Actor` pesquisador com `decisao = "rejeitada"`, e `agente` em caso contrário, sem reescrever o nó (decisão do pesquisador, 2026-10-15; ADR 021 §3.5, §6 e §9).

#### Scenario: Orquestrador não grava abandono do pesquisador
- **WHEN** o `Actor` `orquestrador` atualiza uma hipótese com `status = "abandonada"` e `abandonada_por = "pesquisador"`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Orquestrador não reabre hipótese abandonada pelo pesquisador
- **GIVEN** uma hipótese com `status = "abandonada"` e `abandonada_por = "pesquisador"`
- **WHEN** o `Actor` `orquestrador` atualiza `status` para `em_teste`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Abandono pelo sistema
- **WHEN** o `Actor` `orquestrador` atualiza uma hipótese do sistema com `status = "abandonada"`, `abandonada_por = "sistema"` e `motivo_abandono = "subtarefa_retirada"`
- **THEN** a escrita é aceita
- **AND** um registro em `knowledge_audit` guarda a mudança

#### Scenario: Hipótese abandonada antiga com rejeição do pesquisador
- **GIVEN** uma hipótese `abandonada` sem `abandonada_por` e uma nota de auditoria do `Actor` pesquisador com `decisao = "rejeitada"`
- **WHEN** `abandoned_by(node, audit_history)` é chamado
- **THEN** devolve `"pesquisador"`
- **AND** o nó continua sem a propriedade `abandonada_por`

#### Scenario: Hipótese abandonada antiga sem nota de rejeição
- **GIVEN** uma hipótese `abandonada` sem `abandonada_por` e sem nota de rejeição do pesquisador na trilha de auditoria (alternativa descartada pelo Researcher)
- **WHEN** `abandoned_by(node, audit_history)` é chamado
- **THEN** devolve `"agente"`
- **AND** o nó continua sem a propriedade `abandonada_por`

#### Scenario: Abandono pelo agente não bloqueia
- **GIVEN** uma hipótese com `status = "abandonada"` e `abandonada_por = "agente"`
- **WHEN** o `Actor` `orquestrador` atualiza `status` para `proposta`
- **THEN** a escrita é aceita

### Requirement: Autoridade sobre o abandono em todos os caminhos de escrita
A regra do requisito "Autor do abandono" SHALL ser aplicada na validação do grafo e, por isso, em todos os caminhos que escrevem `Hipotese.status` ou `Hipotese.abandonada_por`: `KnowledgeService`, ingestão (`FactIngestor`), ferramentas de agente do Curator e `geminiclaw graph edit`. O `Actor` de cada escrita MUST ser fixado pelo código do caminho, nunca derivado de saída de LLM; as ferramentas de agente MUST usar sempre um `Actor` de agente (parecer de segurança, item a).

#### Scenario: Ferramenta do Curator
- **GIVEN** uma hipótese com `status = "abandonada"` e `abandonada_por = "pesquisador"`
- **WHEN** uma ferramenta de agente do Curator tenta mudar `status` para `proposta`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Ingestão
- **GIVEN** a mesma hipótese
- **WHEN** a ingestão de uma subtarefa grava `status = "em_teste"` nela
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: KnowledgeService
- **WHEN** o `KnowledgeService` grava `abandonada_por = "pesquisador"` numa hipótese com o `Actor` orquestrador
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Ator declarado pelo LLM é ignorado
- **WHEN** a saída de um agente traz `"actor": "pesquisador"` numa proposta de alteração de hipótese aplicada por ferramenta de agente
- **THEN** a escrita usa o `Actor` de agente e é recusada se gravar `abandonada_por = "pesquisador"`

#### Scenario: Edição confirmada pelo pesquisador
- **GIVEN** a mesma hipótese
- **WHEN** `geminiclaw graph edit` aplica `update_node` com `status = "proposta"`, confirmado no terminal com `Actor` pesquisador
- **THEN** a escrita é aceita e a trilha de auditoria registra o pesquisador

### Requirement: Relação PREPARA
O schema SHALL permitir `Experimento-PREPARA->Hipotese` e `Experimento-PREPARA->Problema`, e SHALL recusar `PREPARA` partindo de outro rótulo ou chegando a outro rótulo (ADR 021 §2 e §3.1).

#### Scenario: Preparação de hipótese
- **WHEN** a aresta `Experimento-PREPARA->Hipotese` é criada com `origem = "derivado"`
- **THEN** a escrita é aceita

#### Scenario: Preparação sem hipótese
- **WHEN** a aresta `Experimento-PREPARA->Problema` é criada
- **THEN** a escrita é aceita

#### Scenario: Origem errada
- **WHEN** a aresta `Resultado-PREPARA->Hipotese` é criada
- **THEN** a escrita é recusada, pois `PREPARA` só parte de `Experimento`

### Requirement: Relação REFERENCIA_DE
O schema SHALL permitir `Resultado-REFERENCIA_DE->Problema` e SHALL recusar qualquer outro par. A aresta MUST NOT ser lida como tentativa no cálculo do veredito (ADR 021 §3.2).

#### Scenario: Referência do problema
- **WHEN** a aresta `Resultado-REFERENCIA_DE->Problema` é criada com `origem = "afirmado"`
- **THEN** a escrita é aceita

#### Scenario: Destino errado
- **WHEN** a aresta `Resultado-REFERENCIA_DE->Hipotese` é criada
- **THEN** a escrita é recusada

#### Scenario: Referência não entra no veredito
- **GIVEN** uma hipótese com um `Resultado` validado ligado por `TESTA`/`PRODUZIU`/`MEDE` e outro `Resultado` validado da mesma métrica ligado só por `REFERENCIA_DE` ao `Problema`
- **WHEN** `collect_attempts` é chamado para a hipótese
- **THEN** devolve uma tentativa, a do `Resultado` ligado por `TESTA`

### Requirement: Hipótese derivada de hipótese
O schema SHALL aceitar `Hipotese-DERIVADA_DE->Hipotese`, além dos destinos já permitidos, e MUST recusar a aresta de uma hipótese para ela mesma (ADR 021 §4.2).

#### Scenario: Refinamento
- **WHEN** a aresta `Hipotese(h2)-DERIVADA_DE->Hipotese(h1)` é criada
- **THEN** a escrita é aceita

#### Scenario: Laço
- **WHEN** a aresta `Hipotese(h1)-DERIVADA_DE->Hipotese(h1)` é criada
- **THEN** a escrita é recusada

### Requirement: Rótulos novos pela migração idempotente
A migração `scripts/migrate_v17_knowledge.py` SHALL criar os rótulos de aresta `PREPARA` e `REFERENCIA_DE` num grafo que não os tem, e uma segunda execução MUST NOT falhar nem duplicar rótulos. O papel `knowledge_reader` SHALL ler as arestas novas.

#### Scenario: Grafo anterior à V18.7
- **GIVEN** um grafo AGE criado antes desta mudança, sem os rótulos `PREPARA` e `REFERENCIA_DE`
- **WHEN** a migração é aplicada duas vezes
- **THEN** `create_relation_labels` devolve `["PREPARA", "REFERENCIA_DE"]` na primeira execução e `[]` na segunda
- **AND** `read_query("MATCH ()-[r:PREPARA]->() RETURN count(r)", {})` executa sem erro de permissão
- **AND** uma escrita numa aresta `PREPARA` com a conexão do `knowledge_reader` é recusada por permissão (parecer de segurança, item c)
