# Delta: operation-metrics

Testes sem chamada paga: telemetria simulada (`get_events`, `token_usage`) e grafo em memória com nós e arestas gravados pelo teste.

## MODIFIED Requirements

### Requirement: Métricas de operação registradas por sessão
O sistema SHALL agregar, para cada sessão, as métricas de egresso, proveniência, verificação, custo e recursos, intervenções humanas (ADR 019 §8) e exploração (ADR 021 §8.4; ADR 022 §6.3, §7), e gravá-las em `agent_sessions.payload["operation_metrics"]` e em `session_metadata.json`, com `versao = 2`. Leitores SHALL aceitar `versao = 1` sem o grupo `exploracao`.

#### Scenario: Fechamento grava as métricas
- **GIVEN** uma sessão com chamadas LLM, execuções no sandbox e uma resposta a `ask_researcher`
- **WHEN** a sessão é fechada por qualquer motivo
- **THEN** `payload["operation_metrics"]` contém os grupos `egresso`, `proveniencia`, `verificacao`, `custo_recursos`, `intervencoes_humanas` e `exploracao`, com `versao=2` e `parcial=false`
- **AND** `session_metadata.json` contém a mesma estrutura

#### Scenario: Payload antigo
- **GIVEN** `operation_metrics` com `versao = 1` e sem `exploracao`
- **WHEN** a seção do relatório é renderizada
- **THEN** a linha "Exploração" mostra `n/d` e nenhuma exceção é lançada

### Requirement: Motivos de parada e de reprovação nas métricas de operação
O grupo `verificacao` SHALL registrar `fechada_por_hipoteses_nao_testadas` (booleano) e `hipoteses_sem_tentativa_no_fechamento`, e MUST NOT registrar `reprovacoes_sem_hipotese`, substituído pelos contadores do grupo `exploracao` (ADR 021 §8.1, §8.4). A seção Markdown "Métricas de operação" SHALL descrever o motivo de parada `hipoteses_nao_testadas` com a contagem de hipóteses sem tentativa.

#### Scenario: Contadores
- **GIVEN** um evento `exploration_stop` com `motivo_parada = "hipoteses_nao_testadas"` e um evento `hipoteses_sem_tentativa` com duas hipóteses
- **WHEN** o leitor do grupo lê a sessão
- **THEN** `fechada_por_hipoteses_nao_testadas` é `true`, `hipoteses_sem_tentativa_no_fechamento` é 2 e a chave `reprovacoes_sem_hipotese` não existe

#### Scenario: Seção do relatório
- **GIVEN** `stop_reason = "hipoteses_nao_testadas"`
- **WHEN** a seção é renderizada
- **THEN** o texto contém o motivo e a explicação "hipóteses em teste sem nenhuma tentativa" e não contém `sem_hipotese`

## ADDED Requirements

### Requirement: Contadores de ligação da exploração
O bloco `exploracao.ligacao` SHALL registrar `experimentos_por_papel` e `testes_por_origem` (`pesquisador`, `researcher`, `curator`, `oportunidade`, `sistema`) contados no grafo sobre os `Experimento` executados na sessão (`Experimento` sem `papel` conta como `teste`), `proporcao_testes_sistema`, e, somados dos eventos `hypothesis_cycle` da sessão, `ligacoes_prepara_derivadas`, `hipoteses_sistema_criadas`, `hipoteses_sistema_abandonadas` e `removidas_pelo_replanejamento` (ADR 021 §8.4, §9).

#### Scenario: Contagem por papel e origem
- **GIVEN** uma sessão com 3 `Experimento` `teste` (dois testando hipóteses `origem = "sistema"`, um `origem = "researcher"`), 2 `preparacao`, 1 `referencia` e 1 `Experimento` antigo sem `papel` testando hipótese `origem = "curator"`
- **WHEN** o leitor lê a sessão
- **THEN** `experimentos_por_papel = {"teste": 4, "preparacao": 2, "referencia": 1}`, `testes_por_origem.sistema = 2`, `testes_por_origem.curator = 1` e `proporcao_testes_sistema = 0.5`

#### Scenario: Soma dos ciclos
- **GIVEN** dois eventos `hypothesis_cycle` com `ligacoes_prepara` 3 e 2 e `hipoteses_sistema_abandonadas` 0 e 1
- **WHEN** o leitor lê a sessão
- **THEN** `ligacoes_prepara_derivadas = 5` e `hipoteses_sistema_abandonadas = 1`

#### Scenario: Produtor ausente
- **GIVEN** eventos `hypothesis_cycle` sem os campos de `v18.7-hypothesis-linking` e `Experimento` sem `papel`
- **WHEN** o leitor lê a sessão
- **THEN** `exploracao.ligacao.estado` é `indisponivel` com `produtor = "v18.7-hypothesis-linking"` e nenhum contador numérico

#### Scenario: Sem testes
- **GIVEN** uma sessão sem `Experimento` `teste`
- **WHEN** o leitor lê a sessão
- **THEN** `proporcao_testes_sistema` é `null`

