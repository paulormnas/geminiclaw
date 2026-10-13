# Delta: vocabulary

## ADDED Requirements

### Requirement: Vocabulário inicial de domínios do CNPq
O sistema SHALL carregar os domínios a partir da Tabela de Áreas do Conhecimento do CNPq, com
hierarquia `SUBAREA_DE` e `codigo_cnpq`, como vocabulário inicial aprovado.

#### Scenario: Carga idempotente
- **WHEN** a carga é executada duas vezes
- **THEN** existe um único nó `Dominio` por `codigo_cnpq`

#### Scenario: Hierarquia
- **WHEN** a carga termina
- **THEN** cada termo de nível inferior tem uma aresta `SUBAREA_DE` para o termo pai

### Requirement: Vocabulário extensível além do CNPq
O sistema SHALL permitir termos de domínio fora da tabela do CNPq, criados como candidatos com
`codigo_cnpq` vazio.

#### Scenario: Área emergente
- **WHEN** o termo "computação quântica aplicada à química" não é encontrado
- **THEN** um `Dominio` candidato é criado sem `codigo_cnpq` e pode ser usado imediatamente

### Requirement: Catálogo de métricas
O sistema SHALL manter nós `Metrica` com nome canônico, sinônimos, sentido
(`maior_melhor`/`menor_melhor`), faixa e família.

#### Scenario: Sinônimo resolvido
- **WHEN** um resultado chega com o nome "accuracy"
- **THEN** ele é resolvido para a métrica canônica `acuracia` com sentido `maior_melhor`

#### Scenario: Métrica nova
- **WHEN** um resultado chega com o nome "indice_de_cristalinidade"
- **THEN** uma `Metrica` candidata é criada e listada em `geminiclaw vocab pending`

### Requirement: Ordem de resolução de termos
O sistema SHALL resolver termos livres na ordem: nome exato normalizado, sinônimo,
similaridade semântica acima de `VOCAB_MATCH_THRESHOLD`, e só então criar candidato.

#### Scenario: Variação ortográfica
- **WHEN** "Química Orgânica" e "quimica organica" são resolvidos
- **THEN** ambos retornam o mesmo nó

### Requirement: Decisão do pesquisador sobre candidatos
O sistema SHALL oferecer os comandos `geminiclaw vocab pending|approve|reject|map`, que alteram
o status de termos candidatos sem apagar nós.

#### Scenario: Aprovar
- **WHEN** o pesquisador executa `vocab approve <id>` sobre um candidato
- **THEN** o termo passa a `status=aprovado` e a mudança é auditada com autor `pesquisador`

#### Scenario: Mapear para termo existente
- **WHEN** o pesquisador executa `vocab map <candidato> --para <canonico>`
- **THEN** as arestas do candidato passam a apontar para o canônico
- **AND** o termo do candidato entra nos sinônimos do canônico
- **AND** o candidato fica com `status=rejeitado` e motivo registrado
