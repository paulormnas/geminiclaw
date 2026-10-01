# Delta: input-documents

## ADDED Requirements

### Requirement: Indexação automática dos insumos
O sistema SHALL indexar na coleção de documentos, sem uso de LLM e antes do planejamento, os
arquivos de `input_snapshot/` da sessão, e SHALL tratar cada arquivo uma única vez por
(`projeto_id`, `hash_conteudo`) (ADR 015 §6).

#### Scenario: Primeira sessão do projeto
- **GIVEN** `input_context/` com `artigo.pdf` e `dados.csv`
- **WHEN** a sessão inicia
- **THEN** `artigo.pdf` tem trechos na coleção e `dados.csv` tem um ponto descritor
- **AND** nenhuma chamada de LLM foi feita na indexação

#### Scenario: Mesmo arquivo na sessão seguinte
- **GIVEN** `artigo.pdf` já indexado no projeto, sem mudança de conteúdo nem de metadados do projeto
- **WHEN** outra sessão do mesmo projeto inicia
- **THEN** nenhum trecho é revetorizado e o número de pontos não muda

#### Scenario: Mesmo arquivo em outro projeto
- **GIVEN** `artigo.pdf` indexado no projeto A
- **WHEN** uma sessão do projeto B com o mesmo arquivo inicia
- **THEN** o arquivo é indexado de novo com `projeto_id` de B e IDs diferentes

#### Scenario: Limite de tempo
- **GIVEN** `INPUT_INDEX_MAX_SECONDS=1` e vários arquivos grandes
- **WHEN** a sessão inicia
- **THEN** a sessão segue para o planejamento ao fim do prazo
- **AND** `payload["input_index"]["pendentes"]` lista os arquivos não indexados

### Requirement: Texto enriquecido com metadados
O sistema SHALL gerar o embedding de cada trecho a partir de um cabeçalho fixo com título,
tipo e nome do arquivo, título, objetivo e domínios do projeto e, quando houver, a seção,
seguido do texto do trecho, e SHALL guardar e devolver na busca apenas o texto do trecho
(ADR 015 §6).

#### Scenario: Texto enviado ao modelo de embedding
- **GIVEN** um projeto "Classificação de flores" com domínio "botânica" e o trecho "As pétalas medem…" do arquivo `artigo.pdf`
- **WHEN** o trecho é indexado com o provedor de embedding falso que registra as entradas
- **THEN** o texto registrado começa com `Documento: ` e contém `Projeto: Classificação de flores` e `domínios: botânica`
- **AND** termina com o texto do trecho

#### Scenario: Busca devolve só o trecho
- **WHEN** uma busca encontra esse trecho
- **THEN** o campo de conteúdo do resultado não contém a linha `Projeto:`

#### Scenario: Mudança de metadados do projeto
- **GIVEN** um projeto com documentos indexados
- **WHEN** o objetivo do projeto muda e uma nova sessão inicia
- **THEN** os trechos do projeto são revetorizados com os mesmos IDs
- **AND** o `hash_cabecalho_projeto` registrado muda

### Requirement: Dados de pesquisa só como descritor
O sistema SHALL indexar arquivos `dataset`, imagens e, quando a marcação existir, arquivos
marcados `dado_de_pesquisa` apenas por um descritor sem valores de registros (nome, formato,
colunas com tipo, contagens; dimensões para imagens), e MUST NOT gravar linhas, células ou
texto de OCR desses arquivos na coleção (ADR 019 §3.1).

#### Scenario: CSV
- **GIVEN** `dados.csv` com colunas `id,massa_g` e 150 linhas
- **WHEN** o arquivo é indexado
- **THEN** existe um único ponto com `tipo_ponto="descritor"` cujo texto cita as colunas, os tipos e "150 linhas"
- **AND** nenhum valor da coluna `massa_g` aparece no texto nem no payload

#### Scenario: Imagem
- **WHEN** `foto.png` é indexada
- **THEN** o ponto descritor tem nome, formato e dimensões, sem texto de OCR

### Requirement: Ligação com o grafo e o projeto
O sistema SHALL gravar no payload de cada ponto `insumo_id`, `projeto_id`, `tipo_insumo`,
`tipo_ponto`, `hash_conteudo`, `dominios`, `visibilidade`, `origem` e
`versao_enriquecimento`, SHALL usar IDs determinísticos de documento e de trecho, e SHALL
indexar normalmente quando o grafo estiver indisponível, com `insumo_id` nulo (ADR 015 §3, §6).

#### Scenario: Payload completo
- **WHEN** `artigo.pdf` é indexado num projeto com o grafo disponível
- **THEN** todo ponto tem `insumo_id` igual ao ID do nó `Insumo` do arquivo e `projeto_id` do projeto

#### Scenario: Grafo indisponível
- **GIVEN** o grafo fora do ar
- **WHEN** a sessão indexa os insumos
- **THEN** os pontos são gravados com `insumo_id=null` e um `WARNING` é registrado

### Requirement: Busca restrita ao projeto
O sistema SHALL filtrar por padrão a busca e a lista de documentos pelo projeto da sessão, e
SHALL permitir busca em todos os projetos somente por pedido explícito, informando o projeto
de cada resultado.

#### Scenario: Dois projetos
- **GIVEN** documentos indexados nos projetos A e B
- **WHEN** um agente da sessão do projeto A busca sem parâmetros extras
- **THEN** só trechos do projeto A são devolvidos

#### Scenario: Busca em todos os projetos
- **WHEN** a busca é feita com `todos_os_projetos=true`
- **THEN** trechos dos dois projetos podem ser devolvidos e cada um traz seu `projeto_id`

### Requirement: Falha de vetorização não interrompe a sessão
O sistema SHALL registrar o documento com `vetorizacao="pendente"` quando o Qdrant ou o modelo
de embedding falharem, SHALL seguir com a sessão e SHALL completar a vetorização numa sessão
seguinte ou na reindexação.

#### Scenario: Qdrant fora do ar
- **GIVEN** o Qdrant indisponível no início da sessão
- **WHEN** a sessão indexa os insumos
- **THEN** a sessão segue para o planejamento
- **AND** os documentos ficam com `vetorizacao="pendente"`

#### Scenario: Recuperação
- **GIVEN** documentos `pendente` de uma sessão anterior e o Qdrant disponível
- **WHEN** a próxima sessão do projeto inicia
- **THEN** os trechos são vetorizados e o estado passa a `ok`