### Requirement: Contadores da parada e das restrições
O bloco `exploracao.parada` SHALL registrar, a partir dos eventos de `v18.7-exploration-limits`, os ciclos, as intervenções por estagnação, se a saturação foi avaliada, se o objetivo foi atingido e o desfecho, as retiradas por restrição por critério (`abordagem`, `similaridade`) e a lista das retiradas por similaridade (`hipotese_id`, `restricao_id`, `similaridade`), limitada a `OPERATION_METRICS_LIST_MAX_ITEMS` (padrão 50) com a contagem das omitidas (ADR 021 §5.5). Sem os eventos do produtor, o bloco SHALL ficar `indisponivel` com `produtor = "v18.7-exploration-limits"`.

#### Scenario: Retiradas por similaridade listadas
- **GIVEN** `OPERATION_METRICS_LIST_MAX_ITEMS=2` e três eventos `restricao_retirada` com `criterio = "similaridade"` e um com `criterio = "abordagem"`
- **WHEN** o leitor lê a sessão
- **THEN** `retiradas_restricao = {"abordagem": 1, "similaridade": 3}`, a lista tem 2 itens e `retiradas_restricao_similaridade_omitidas = 1`

#### Scenario: Seção lista as retiradas
- **GIVEN** o bloco `parada` com uma retirada por similaridade 0.86
- **WHEN** a seção "Métricas de operação" é renderizada
- **THEN** a linha "Exploração" cita a restrição, a hipótese e 0.86

### Requirement: Hash e tokens do contrato por tentativa
O sistema SHALL emitir, no início de cada tentativa de subtarefa do Developer, o evento `subtask_attempt` com `attempt`, `contrato_sha256`, `contrato_chars`, `contrato_tokens_estimados` (estimativa de `estimate_tokens` sobre o bloco renderizado), `tarefa_original_truncada`, `recorte_sha256` (de `AgentContext.recorte_sha256`, `null` sem `v18.7-agent-system-prompts`) e `limiar_mascarado` (preenchido por `v18.7-subtask-contract`, `false` sem ela), uma vez por tentativa e nunca por volta do laço de ferramentas; SHALL registrar `contrato_sha256` no evento `subtask_review`; e, quando os dois hashes do mesmo `(task_name, attempt)` diferem, SHALL emitir `contrato_divergente` e MUST NOT reprovar a subtarefa por isso (ADR 022 §6.3, §7). O bloco `exploracao.contrato` SHALL agregar tentativas, tokens estimados (total e médio), `fracao_entrada` (sobre os `prompt_tokens` dos papéis developer e validator), divergências, tentativas sem hash e truncamentos. Os eventos MUST NOT conter o texto do contrato.

#### Scenario: Tentativas com o mesmo contrato
- **GIVEN** uma subtarefa com contrato simulado de 4 000 caracteres e duas tentativas
- **WHEN** as tentativas executam e são revisadas
- **THEN** há dois eventos `subtask_attempt` com `attempt` 1 e 2 e `contrato_tokens_estimados` igual a `estimate_tokens` do bloco
- **AND** os eventos `subtask_review` têm os mesmos hashes e nenhum `contrato_divergente` é emitido

#### Scenario: Laço de ferramentas não repete o evento
- **GIVEN** uma tentativa em que o Developer simulado faz 5 voltas de ferramenta
- **WHEN** a tentativa termina
- **THEN** existe um único `subtask_attempt` para essa tentativa

#### Scenario: Hash divergente
- **GIVEN** `subtask_attempt` com hash `aaa…` e um `ReviewResult.contract_sha256` `bbb…` na mesma tentativa, e a revisão aprovada
- **WHEN** a revisão é registrada
- **THEN** o evento `contrato_divergente` traz os dois hashes, a subtarefa continua aprovada e `exploracao.contrato.divergencias = 1`

#### Scenario: Fração da entrada
- **GIVEN** 14 tentativas com 23 100 tokens estimados de contrato e 325 000 `prompt_tokens` dos papéis developer e validator na sessão
- **WHEN** o leitor lê a sessão
- **THEN** `tokens_estimados_total = 23100`, `tokens_estimados_medio = 1650` e `fracao_entrada = 0.071`

#### Scenario: Subtarefa sem contrato
- **GIVEN** uma subtarefa do Researcher sem contrato
- **WHEN** a tentativa começa
- **THEN** `subtask_attempt` tem `contrato_sha256 = null` e `tentativas_sem_hash` aumenta em 1

#### Scenario: Hash do recorte na tentativa
- **GIVEN** uma tentativa cujo `AgentContext.recorte_sha256` é `ccc…`, e outra sessão sem regimento (`recorte_sha256` ausente)
- **WHEN** as tentativas começam
- **THEN** o primeiro `subtask_attempt` tem `recorte_sha256 = "ccc…"` e o segundo tem `recorte_sha256 = null`, sem erro

#### Scenario: Evento sem texto
- **WHEN** um `subtask_attempt` é gravado
- **THEN** o payload só tem as chaves `task_name`, `attempt`, `contrato_sha256`, `contrato_chars`, `contrato_tokens_estimados`, `tarefa_original_truncada` e `recorte_sha256`
