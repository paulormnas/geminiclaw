# Delta: code-sandbox

## ADDED Requirements

### Requirement: Imagem mínima do sandbox
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

## REMOVED Requirements

### Requirement: Tradução de caminhos por HOST_PROJECT_PATH
**Motivo:** existia para o orquestrador em container (Docker-in-Docker), removido pelo ADR 014
(#80, #81). O sandbox monta o caminho real do host.

#### Scenario: Variável ignorada
- **GIVEN** `HOST_PROJECT_PATH=/qualquer` no ambiente
- **WHEN** a skill executa um script
- **THEN** a origem do bind mount é o caminho resolvido de `outputs/<sessão>/<tarefa>/`
