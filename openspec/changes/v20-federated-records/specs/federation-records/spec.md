# Delta: federation-records

## ADDED Requirements

### Requirement: Envelope canônico e endereçado por conteúdo
O sistema SHALL representar todo registro federado num envelope com `versao_formato`, `tipo`,
`autor`, `chave_publica`, `criado_em`, `conteudo`, `refs` e `assinatura`, SHALL assinar o JSON
canônico do envelope sem a assinatura e SHALL identificá-lo por
`cid = "sha256:" + hex(sha256(bytes assinados))` (ADR 013 §2, §6).

#### Scenario: Vetor de teste
- **GIVEN** o envelope de teste versionado em `tests/fixtures/federation/descoberta_v1.json` e a chave de teste
- **WHEN** o registro é canonicalizado e assinado
- **THEN** os bytes canônicos, o `cid` e a assinatura são iguais aos valores esperados do arquivo de fixture

#### Scenario: Ordem das chaves não importa
- **WHEN** dois dicionários com as mesmas chaves em ordens diferentes são canonicalizados
- **THEN** os bytes são idênticos

#### Scenario: Número decimal
- **WHEN** um conteúdo com o número `0.953` (float) é montado
- **THEN** a montagem falha pedindo string decimal

### Requirement: Validação estrita por tipo
O sistema SHALL validar cada registro pelo esquema do seu tipo, SHALL recusar chave
desconhecida, autor incoerente com a chave pública, assinatura inválida, registro acima de
`FEDERATION_RECORD_MAX_BYTES` e data mais de `FEDERATION_CLOCK_SKEW_MINUTES` no futuro.

#### Scenario: Autor falso
- **GIVEN** um registro assinado pela chave A com `autor` derivado da chave B
- **WHEN** o registro é validado
- **THEN** a validação falha com motivo `autor_incoerente`

#### Scenario: Registro grande demais
- **WHEN** um registro com 70000 bytes é validado
- **THEN** a validação falha com motivo `tamanho`

### Requirement: Publicação opt-in e só do que é compartilhável
O sistema SHALL gerar candidatos à publicação somente de projetos marcados como federados e de
nós com `visibilidade="compartilhavel"`, e MUST NOT gerar candidatos de projetos não
federados (ADR 013 §6).

#### Scenario: Projeto não federado
- **GIVEN** um projeto com descobertas `compartilhavel` mas sem `federation project share`
- **WHEN** os candidatos são montados
- **THEN** nenhum candidato é gerado

#### Scenario: Nó privado em projeto federado
- **GIVEN** um projeto federado com uma descoberta `privado` e outra `compartilhavel`
- **WHEN** os candidatos são montados
- **THEN** só a descoberta `compartilhavel` vira candidato

### Requirement: Nenhum dado bruto nem segredo publicado
O sistema MUST NOT incluir dados brutos de pesquisa em registros; datasets SHALL aparecer só
como referência `{nome, sha256, url}` quando marcados `compartilhavel` com URL pública, e como
`{nome, privado: true}` nos demais casos. Candidatos com caminho absoluto, nome de host,
endereço IP, e-mail ou valor de segredo SHALL ser bloqueados com o motivo (ADR 019 §3).

#### Scenario: Dataset privado
- **GIVEN** um experimento que usou `dados.csv` sem marcação `compartilhavel`
- **WHEN** o candidato `experimento` é montado
- **THEN** o dataset aparece como `{"nome": "dados.csv", "privado": true}` sem sha256 nem URL

#### Scenario: Caminho absoluto no texto
- **GIVEN** uma descoberta cujo enunciado contém `/home/pi/outputs/x`
- **WHEN** o candidato é montado
- **THEN** o candidato fica bloqueado com motivo `caminho_absoluto`

### Requirement: Números com origem
O sistema SHALL resolver referências numéricas (`v18.5-numeric-references`) nos textos de
`descoberta`, `oportunidade` e `problema`, e SHALL bloquear o candidato com número literal sem
origem (ADR 019 §2).

#### Scenario: Número literal
- **GIVEN** uma descoberta com o enunciado "acurácia de 95%" sem referência
- **WHEN** o candidato é montado
- **THEN** o candidato fica bloqueado com motivo `numero_sem_origem`

### Requirement: Revisão humana antes de assinar
O sistema SHALL assinar e enfileirar para envio somente candidatos aprovados pelo pesquisador
em `federation outbox review`, exibindo o JSON exato que será assinado, e MUST NOT publicar
automaticamente (ADR 013 §4).

#### Scenario: Candidato não revisado
- **GIVEN** candidatos no estado `candidato`
- **WHEN** o transporte busca registros para enviar
- **THEN** nenhum candidato é entregue

#### Scenario: Aprovação
- **WHEN** o pesquisador aprova um candidato
- **THEN** o registro é assinado, o estado passa a `aprovado` e o nó do grafo recebe `publicado_cid`

### Requirement: Histórico somente-acréscimo
O sistema MUST NOT alterar o envelope de um registro assinado; correções e retratações SHALL
ser registros novos (`correcao` com `substitui`, `retratacao` com `retira`) do mesmo autor.

#### Scenario: Correção por outro autor
- **GIVEN** um registro do autor A
- **WHEN** chega uma `correcao` do autor B que o referencia
- **THEN** a correção é recusada com motivo `autor_diferente`

#### Scenario: Registro imutável
- **WHEN** o código tenta atualizar a coluna `registro` de um registro assinado
- **THEN** a operação é recusada
