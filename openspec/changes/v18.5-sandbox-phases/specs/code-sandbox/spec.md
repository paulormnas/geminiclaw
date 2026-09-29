# Delta: code-sandbox

## ADDED Requirements

### Requirement: Execução do script sem rede
O sistema SHALL executar o script gerado (fase `execute`) em container com a rede desativada,
inclusive quando a execução declara `packages` ou `assets`, exceto no caso do requisito
"Exceção de rede para entradas compartilháveis".

#### Scenario: Pacotes declarados não ligam a rede do script
- **GIVEN** uma chamada da skill de código com `packages=["scikit-learn"]`
- **WHEN** a execução chega à fase `execute`
- **THEN** o container da fase `execute` é criado com `network_disabled=True`
- **AND** o resultado traz `rede_na_execucao=False`

#### Scenario: Sem pacotes nem ativos
- **WHEN** a skill é chamada só com `code`
- **THEN** apenas o container da fase `execute` é criado, sem rede

### Requirement: Preparação com rede e sem dados
O sistema SHALL executar as fases `install` e `fetch_assets` em container separado do da fase
`execute`, com rede e **sem** montar `input_snapshot/`, o diretório de saída da subtarefa ou
diretórios de sessões anteriores, e SHALL remover esse container antes de iniciar a fase
`execute`.

#### Scenario: Montagens da preparação
- **GIVEN** uma execução com `packages` e `assets`
- **WHEN** o container de preparação é criado
- **THEN** suas únicas montagens são o diretório temporário de dependências e a área de download da execução
- **AND** nenhuma variável de ambiente do host além de `HOME`, `UV_CACHE_DIR` e `PATH` é repassada

#### Scenario: Container de preparação removido antes da execução
- **WHEN** a preparação termina com sucesso
- **THEN** o container de preparação já foi removido quando o container da fase `execute` é criado

### Requirement: Instalação sem root e com falha explícita
O sistema SHALL instalar pacotes com comando fixo montado pelo sandbox, como usuário não-root,
e MUST falhar a execução quando a instalação falhar ou estourar o tempo, sem executar o script.

#### Scenario: Pacote inexistente
- **WHEN** a skill é chamada com `packages=["pacote-que-nao-existe-xyz"]`
- **THEN** o resultado tem `fase_falha="install"` e `success=False`
- **AND** o script não é executado
- **AND** a mensagem de erro identifica o pacote

#### Scenario: Requisito de pacote inválido
- **WHEN** `packages` contém `"--index-url=http://exemplo"` ou `"git+https://…"`
- **THEN** a execução é recusada antes de criar containers, com erro explicando o formato aceito

#### Scenario: Nenhum comando como root
- **WHEN** qualquer fase é executada
- **THEN** nenhum `exec_run` usa `user='root'` e os containers rodam com o UID/GID do orquestrador

### Requirement: Ativos declarados, verificados e em cache
O sistema SHALL baixar os ativos declarados em `assets` apenas na fase `fetch_assets`, por
script fixo do projeto, SHALL calcular o sha256 de cada ativo no host, MUST falhar a execução
quando o sha256 declarado divergir do calculado e SHALL disponibilizar os ativos somente
leitura em `/assets/<destino>` na fase `execute`.

#### Scenario: Hash divergente
- **GIVEN** um ativo declarado com `sha256` diferente do conteúdo servido pela URL
- **WHEN** a fase `fetch_assets` termina
- **THEN** o resultado tem `fase_falha="fetch_assets"` com os dois hashes na mensagem, e o script não roda

#### Scenario: Ativo sem hash declarado
- **WHEN** um ativo é declarado com `sha256=null`
- **THEN** o ativo é baixado, o hash calculado é registrado em `ativos` com `hash_declarado=false`

#### Scenario: Ativo já em cache
- **GIVEN** um ativo com `sha256` declarado já presente em `SANDBOX_ASSET_CACHE_DIR`
- **WHEN** a execução é preparada sem `packages`
- **THEN** nenhum container de preparação é criado e o ativo aparece com `origem="cache"`

#### Scenario: Destino ou URL recusados
- **WHEN** um ativo tem `destino="../x"` ou URL `http://169.254.169.254/` ou `file:///etc/passwd`
- **THEN** a execução é recusada com erro explicando o bloqueio

