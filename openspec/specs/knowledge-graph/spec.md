# Especificação: knowledge-graph

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md), [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Grafo de conhecimento no PostgreSQL com Apache AGE
_Origem: [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md)_
O sistema SHALL armazenar o grafo de conhecimento com a extensão Apache AGE no PostgreSQL 16
já existente, sem novo serviço em execução.

#### Scenario: Migração idempotente
- **WHEN** a migração `v17_001` é aplicada duas vezes
- **THEN** a segunda execução não falha e não duplica grafo, rótulos, índices nem papéis

### Requirement: Schema único e declarativo
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL validar toda escrita no grafo contra `src/knowledge/schema.py`, que define os tipos de nó do ADR 015 mais `Restricao` (ADR 021 §5.5), suas propriedades, enumerações e as relações permitidas. A validação SHALL incluir a estrutura de `Problema.criterio_sucesso` por tipo de objetivo (ADR 021 §5.2).

#### Scenario: Rótulo desconhecido
- **WHEN** `create_node("Pessoa", ...)` é chamado
- **THEN** a escrita é recusada com erro de validação

#### Scenario: Tipo de objetivo inválido
- **WHEN** um `Problema` é gravado com `criterio_sucesso = {tipo: "maximo"}`
- **THEN** a escrita é recusada listando `limiar`, `discriminacao`, `cobertura` e `fronteira`

#### Scenario: Campo proibido pelo tipo
- **WHEN** um `Problema` é gravado com `criterio_sucesso = {tipo: "discriminacao", alvo: 0.9, hipoteses_concorrentes: [...]}`
- **THEN** a escrita é recusada citando `alvo`

#### Scenario: Política inválida
- **WHEN** um `Problema` é gravado com `criterio_sucesso.ao_atingir_objetivo = "talvez"`
- **THEN** a escrita é recusada listando `parar`, `perguntar` e `continuar`

#### Scenario: Problema antigo continua válido
- **GIVEN** um `Problema` existente com `criterio_sucesso` sem `tipo`
- **WHEN** outra propriedade dele é atualizada
- **THEN** a escrita é aceita

### Requirement: Proveniência obrigatória
_Origem: [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md)_
O sistema SHALL preencher em todo nó `id`, `criado_em`, `atualizado_em`, `criado_por`,
`projeto_id`, `sessao_id`, `visibilidade` (default `privado`), `origem_no` (default `local`) e
`versao_schema`, derivando `criado_por` do `Actor` da operação.

#### Scenario: Autoria não forjável
- **GIVEN** uma escrita feita pelo `Actor` agente `curator` com o modelo `qwen3:8b`
- **WHEN** as propriedades enviadas incluem `criado_por="pesquisador"`
- **THEN** o nó é gravado com `criado_por="curator/qwen3:8b"`

#### Scenario: Nó de agente sem justificativa
- **WHEN** um agente cria uma `Descoberta` sem `justificativa_criacao`
- **THEN** a escrita é recusada

### Requirement: Nada é apagado
_Origem: [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md)_
O sistema MUST NOT oferecer operação de remoção de nós ou arestas de conhecimento; correções
são mudanças de status ou novos nós, com auditoria.

#### Scenario: Campos imutáveis
- **WHEN** `update_node` tenta alterar `id`, `criado_em`, `criado_por` ou `projeto_id`
- **THEN** a alteração é recusada

#### Scenario: Auditoria de alterações
- **WHEN** o status de uma `Descoberta` muda de `ativa` para `contestada`
- **THEN** um registro em `knowledge_audit` guarda o nó, o autor, a data e a mudança

### Requirement: Escrita sem injeção de consulta
_Origem: [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md)_
O sistema MUST montar consultas de escrita apenas com rótulos e relações da whitelist do schema
e passar todos os valores como parâmetros.

#### Scenario: Valor malicioso
- **WHEN** um nó é criado com `titulo = "x'}) MATCH (n) DETACH DELETE n //"`
- **THEN** o título é gravado literalmente e nenhum outro nó é afetado

### Requirement: Consultas livres somente-leitura
_Origem: [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md)_
O sistema SHALL executar consultas Cypher livres somente com o papel de banco
`knowledge_reader`, em transação somente-leitura e com timeout.

#### Scenario: Tentativa de escrita em consulta livre
- **WHEN** `read_query("CREATE (n:Projeto {titulo: 'x'})", {})` é chamado
- **THEN** a consulta é recusada e o grafo não muda

#### Scenario: Consulta lenta
- **WHEN** uma consulta excede `KNOWLEDGE_READ_TIMEOUT_MS`
- **THEN** ela é cancelada e um erro de timeout é retornado

### Requirement: Identificador do computador
_Origem: [`v17-graph-store`](../../changes/archive/v17-graph-store/proposal.md)_
O sistema SHALL gerar uma vez e persistir `NODE_ID`, registrado em sessões e experimentos.

#### Scenario: NODE_ID estável
- **WHEN** o sistema é reiniciado
- **THEN** o mesmo `NODE_ID` é usado

### Requirement: Papel do experimento
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
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
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
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
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
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
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
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
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
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
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
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
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
O schema SHALL aceitar `Hipotese-DERIVADA_DE->Hipotese`, além dos destinos já permitidos, e MUST recusar a aresta de uma hipótese para ela mesma (ADR 021 §4.2).

#### Scenario: Refinamento
- **WHEN** a aresta `Hipotese(h2)-DERIVADA_DE->Hipotese(h1)` é criada
- **THEN** a escrita é aceita

#### Scenario: Laço
- **WHEN** a aresta `Hipotese(h1)-DERIVADA_DE->Hipotese(h1)` é criada
- **THEN** a escrita é recusada

### Requirement: Rótulos novos pela migração idempotente
_Origem: [`v18.7-graph-exploration-relations`](../../changes/archive/v18.7-graph-exploration-relations/proposal.md)_
A migração `scripts/migrate_v17_knowledge.py` SHALL criar os rótulos de aresta `PREPARA` e `REFERENCIA_DE` num grafo que não os tem, e uma segunda execução MUST NOT falhar nem duplicar rótulos. O papel `knowledge_reader` SHALL ler as arestas novas.

#### Scenario: Grafo anterior à V18.7
- **GIVEN** um grafo AGE criado antes desta mudança, sem os rótulos `PREPARA` e `REFERENCIA_DE`
- **WHEN** a migração é aplicada duas vezes
- **THEN** `create_relation_labels` devolve `["PREPARA", "REFERENCIA_DE"]` na primeira execução e `[]` na segunda
- **AND** `read_query("MATCH ()-[r:PREPARA]->() RETURN count(r)", {})` executa sem erro de permissão
- **AND** uma escrita numa aresta `PREPARA` com a conexão do `knowledge_reader` é recusada por permissão (parecer de segurança, item c)

### Requirement: Campos do pesquisador no objetivo protegidos no grafo
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
A validação do grafo (`src/knowledge/validation.py`, pelo mesmo mecanismo de `HUMAN_ONLY_TRANSITIONS`) SHALL aceitar a gravação ou a alteração de `Problema.criterio_sucesso.ao_atingir_objetivo` e de `criterio_sucesso.definido_por = "pesquisador"` somente pelo `Actor` pesquisador: no processo do terminal (confirmação do `Problema`, `geminiclaw project objective`) ou no processo da sessão depois de `consume_authorized` de um pedido `confirmar_problema` respondido pelo terminal. Escrita desses campos por qualquer outro `Actor`, inclusive o orquestrador e os agentes, MUST ser recusada, e o orquestrador MUST NOT substituir um `criterio_sucesso` com `definido_por = "pesquisador"` (ADR 021 §5.2, §5.3; parecer de segurança, item 1).

#### Scenario: Orquestrador grava a política
- **WHEN** o `Actor` orquestrador atualiza um `Problema` com `criterio_sucesso.ao_atingir_objetivo = "continuar"`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Agente se declara pesquisador
- **WHEN** o `Actor` agente `Researcher` grava `criterio_sucesso` com `definido_por = "pesquisador"`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Orquestrador substitui o objetivo do pesquisador
- **GIVEN** um `Problema` com `criterio_sucesso.definido_por = "pesquisador"`
- **WHEN** o `Actor` orquestrador grava um `criterio_sucesso` aprovado no plano com `definido_por = "agente"`
- **THEN** a escrita é recusada e o critério do pesquisador continua gravado

#### Scenario: Objetivo do agente no auto
- **GIVEN** um `Problema` sem objetivo válido
- **WHEN** o `Actor` orquestrador grava `criterio_sucesso` com `definido_por = "agente"` e sem `ao_atingir_objetivo`
- **THEN** a escrita é aceita

#### Scenario: Pesquisador define a política
- **WHEN** o `Actor` pesquisador executa `geminiclaw project objective p1 --ao-atingir continuar`
- **THEN** a escrita é aceita e a trilha de auditoria registra o pesquisador

### Requirement: Abandono por restrição com autoridade da restrição
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
A retirada de hipótese por restrição de direção SHALL gravar `abandonada_por = "pesquisador"` e `motivo_abandono = "direcao_restrita:<restricao_id>"` com o `Actor` pesquisador derivado da `Restricao` (o ator cita o `restricao_id`). A validação do grafo SHALL aceitar essa escrita só quando a `Restricao` citada existe, tem `decidida_por = "pesquisador"` e `status = "ativa"`, e SHALL recusar a derivação em qualquer outra escrita, de modo que a regra de autoridade de `v18.7-graph-exploration-relations` (design §2.3) continue fechada a outros caminhos (parecer de segurança, item 3).

#### Scenario: Retirada com restrição ativa
- **GIVEN** a `Restricao(r1, status="ativa", decidida_por="pesquisador")`
- **WHEN** a sessão grava `status = "abandonada"`, `abandonada_por = "pesquisador"` e `motivo_abandono = "direcao_restrita:r1"` com o ator derivado de `r1`
- **THEN** a escrita é aceita e a trilha de auditoria registra `r1`

#### Scenario: Restrição revogada não autoriza
- **GIVEN** a `Restricao(r1, status="revogada")`
- **WHEN** a sessão tenta a mesma escrita com o ator derivado de `r1`
- **THEN** a escrita é recusada com `HumanConfirmationRequiredError`

#### Scenario: Restrição inexistente
- **WHEN** a sessão tenta a escrita com o ator derivado de `r_inexistente`
- **THEN** a escrita é recusada

### Requirement: Motivos de parada da exploração longa
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O enum de `Sessao.motivo_parada` SHALL aceitar `limite_custo` e `saturacao`, SHALL manter `limite_ciclos` e `limite_execucoes` para os nós existentes (o código deixa de gravá-los) e SHALL manter `limite_cota_provedor` de `v18.7-benchmark-fixes` (ADR 021, cabeçalho, mudança no ADR 015 §8).

#### Scenario: Novos valores
- **WHEN** um nó `Sessao` é gravado com `motivo_parada = "saturacao"` e outro com `"limite_custo"`
- **THEN** as duas escritas são aceitas

### Requirement: Marco de objetivo atingido
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O `Problema` SHALL aceitar a propriedade `objetivo_atingido`, lista de marcos `{em, sessao_id, tipo, desfecho, resultado_id, hipotese_id, valor}`, acrescentada pelo orquestrador a cada atingimento e nunca sobrescrita (ADR 021 §5.3). Agentes MUST NOT escrevê-la.

#### Scenario: Segundo marco
- **GIVEN** um `Problema` com um marco de uma sessão anterior
- **WHEN** outra sessão atinge o objetivo
- **THEN** a lista tem os dois marcos, na ordem

#### Scenario: Agente tenta escrever
- **WHEN** o ator `Researcher` tenta atualizar `objetivo_atingido`
- **THEN** a escrita é recusada pela barreira de valores permitidos a agentes

### Requirement: Predições das hipóteses concorrentes
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
`Hipotese` SHALL aceitar `concorrente` (booleano) e `predicao` (texto até `HYPOTHESIS_TEXT_MAX_CHARS`), e `Experimento` SHALL aceitar `conferencia_predicoes` (mapa `hipotese_id` → `confirma` | `contraria` | `inconclusiva`) (ADR 021 §5.2). Nós sem essas propriedades SHALL ser lidos como `concorrente = false` e sem conferência.

#### Scenario: Conferência inválida
- **WHEN** um `Experimento` é gravado com `conferencia_predicoes = {"h1": "talvez"}`
- **THEN** a escrita é recusada listando os três valores válidos

### Requirement: Restrição de direção como nó
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O schema SHALL ter o nó `Restricao` (`direcao` obrigatória, `categoria` em `seguranca` | `etica` | `recurso`, `abordagens` lista, `status` em `ativa` | `revogada`, `decidida_por` = `pesquisador`, `decidida_em`, `pedido_id`) e a relação `(Restricao)-[:RESTRINGE]->(Problema|Projeto)`. A validação do grafo (`src/knowledge/validation.py`) SHALL aceitar a criação ou a revogação de `Restricao` só em dois caminhos: pelo `Actor` pesquisador no processo do terminal (comandos `project restrict` e `project unrestrict`, `pedido_id` vazio), ou pelo processo da sessão depois que `PersistentGate.consume_authorized("restringir_direcao", referencia, session_chain)` de `v18.7-persistent-human-gate` devolver um pedido autorizado e consumido, caso em que `pedido_id` MUST ser o id desse pedido. Qualquer outra escrita, inclusive do `Actor` orquestrador sem pedido autorizado e consumido, MUST ser recusada; a revogação SHALL mudar `status` e nunca apagar o nó. O rótulo e a relação SHALL ser criados pela migração idempotente do grafo, a mesma usada por `v18.7-graph-exploration-relations` (ADR 021 §5.5).

#### Scenario: Criação pelo pesquisador
- **WHEN** `geminiclaw project restrict p1 --direcao "uso de reagente perigoso" --categoria seguranca --abordagem sintese_com_reagente_x` é executado
- **THEN** existe `Restricao(status="ativa", decidida_por="pesquisador")` com `RESTRINGE->Projeto(p1)` e a trilha de auditoria registra o pesquisador

#### Scenario: Agente não cria restrição
- **WHEN** o ator `Curator` tenta criar um nó `Restricao`
- **THEN** a escrita é recusada

#### Scenario: Orquestrador sem pedido autorizado é recusado
- **GIVEN** uma sessão `auto` sem pedido `restringir_direcao` autorizado
- **WHEN** o `Actor` orquestrador tenta criar um nó `Restricao` com `decidida_por = "pesquisador"`
- **THEN** a escrita é recusada e nenhum nó `Restricao` existe

#### Scenario: Pedido já consumido não cria segunda restrição
- **GIVEN** um pedido `restringir_direcao` autorizado pelo terminal e já consumido por uma `Restricao`
- **WHEN** o processo da sessão tenta criar outra `Restricao` citando o mesmo `pedido_id`
- **THEN** `consume_authorized` recusa com `ja_consumida` e a escrita não ocorre

#### Scenario: Sessão sem pedido_id
- **GIVEN** um pedido `restringir_direcao` autorizado e consumido
- **WHEN** o processo da sessão grava a `Restricao` sem `pedido_id`
- **THEN** a escrita é recusada citando `pedido_id`

#### Scenario: Revogação não apaga
- **WHEN** `geminiclaw project unrestrict <id>` é executado
- **THEN** o nó continua existindo com `status = "revogada"`

#### Scenario: Migração idempotente
- **WHEN** a migração do grafo é aplicada duas vezes
- **THEN** a segunda execução não falha e o rótulo `Restricao` existe uma vez
