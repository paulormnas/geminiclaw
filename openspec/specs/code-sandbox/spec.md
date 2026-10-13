# Especificação: code-sandbox

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md), [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)

## Requirements

### Requirement: Imagem mínima do sandbox
_Origem: [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md)_
O sistema SHALL executar o código gerado numa imagem configurável por `SANDBOX_IMAGE` que
contém apenas Python, `uv` e o conjunto científico básico travado com hashes, e MUST NOT
conter código do projeto (`src/`, `agents/`), extras do projeto nem SDKs de provedores LLM
(ADR 018 §1).

#### Scenario: Conteúdo da imagem
- **GIVEN** a imagem construída a partir de `containers/sandbox/Dockerfile`
- **WHEN** o teste de integração lista o sistema de arquivos e as distribuições instaladas
- **THEN** não existem `/app/src`, `/app/agents` nem as distribuições `docling`, `qdrant-client`, `google-genai`, `anthropic` e `fastembed`
- **AND** `numpy`, `pandas`, `scipy`, `matplotlib`, `scikit-learn` e `seaborn` importam sem rede

#### Scenario: Imagem configurável
- **GIVEN** `SANDBOX_IMAGE=meu-sandbox:1`
- **WHEN** a skill de código executa um script
- **THEN** o container é criado com a imagem `meu-sandbox:1`

#### Scenario: Imagem ausente
- **GIVEN** a imagem configurada não existe localmente
- **WHEN** a skill executa um script
- **THEN** o resultado é erro acionável que diz como construir a imagem, sem tentar `pull` de um nome local

### Requirement: Container sem privilégios
_Origem: [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md)_
O sistema SHALL criar o container do sandbox com o UID/GID do orquestrador, `cap_drop=["ALL"]`,
`no-new-privileges`, `pids_limit`, sistema de arquivos raiz somente leitura e `/tmp` em
`tmpfs`, e MUST NOT executar nenhum comando como root dentro do container (ADR 018 §2).

#### Scenario: Parâmetros de criação
- **WHEN** a skill executa um script com o cliente Docker simulado
- **THEN** `containers.run` recebe `user="<uid>:<gid>"` do processo, `cap_drop=["ALL"]`, `security_opt` com `no-new-privileges:true`, `read_only=True` e `pids_limit` igual a `SANDBOX_PIDS_LIMIT`

#### Scenario: Nenhum root
- **WHEN** um script com `packages` é executado com o cliente simulado
- **THEN** nenhuma chamada a `exec_run` recebe `user="root"`

#### Scenario: Escrita fora das áreas permitidas
- **WHEN** um script tenta gravar em `/opt/sandbox-venv/x` e em `/etc/x`
- **THEN** as duas gravações falham por permissão ou sistema somente leitura
- **AND** gravações em `/outputs`, `/deps` e `/tmp` funcionam

### Requirement: Pacotes sob demanda sem root e com falha explícita
_Origem: [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md)_
O sistema SHALL instalar os pacotes pedidos em `/deps`, diretório temporário por execução,
com comando fixo montado pelo sandbox, SHALL validar cada item pela gramática de requisito do
PEP 508 recusando URL direta, opções e caminhos, e SHALL encerrar a execução sem rodar o
script quando a instalação falhar ou exceder o timeout (ADR 018 §1, §2).

#### Scenario: Pacote inexistente
- **GIVEN** `packages=["pacote-que-nao-existe-123"]`
- **WHEN** a skill executa o script
- **THEN** o script não roda
- **AND** o resultado tem `install_failed=True` e `stderr` cita o pacote e o final do log do `uv`

#### Scenario: Requisito inválido
- **GIVEN** `packages=["--index-url=http://x", "pkg @ https://x/y.whl"]`
- **WHEN** a skill executa o script
- **THEN** nenhum container é criado e o erro cita os dois itens

#### Scenario: Pacote do conjunto básico
- **GIVEN** `packages=["numpy", "os"]`
- **WHEN** a skill executa o script
- **THEN** nenhuma instalação é feita e o container é criado sem rede

#### Scenario: Pacotes registrados
- **GIVEN** `packages=["tabulate"]` instalado com sucesso
- **WHEN** a execução termina
- **THEN** `packages_installed` contém `tabulate` com a versão instalada
- **AND** o diretório `SANDBOX_WORK_DIR/<run_id>` foi removido

### Requirement: Script sem rede depois da instalação
_Origem: [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md)_
O sistema SHALL desconectar o container de todas as redes depois da instalação e antes do
script, SHALL confirmar que nenhuma rede ficou conectada e SHALL abortar a execução se a
desconexão falhar (ADR 018 §2).

#### Scenario: Desconexão antes do script
- **GIVEN** uma execução com `packages`
- **WHEN** o script roda
- **THEN** a desconexão de cada rede ocorreu antes do `exec_run` do script
- **AND** um teste de integração em que o script abre um socket para fora recebe erro de rede

#### Scenario: Desconexão falha
- **GIVEN** o cliente simulado lança erro ao desconectar a rede
- **WHEN** a skill executa o script
- **THEN** o script não roda e o resultado é erro que cita a desconexão

