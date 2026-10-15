# Delta: researcher-consult

O requisito "Decisões reservadas ao pesquisador" e a lista `DECISOES_RESERVADAS`, inclusive a entrada `restringir_direcao`, são modificados por `v18.7-persistent-human-gate`, que é a dona do catálogo do gate e é mergeada antes desta mudança. Esta mudança acrescenta só o efeito da decisão `restringir_direcao` (ADR 021 §5.5).

## ADDED Requirements

### Requirement: Restrição de direção só por decisão do pesquisador
Uma restrição de direção (nó `Restricao`, spec `knowledge-graph`) SHALL ser criada só pela ação do pesquisador no processo do terminal: o comando `geminiclaw project restrict` ou a resposta `restringir` a um pedido `restringir_direcao` do gate persistente. Um pedido de agente por `ask_researcher` com `decisao_reservada="restringir_direcao"` SHALL seguir a regra das decisões reservadas (consultor não chamado, interação `pendente_pesquisador`, pedido no gate) e MUST NOT criar `Restricao` enquanto o pesquisador não responder (ADR 021 §5.5).

#### Scenario: Restrição de direção pedida por agente
- **GIVEN** uma sessão `auto`
- **WHEN** um agente chama `ask_researcher` com `decisao_reservada="restringir_direcao"` e a pergunta "encerrar a linha que usa o reagente X?"
- **THEN** o consultor não é chamado, a interação tem `respondido_por="pendente_pesquisador"`, existe um pedido `restringir_direcao` pendente e nenhum nó `Restricao` é criado

#### Scenario: Resposta do pesquisador cria a restrição
- **GIVEN** um pedido `restringir_direcao` com `motivo="restricao_duvidosa"` para a subtarefa `t3`
- **WHEN** o terminal responde `restringir`
- **THEN** a sessão cria um nó `Restricao` com `decidida_por="pesquisador"` e `pedido_id` igual ao id do pedido, ligado por `RESTRINGE` ao `Problema`

#### Scenario: Liberar não cria restrição
- **GIVEN** o mesmo pedido
- **WHEN** o terminal responde `liberar`
- **THEN** nenhum nó `Restricao` é criado e `t3` pode voltar no próximo plano