### Requirement: Entrega de dados somente leitura na execução
O sistema SHALL entregar os insumos da sessão (`input_snapshot/`) ao script em `/inputs`, por
montagem somente leitura (padrão) ou por cópia (`put_archive`), e SHALL montar como graváveis
apenas o diretório de saída da subtarefa.

#### Scenario: Montagem somente leitura
- **GIVEN** `SANDBOX_INPUT_DELIVERY=mount` e `dados.csv` em `input_snapshot/`
- **WHEN** o script tenta gravar em `/inputs/dados.csv`
- **THEN** a gravação falha por sistema de arquivos somente leitura e o arquivo do host fica intacto

#### Scenario: Entrega por cópia
- **GIVEN** `SANDBOX_INPUT_DELIVERY=copy`
- **WHEN** o script lê `/inputs/dados.csv`
- **THEN** o conteúdo é o do `input_snapshot/` e o resultado traz `modo_entrega="copy"`

#### Scenario: Origem de montagem fora do lugar
- **GIVEN** um symlink em `input_snapshot/` apontando para fora da sessão
- **WHEN** a execução é preparada
- **THEN** a execução é recusada antes de criar o container

### Requirement: Erro acionável para download não declarado
O sistema SHALL, quando o script falhar na fase `execute` sem rede com uma assinatura de falha
de rede, devolver ao agente uma mensagem fixa orientando a declarar o ativo em `assets`, sem
repetir URL nem trechos do `stderr`.

#### Scenario: Download dentro do script
- **WHEN** o script chama `urllib.request.urlopen("https://exemplo.org/pesos.bin")` na fase `execute`
- **THEN** o resultado tem `download_nao_declarado=True`
- **AND** o erro devolvido pela skill contém "declare-os no parâmetro `assets`"

#### Scenario: Falha que não é de rede
- **WHEN** o script termina com `ValueError`
- **THEN** `download_nao_declarado=False` e o erro segue o fluxo normal

### Requirement: Exceção de rede para entradas compartilháveis
O sistema MAY executar a fase `execute` com rede somente quando a chamada pedir
`needs_network=true`, todos os arquivos de `/inputs` estiverem marcados `compartilhavel` e
nenhum dado produzido por execução estiver visível ao script; nos demais casos SHALL executar
sem rede e informar a condição que falhou.

#### Scenario: Todas as entradas compartilháveis
- **GIVEN** o classificador marca todos os arquivos de `input_snapshot/` como `compartilhavel` e o diretório de saída da subtarefa está vazio
- **WHEN** a skill é chamada com `needs_network=true`
- **THEN** a fase `execute` tem rede, o resultado traz `rede_na_execucao=True` e um `WARNING` é registrado

#### Scenario: Uma entrada não compartilhável
- **GIVEN** um arquivo de `input_snapshot/` sem a marcação `compartilhavel`
- **WHEN** a skill é chamada com `needs_network=true`
- **THEN** a fase `execute` roda sem rede e o erro informa que há entradas não compartilháveis

#### Scenario: Classificador padrão
- **GIVEN** que `v18.5-research-data-ingestion` ainda não está implementada
- **WHEN** qualquer execução pede `needs_network=true`
- **THEN** a fase `execute` roda sem rede

### Requirement: Resultado estruturado do sandbox
O sistema SHALL devolver em `SandboxResult` a fase que falhou, o nome, id e digests da imagem,
a versão do Python, os pacotes visíveis na execução com versões, os ativos com URL, sha256 e
origem, o modo de entrega dos dados, se houve rede na execução e a duração de cada fase.

#### Scenario: Execução com pacote
- **WHEN** uma execução com `packages=["tabulate"]` termina com sucesso
- **THEN** `pacotes` contém `tabulate` com a versão instalada e `imagem.id` não é vazio
- **AND** `fases` lista `install` e `execute` com início, fim e código de saída

#### Scenario: Daemon indisponível
- **WHEN** o daemon Docker não responde após as retentativas
- **THEN** o resultado tem `fase_falha="infra"`

### Requirement: Sandbox fora do event loop
A skill de código SHALL executar o sandbox em thread (`asyncio.to_thread`), sem bloquear o
event loop do orquestrador.

#### Scenario: Duas subtarefas em paralelo
- **GIVEN** duas subtarefas independentes do DAG que chamam a skill de código
- **WHEN** ambas executam scripts que dormem 2 s
- **THEN** o tempo total das duas é menor que 4 s
