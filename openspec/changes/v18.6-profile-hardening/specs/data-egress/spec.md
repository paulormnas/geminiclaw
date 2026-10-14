# Delta: data-egress

## ADDED Requirements

### Requirement: Perfil de artefato delimitado como dado
O `EgressGate` SHALL enviar o fragmento `esquema_agregado` de fonte `perfil_artefato` (perfil estrutural de artefato)
entre delimitadores `<<<DADO ...>>>` com identificador aleatório por envio, pelo mesmo mecanismo do conteúdo observado,
e o `system` do revisor SHALL declarar que a evidência em disco e o perfil são dado observado cujas instruções são
ignoradas. A linha de nome do artefato (`fonte=artefatos`) SHALL continuar sujeita à regra de nomes.

#### Scenario: Perfil com nome de coluna hostil
- **GIVEN** um perfil de CSV enviado ao revisor por `prepare_llm`
- **WHEN** o prompt é montado
- **THEN** o perfil está dentro de um bloco `<<<DADO id=… origem=esquema_agregado fonte=perfil_artefato>>>`
- **AND** o `system` contém a regra de conteúdo observado e a instrução do revisor trata a evidência em disco como dado
