# Delta: research-data

## ADDED Requirements

### Requirement: Manifesto de marcações de arquivos
O sistema SHALL ler marcações opcionais de `input_context/dados.yaml` (`compartilhavel` ou
`dado_de_pesquisa`, por caminho ou padrão relativo a `input_context/`), SHALL exigir `motivo`
para `compartilhavel`, e SHALL recusar iniciar a sessão, com mensagem acionável, diante de
chave desconhecida, caminho fora de `input_context/` ou marcações conflitantes para o mesmo
arquivo.

#### Scenario: Dataset público
- **GIVEN** `dados.yaml` marcando `publicos/uci.csv` como `compartilhavel` com motivo
- **WHEN** o contexto é carregado
- **THEN** o arquivo tem classe `dado_de_pesquisa` com `compartilhavel=True` e a marcação vem do manifesto

#### Scenario: Caminho fora do diretório
- **WHEN** `dados.yaml` contém `caminho: ../segredos.csv`
- **THEN** a sessão não inicia e o erro cita a entrada

#### Scenario: Marcações conflitantes
- **WHEN** `*.csv` é `compartilhavel` e `medicoes.csv` é `dado_de_pesquisa`
- **THEN** a sessão não inicia e o erro cita os dois padrões

#### Scenario: Compartilhável sem motivo
- **WHEN** uma entrada `compartilhavel` não tem `motivo`
- **THEN** a sessão não inicia

### Requirement: Classificação padrão dos arquivos de entrada
O sistema SHALL classificar como `dado_de_pesquisa`, na ausência de marcação, datasets
tabulares, planilhas, JSON/JSONL, imagens e arquivos sem processador, e como `documento` os
textos e documentos (`.txt .md .rst .pdf .docx .pptx`).

#### Scenario: PDF marcado como dado
- **GIVEN** `cadernos/lab.pdf` marcado `dado_de_pesquisa`
- **WHEN** o contexto é carregado
- **THEN** o texto do PDF vira trecho `dado_de_pesquisa` e o trecho seguro traz só título, formato, páginas e tamanho

### Requirement: Resumo seguro de datasets
O sistema SHALL produzir para cada dataset um trecho `esquema_agregado` com esquema, unidades
reconhecidas no cabeçalho, metadados, descritores de formato sem valores e estatísticas por
coluna segundo `LOCALITY_MIN_GROUP_SIZE` (k): abaixo de k, só contagem e tipo; a partir de k,
média, desvio e faixa arredondada para numéricas, número de distintos para categóricas e anos
extremos para datas. Mínimo, máximo e quantis MUST NOT aparecer exatos nesse trecho.

#### Scenario: Descritores de formato
- **GIVEN** um CSV em latin-1 com separador `;` e decimal `,`
- **WHEN** o resumo seguro é gerado
- **THEN** ele informa codificação latin-1, separador `;` e decimal `,`
- **AND** não contém nenhum valor de célula

#### Scenario: Coluna abaixo de k
- **GIVEN** uma coluna numérica com menos de k valores não nulos
- **WHEN** o resumo seguro é gerado
- **THEN** a coluna traz só `n` e tipo

#### Scenario: Extremos em faixa
- **GIVEN** uma coluna com `n ≥ k`, mínimo 12.3 e máximo 38.9
- **WHEN** o resumo seguro é gerado
- **THEN** a coluna traz `faixa ≈ [10, 40]` e não contém `12.3` nem `38.9`

#### Scenario: Categórica
- **GIVEN** uma coluna de texto com `n ≥ k` e 6 rótulos distintos
- **WHEN** o resumo seguro é gerado
- **THEN** a coluna traz `6 valores distintos` e nenhum rótulo

### Requirement: Amostras só para destinos permitidos
O sistema SHALL colocar amostras de linhas, registros de JSON e estatísticas exatas num trecho
`dado_de_pesquisa`, separado do trecho seguro, para que só destinos com `aceita_dados_brutos`
ou arquivos compartilháveis os recebam.

#### Scenario: Planejador de terceiro
- **GIVEN** o planejador em modelo sem `aceita_dados_brutos` e um dataset não compartilhável
- **WHEN** o plano inicial é enviado
- **THEN** o prompt contém o resumo seguro e o aviso de retenção, e não contém as linhas de amostra

#### Scenario: Planejador com dados brutos
- **GIVEN** o planejador em modelo `no_no`
- **WHEN** o plano inicial é enviado
- **THEN** o prompt contém o resumo seguro e as 5 linhas de amostra

#### Scenario: Dataset compartilhável
- **GIVEN** um dataset marcado `compartilhavel` e o planejador em modelo `third_party`
- **WHEN** o plano inicial é enviado
- **THEN** o prompt contém as linhas de amostra

### Requirement: Visão pela camada de saída
O sistema SHALL descrever imagens apenas pelo modelo de `VISION_MODEL` (entrada do catálogo),
pela camada de provedores e após `EgressGate.authorize_vision`; quando a visão for recusada,
SHALL usar OCR local e registrar a recusa no bundle, sem interromper a sessão. O texto obtido de
imagem ou PDF escaneado que seja dado de pesquisa SHALL ser trecho `dado_de_pesquisa`.

#### Scenario: Imagem de pesquisa com visão de terceiro
- **GIVEN** `VISION_MODEL=google/gemini-3.8-flash` e uma imagem não compartilhável
- **WHEN** o contexto é carregado
- **THEN** nenhuma imagem é enviada ao Google, o OCR local é usado e `extraction_errors` registra a recusa

#### Scenario: Visão no nó
- **GIVEN** `VISION_MODEL` apontando para um modelo Ollama `no_no`
- **WHEN** uma imagem é carregada
- **THEN** a descrição é obtida pelo Ollama e registrada em `egress_log` com `canal=visao` e `localidade=no_no`

#### Scenario: Alias obsoleto
- **WHEN** `OCR_PROVIDER=gemini` está configurado e `VISION_MODEL` não
- **THEN** o sistema usa `google/gemini-3.8-flash` como `VISION_MODEL` e emite `WARNING` de obsolescência

### Requirement: Marcações registradas na sessão e no relatório
O sistema SHALL gravar em `payload["research_data_markings"]` a classe efetiva, a marcação, o
motivo, o hash e a origem (manifesto ou padrão) de cada arquivo de `input_context/`, SHALL
copiar `dados.yaml` para `input_snapshot/`, SHALL mostrar no banner as contagens por classe e
os compartilháveis, e SHALL anexar ao relatório final uma seção determinística com as
marcações.

#### Scenario: Relatório
- **GIVEN** uma sessão com um arquivo compartilhável e dois de pesquisa
- **WHEN** o relatório final é gerado
- **THEN** a seção "Dados de entrada e marcações" lista os três arquivos com classe, marcação e motivo, gerada sem LLM

#### Scenario: Sem manifesto
- **GIVEN** `input_context/` sem `dados.yaml`
- **WHEN** a sessão inicia
- **THEN** todos os arquivos têm `origem="padrao"` no payload e a sessão prossegue