### Requirement: Saída por bind mount restrito à subtarefa
_Origem: [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md)_
O sistema SHALL montar apenas `outputs/<sessão>/<tarefa>/` em `/outputs` com leitura e
escrita, SHALL usar o bind mount como única via de retorno dos artefatos e MUST NOT aplicar
`chmod 777`, `chown` por root ou permissões `0o777`/`0o666` aos artefatos (ADR 018 §3).

#### Scenario: Dono dos artefatos
- **WHEN** um script grava `/outputs/grafico.png`
- **THEN** o arquivo no host pertence ao usuário do orquestrador
- **AND** o modo do arquivo segue a umask do usuário, sem permissão de escrita para outros

#### Scenario: Sem cópia duplicada
- **WHEN** a execução termina com o cliente simulado
- **THEN** `get_archive` não é chamado

#### Scenario: Symlink que escapa
- **GIVEN** um script que cria `/outputs/link -> /etc/passwd`
- **WHEN** a execução termina
- **THEN** o link é removido da pasta da subtarefa, como hoje

### Requirement: Execução do script sem rede
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
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
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
O sistema SHALL executar as fases `install` e `fetch_assets`, cada uma em container separado do da
fase `execute` (e um do outro), com rede e **sem** montar `input_snapshot/`, o diretório de saída da subtarefa ou
diretórios de sessões anteriores, e SHALL remover esse container antes de iniciar a fase
`execute`.

#### Scenario: Montagens da preparação
- **GIVEN** uma execução com `packages` e `assets`
- **WHEN** o container de preparação é criado
- **THEN** o container de download só monta a área de download (`/staging`, gravável) e o diretório de controle (`/control`, somente leitura), e o de instalação só monta o diretório de dependências
- **AND** nenhuma variável de ambiente do host além de `HOME`, `UV_CACHE_DIR` e `PATH` é repassada

#### Scenario: Container de preparação removido antes da execução
- **WHEN** a preparação termina com sucesso
- **THEN** o container de preparação já foi removido quando o container da fase `execute` é criado

### Requirement: Instalação sem root e com falha explícita
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
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
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
O sistema SHALL baixar os ativos declarados em `assets` apenas na fase `fetch_assets`, por
script fixo do projeto, SHALL calcular o sha256 de cada ativo no host, MUST falhar a execução
quando o sha256 declarado divergir do calculado e SHALL disponibilizar os ativos somente
leitura em `/assets/<destino>` na fase `execute`.

#### Scenario: Hash divergente
- **GIVEN** um ativo declarado com `sha256` diferente do conteúdo servido pela URL
- **WHEN** a fase `fetch_assets` termina
- **THEN** o resultado tem `fase_falha="fetch_assets"` com os dois hashes na mensagem, e o script não roda

#### Scenario: Ativo sem hash declarado
- **WHEN** um ativo com URL `https` é declarado com `sha256=null`
- **THEN** o ativo é baixado, o hash calculado é registrado em `ativos` com `hash_declarado=false`

#### Scenario: Ativo sem hash em URL http
- **WHEN** um ativo com URL `http` é declarado sem `sha256`
- **THEN** a execução é recusada informando que sem sha256 a URL precisa ser `https`

#### Scenario: Ativo já em cache
- **GIVEN** um ativo com `sha256` declarado já presente em `SANDBOX_ASSET_CACHE_DIR`
- **WHEN** a execução é preparada sem `packages`
- **THEN** nenhum container de preparação é criado e o ativo aparece com `origem="cache"`

#### Scenario: Destino ou URL recusados
- **WHEN** um ativo tem `destino="../x"` ou URL `http://169.254.169.254/` ou `file:///etc/passwd`
- **THEN** a execução é recusada com erro explicando o bloqueio

### Requirement: Entrega de dados somente leitura na execução
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
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
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
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
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
O sistema MAY executar a fase `execute` com rede somente quando o classificador de insumos a
autorizar explicitamente (verificado antes de qualquer outra regra, inclusive sem insumos), a
chamada pedir `needs_network=true`, todos os arquivos de `/inputs` estiverem marcados `compartilhavel` e
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
- **WHEN** qualquer execução pede `needs_network=true`, com ou sem insumos
- **THEN** a fase `execute` roda sem rede

### Requirement: Resultado estruturado do sandbox
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
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
_Origem: [`v18.5-sandbox-phases`](../../changes/archive/v18.5-sandbox-phases/proposal.md)_
A skill de código SHALL executar o sandbox em thread (`asyncio.to_thread`), sem bloquear o
event loop do orquestrador.

#### Scenario: Duas subtarefas em paralelo
- **GIVEN** duas subtarefas independentes do DAG que chamam a skill de código
- **WHEN** ambas executam scripts que dormem 2 s
- **THEN** o tempo total das duas é menor que 4 s

## Requisitos removidos

- Tradução de caminhos por HOST_PROJECT_PATH (removido por [`v16-sandbox-slim-image`](../../changes/archive/v16-sandbox-slim-image/proposal.md))
