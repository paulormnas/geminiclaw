# Especificação: session-continuity

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md), [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Checkpoint incremental e atômico
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL gravar o avanço da sessão em `checkpoint.json` a cada mudança de plano, início
e fim de subtarefa, abandono de tarefa, checkpoint do Curator e fechamento, de forma atômica.

#### Scenario: Após cada subtarefa
- **WHEN** uma subtarefa termina
- **THEN** o checkpoint reflete seu status, tentativas, artefatos e resumo do resultado

#### Scenario: Queda durante a gravação
- **WHEN** a gravação é interrompida antes de concluir
- **THEN** o checkpoint anterior permanece íntegro e legível

### Requirement: Detecção de paradas inesperadas
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL detectar sessões interrompidas sem fechamento e registrá-las como tal.

#### Scenario: Queda de energia
- **GIVEN** uma sessão `active` sem batimento há mais de `SESSION_STALE_SECONDS`
- **WHEN** o sistema inicia
- **THEN** a sessão é marcada `interrompida`
- **AND** suas subtarefas em andamento são registradas como falhas de causa `infraestrutura`

### Requirement: Retomada a partir do checkpoint
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL retomar uma sessão a partir do seu checkpoint, em uma nova sessão ligada à
anterior, sem recomeçar do zero.

#### Scenario: Retomada após limite
- **GIVEN** uma sessão fechada por `limite_tokens` com 3 subtarefas concluídas e 2 pendentes
- **WHEN** o pesquisador executa `geminiclaw resume --session <id>`
- **THEN** uma nova sessão é criada com `continues_session_id=<id>`, orçamento novo e aresta `CONTINUA`
- **AND** as 3 subtarefas concluídas não são reexecutadas

#### Scenario: Continuar o projeto
- **WHEN** o pesquisador executa `geminiclaw continue --project <p>`
- **THEN** a sessão mais recente do projeto é retomada

#### Scenario: Pesquisa dada como resolvida
- **GIVEN** uma sessão fechada com `solucao_encontrada`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a CLI pede confirmação antes de continuar

### Requirement: Contexto de retomada completo
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL fornecer ao Researcher, na retomada, o estado do plano, as hipóteses abertas
com vereditos, os caminhos sem conclusão, a experiência relacionada do grafo e as
sinalizações pendentes.

#### Scenario: Caminho sem conclusão
- **GIVEN** um caminho registrado como sem conclusão com `proximo_passo_sugerido`
- **WHEN** a sessão é retomada
- **THEN** o contexto do Researcher contém esse caminho e o próximo passo sugerido

### Requirement: Artefatos anteriores legíveis, escrita isolada
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL permitir ler os artefatos das sessões anteriores da cadeia do mesmo projeto e
restringir a escrita à sessão atual.

#### Scenario: Leitura e escrita
- **WHEN** o Developer da sessão retomada lê um artefato da sessão anterior e tenta sobrescrevê-lo
- **THEN** a leitura funciona e a escrita na sessão anterior é recusada

### Requirement: Consolidação pendente concluída na retomada
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL executar a consolidação do Curator que ficou pendente na sessão anterior antes
do novo planejamento.

#### Scenario: Curator pendente
- **GIVEN** um checkpoint com `curator_pendente=true`
- **WHEN** a sessão é retomada
- **THEN** o Curator executa o fechamento da sessão anterior antes do replanejamento

### Requirement: Retomada idempotente e sem bifurcação
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL permitir que apenas uma retomada simultânea continue uma mesma sessão.

#### Scenario: Retomadas simultâneas
- **WHEN** duas retomadas da mesma sessão de origem começam ao mesmo tempo
- **THEN** só uma cria e executa a sessão nova
- **AND** a outra é recusada e sua sessão é fechada sem executar nada

#### Scenario: Continuação que falhou
- **GIVEN** a sessão que continuava a origem falhou sem checkpoint válido
- **WHEN** o pesquisador retoma a origem
- **THEN** a retomada é aceita e substitui a reivindicação anterior

### Requirement: Checkpoint e artefatos como dado não confiável
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL validar o checkpoint lido do disco, inclusive cada caminho de artefato, e entregar ao Researcher o
conteúdo restaurado apenas como dado.

#### Scenario: Artefato hostil
- **GIVEN** um checkpoint com artefato `../../etc/passwd` ou nome com quebra de linha
- **WHEN** o checkpoint é lido
- **THEN** a leitura é recusada e nada chega ao prompt

### Requirement: Batimento independente do laço de eventos
_Origem: [`v18-research-continuity`](../../changes/archive/v18-research-continuity/proposal.md)_
O sistema SHALL manter o batimento da sessão em thread própria e reafirmar a sessão marcada obsoleta por engano.

#### Scenario: Laço parado
- **WHEN** o laço de eventos fica parado por mais que `SESSION_STALE_SECONDS`
- **THEN** o batimento continua e a sessão não é marcada `interrompida`

### Requirement: Retomada após cota ou gasto esgotado
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
Uma sessão fechada com `motivo_parada="limite_cota_provedor"` SHALL ser retomável sem confirmação, como os demais `limite_*`, e o valor SHALL constar da enumeração `Sessao.motivo_parada` do grafo. A retomada SHALL NOT conferir saldo no provedor; se a cota continuar esgotada, a nova sessão SHALL fechar de novo com o mesmo motivo.

#### Scenario: Retomada aceita
- **GIVEN** um checkpoint e o banco de sessões com `motivo_parada="limite_cota_provedor"`
- **WHEN** a retomabilidade é avaliada
- **THEN** o resultado é `RESUME_OK`

#### Scenario: Nó Sessao com o motivo novo
- **WHEN** um nó `Sessao` é gravado com `motivo_parada="limite_cota_provedor"`
- **THEN** a validação do schema aceita o valor

### Requirement: Retomada conforme os motivos de parada da exploração longa
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
`evaluate_resumability` SHALL tratar `limite_custo` como os demais `limite_*` (retomável sem perguntar), SHALL pedir confirmação para `saturacao`, com a mensagem que cita `saturacao` e explica que a melhora possível ficou abaixo do erro da medida, e SHALL continuar aceitando sem perguntar `limite_ciclos` e `limite_execucoes` de sessões anteriores a esta mudança. `limite_cota_provedor` (`v18.7-benchmark-fixes`) SHALL continuar retomável sem perguntar (ADR 021 §5, "Mudanças OpenSpec exigidas"; `src/continuity.py:64-70`).

#### Scenario: Limite de custo
- **GIVEN** uma sessão fechada com `motivo_parada = "limite_custo"` no banco e no checkpoint
- **WHEN** o pesquisador executa `geminiclaw resume --session <id>`
- **THEN** a avaliação devolve `RESUME_OK` e a nova sessão recebe orçamento novo

#### Scenario: Saturação pede confirmação
- **GIVEN** uma sessão fechada com `motivo_parada = "saturacao"`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a avaliação devolve `RESUME_CONFIRM` com mensagem que contém `saturacao`

#### Scenario: Sessão antiga com teto de ciclos
- **GIVEN** uma sessão fechada antes desta mudança com `motivo_parada = "limite_ciclos"`
- **WHEN** o pesquisador tenta retomá-la
- **THEN** a avaliação devolve `RESUME_OK`

### Requirement: Estado da exploração restaurado na retomada
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O checkpoint SHALL levar `exploracao_estado` (ciclos sem avanço, intervenções feitas, melhor valor e EP, desfecho, janela de novidade, objetivo atingido na sessão e política efetiva), validado como dado não confiável (tipos, faixas e tamanho), e a retomada SHALL restaurá-lo na `ExplorationSession`; valor inválido SHALL ser descartado com aviso, começando do zero, sem recusar a retomada.

#### Scenario: Estado inválido
- **GIVEN** um checkpoint com `exploracao_estado.intervencoes = -4`
- **WHEN** a sessão é retomada
- **THEN** a retomada segue com `intervencoes = 0` e o evento `exploracao_estado_descartado` é registrado
