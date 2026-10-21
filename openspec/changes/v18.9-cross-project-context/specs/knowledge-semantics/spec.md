# Delta: knowledge-semantics

## MODIFIED Requirements

### Requirement: Consulta híbrida de experiência relacionada
O sistema SHALL responder "o que funcionou ou falhou em problemas parecidos" buscando Problemas semelhantes pela combinação de texto e `caracteristicas_dados` (design §3) e lendo os `RegistroResultado` deles. O ranking SHALL ser semelhança × (1 + margem) × min(réplicas, 3) × recência. (Antes: atalhos ponderados por confiança do veredito.)

#### Scenario: Experiência de outro projeto
- **GIVEN** um Problema P2 semelhante (0,8) a P1, com registro da abordagem A `atingiu_alvo` e duas réplicas
- **WHEN** `related_experience(P1)` é chamado
- **THEN** A aparece com P2 como origem e com os fatos do registro

#### Scenario: Semelhança pelos dados
- **GIVEN** P1 e P2 com texto de cosseno 0,5 e `caracteristicas_dados` iguais, com `RELATED_TEXT_WEIGHT=0.5`
- **WHEN** a semelhança é calculada
- **THEN** o valor é 0,75

### Requirement: Faixas de similaridade
O sistema SHALL classificar pares de nós como duplicata (≥ 0,90) ou ignorado. Só duplicatas SHALL entrar na fila. A relação entre Problemas SHALL ser calculada sob demanda pela consulta de experiência relacionada. (Antes: a faixa de relacionados também entrava na fila.)

#### Scenario: Relacionado não enfileirado
- **WHEN** dois `Problema`s têm similaridade 0,75
- **THEN** o par não entra na fila

#### Scenario: Duplicata
- **WHEN** duas `Abordagem`s têm similaridade 0,93
- **THEN** o par entra na fila como `duplicata`

## REMOVED Requirements

### Requirement: Oportunidades entre projetos exigem evidência
**Motivo:** a regra por |veredito| deixa de existir. Oportunidades entre projetos passam a vir dos candidatos estruturais (`hypothesis-loop`, "Candidatos estruturais no ciclo").

## ADDED Requirements

### Requirement: Experiência de problemas semelhantes no primeiro plano
O sistema SHALL incluir no prompt do primeiro plano de um projeto, e no de cada ciclo, o bloco `experiencia_de_problemas_semelhantes`, com o modelo do design §2 e até `RELATED_RECORDS_K` Problemas e `RELATED_RECORDS_MAX_CHARS` caracteres. O bloco SHALL ser envolto por `wrap_data`, SHALL excluir registros `retido` e de projetos não visíveis e SHALL trazer a instrução de que a experiência é hipótese a testar.

#### Scenario: Projeto novo com experiência disponível
- **GIVEN** um projeto novo com Problema semelhante (0,8) a um Problema de outro projeto visível, que tem um registro `atingiu_alvo`
- **WHEN** o primeiro plano é pedido ao Researcher
- **THEN** o prompt contém o bloco com o nome da abordagem e o `melhor_valor` desse registro

#### Scenario: Registro retido
- **GIVEN** o único registro do Problema semelhante com `qualificacao = "retido"`
- **WHEN** o bloco é montado
- **THEN** o registro não aparece

#### Scenario: Sem experiência
- **WHEN** não há Problemas semelhantes acima de `CANDIDATE_MIN_SIMILARITY`
- **THEN** o bloco é omitido
