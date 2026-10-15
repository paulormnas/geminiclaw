# Delta: hypothesis-loop

## ADDED Requirements

### Requirement: Aprovação de hipóteses no assisted pelo gate persistente
No modo `assisted`, cada hipótese proposta por agente ou derivada de oportunidade que aguarda aprovação SHALL virar um pedido `aprovar_hipotese` no gate persistente, com o enunciado e a justificativa sanitizados (até `GATE_QUESTION_MAX_CHARS`); a resposta do terminal (`aprovar`, `rejeitar` com motivo, `editar` com novo enunciado) SHALL ser aplicada pela sessão com o pesquisador como autor; `p` (pular) SHALL deixar o pedido pendente. Nenhuma leitura de terminal MUST ocorrer no processo da sessão (ADR 023 §4.1; substitui `terminal_approver`).

#### Scenario: Aprovação pelo terminal
- **GIVEN** uma sessão `assisted` com a hipótese `h1` (`origem="researcher"`) aguardando aprovação
- **WHEN** o terminal responde o pedido com `aprovar`
- **THEN** no ciclo seguinte `h1` é executada e a métrica `intervencoes_humanas` conta 1 aprovação

#### Scenario: Rejeição com motivo
- **WHEN** o terminal responde o pedido de `h1` com `rejeitar` e motivo "fora do escopo"
- **THEN** `h1` fica `abandonada` com motivo "fora do escopo" e não é executada

#### Scenario: Edição
- **WHEN** o terminal responde com `editar` e enunciado "Variante com dados normalizados"
- **THEN** `h1` é aprovada com o enunciado novo e a edição é contada em `intervencoes_humanas`

### Requirement: Interface comum de aprovação
O laço de hipóteses SHALL pedir e conferir aprovação do pesquisador só pela interface `ApprovalPort` (design §2.4): chamada com a lista de `ApprovalItem`, devolve só as decisões já respondidas (item ausente continua pendente), e `previously_approved(hypothesis_id, session_chain)` responde se existe pedido `aprovar_hipotese` desse id autorizado por fonte humana. A implementação de produção (`PersistentGateApprover`) SHALL ler e gravar só `gate_requests`; `previously_approved` MUST NOT consultar a trilha de auditoria do grafo nem outro registro que o processo da sessão possa gravar. Os testes SHALL usar `FakeGate`, que implementa a mesma interface.

#### Scenario: Só decisões respondidas
- **GIVEN** `PersistentGateApprover` e dois itens, `h1` com pedido autorizado (`aprovar`) e `h2` sem resposta
- **WHEN** o laço chama o aprovador
- **THEN** o dicionário devolvido tem só `h1`, com ação `aprovar`, e o pedido de `h1` fica com `consumido_em` preenchido

#### Scenario: Aprovação anterior vem do gate
- **GIVEN** a hipótese `h3` com uma nota de auditoria `decisao="aprovada"` gravada pela sessão no grafo e nenhum pedido `aprovar_hipotese` autorizado para `h3`
- **WHEN** `previously_approved("h3", cadeia)` é chamado
- **THEN** devolve `False`

#### Scenario: FakeGate com a mesma interface
- **WHEN** o teste de contrato roda os cenários acima com `FakeGate` no lugar de `PersistentGateApprover`
- **THEN** os resultados são os mesmos

### Requirement: Decisão ao atingir o objetivo pelo gate persistente
Quando o critério de solução é atingido e a decisão cabe ao pesquisador (hoje, modo `assisted`; com `v18.7-exploration-limits`, política `perguntar`), a sessão SHALL criar o pedido `decidir_objetivo_atingido` com o melhor resultado validado e o valor do alvo, e SHALL fechar com `solucao_encontrada` na resposta `encerrar` ou continuar explorando na resposta `continuar` (ADR 023 §4.1; ADR 021 §5.3; substitui `terminal_solution_confirmer`).

#### Scenario: Encerrar
- **GIVEN** uma sessão `assisted` que atingiu o critério de solução
- **WHEN** o terminal responde `encerrar`
- **THEN** a sessão fecha com `motivo_parada="solucao_encontrada"`

#### Scenario: Continuar
- **WHEN** o terminal responde `continuar`
- **THEN** a sessão segue para o próximo ciclo e o pedido fica consumido

#### Scenario: Sem resposta com terminal ausente
- **GIVEN** o pedido pendente e o terminal ausente
- **WHEN** a sessão `assisted` lê a presença
- **THEN** a sessão fica `suspensa_sem_pesquisador` com o pedido ainda pendente

### Requirement: Pedidos de continuidade e de restrição pelo gate persistente
Os pedidos ao pesquisador em estagnação no `assisted`, saturação, intervenções esgotadas, cobertura saturada, várias hipóteses compatíveis, experimento físico pendente ou planos rejeitados SHALL usar a decisão `decidir_continuidade`, com o subtipo em `motivo` (respostas `continuar`, `orientar` com texto, `parar` e, conforme o `motivo`, `aceitar_conjunto` ou `objetivo_atingido`, restritas às `opcoes` gravadas no pedido), e o caso duvidoso de restrição de direção SHALL usar `restringir_direcao` com `motivo="restricao_duvidosa"` (respostas `restringir` ou `liberar`), ambos pelo gate persistente; a orientação de `decidir_continuidade` SHALL chegar ao Researcher no replanejamento delimitada como dado (ADR 023 §4.1; ADR 021 §5.5 e §5.6). Os pontos que criam esses pedidos são de `v18.7-exploration-limits`.

#### Scenario: Parar por decisão do pesquisador
- **GIVEN** um pedido `decidir_continuidade` com `motivo="saturacao"` criado por uma sessão `semi` em `aguarda_pesquisador`
- **WHEN** o terminal responde `parar`
- **THEN** a sessão é encerrada pelo terminal com `motivo_parada="encerrada_pesquisador"` e relatório, sem criar processo novo

#### Scenario: Orientar
- **GIVEN** um pedido `decidir_continuidade` com `motivo="saturacao"` e `opcoes=["continuar","orientar","parar"]`, criado por uma sessão `semi` que ficou `aguarda_pesquisador`, e respostas gravadas para a continuação que registram o prompt recebido
- **WHEN** o terminal responde `orientar` com "priorize modelos lineares"
- **THEN** a sessão retomada recebe o texto no replanejamento dentro de `<mensagens_do_pesquisador>`

#### Scenario: Resposta fora das opções do pedido
- **GIVEN** um pedido `decidir_continuidade` com `motivo="estagnacao"` e `opcoes=["continuar","orientar","parar"]`
- **WHEN** o terminal tenta responder `aceitar_conjunto`
- **THEN** a resposta é recusada com a lista de opções válidas e o pedido continua `pendente`
