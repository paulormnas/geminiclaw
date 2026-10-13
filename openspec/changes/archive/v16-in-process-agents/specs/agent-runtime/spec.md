# Delta: agent-runtime

## ADDED Requirements

### Requirement: Agentes executam em processo no host
O sistema SHALL executar os agentes (Researcher, Developer, Summarizer, Reviewer, Validator e
futuros papéis) no processo do orquestrador, sem container dedicado por agente.

#### Scenario: Subtarefa sem spawn de container de agente
- **GIVEN** `AGENT_RUNTIME=inprocess`
- **WHEN** o orquestrador executa uma subtarefa do Developer
- **THEN** nenhum container de agente é criado
- **AND** o `AgentResult` é retornado pelo `AgentRuntime`

#### Scenario: Provedor por papel
- **GIVEN** `RESEARCHER_PROVIDER=ollama` e `DEVELOPER_PROVIDER=openai_compatible`
- **WHEN** as duas subtarefas rodam na mesma sessão
- **THEN** cada agente usa o provedor do seu papel

### Requirement: Contexto isolado por tarefa
O sistema SHALL fornecer a cada tarefa um `AgentContext` próprio, e MUST NOT usar variáveis de
ambiente para estado por tarefa.

#### Scenario: Tarefas concorrentes
- **GIVEN** duas tarefas simultâneas das sessões A e B
- **WHEN** ambas gravam um artefato
- **THEN** o artefato de A fica em `outputs/A/artifacts/` e o de B em `outputs/B/artifacts/`

#### Scenario: Uso fora de uma tarefa
- **WHEN** `get_agent_context()` é chamado fora de uma execução de agente
- **THEN** um erro explícito é levantado

### Requirement: Falha de agente não derruba a sessão
O sistema SHALL isolar cada execução de agente com timeout e captura de exceções.

#### Scenario: Timeout
- **WHEN** um agente excede `AGENT_TIMEOUT_SECONDS`
- **THEN** o resultado é `AgentResult(status="timeout")` e as demais tarefas do DAG seguem

#### Scenario: Exceção
- **WHEN** uma ferramenta levanta exceção não tratada
- **THEN** o resultado é `AgentResult(status="error")` com a mensagem, e o orquestrador continua

### Requirement: Código gerado executa apenas no sandbox
O sistema MUST executar todo código gerado ou modificado por agentes exclusivamente no
sandbox de código, e MUST NOT oferecer no host ferramenta que aceite código, comando de shell,
SQL ou Cypher arbitrário.

#### Scenario: Inventário de ferramentas
- **WHEN** as ferramentas registradas de todos os papéis são inspecionadas
- **THEN** a única que executa código é a skill de código, que delega ao sandbox

#### Scenario: Instalação de pacotes
- **WHEN** um agente precisa de um pacote Python
- **THEN** ele o declara no parâmetro `packages` da skill de código, e a instalação ocorre no sandbox
- **AND** o prompt base não contém instruções de `subprocess`

### Requirement: Escrita confinada ao diretório da sessão
O sistema SHALL recusar qualquer escrita de artefato fora de `outputs/<sessão>/artifacts/`.

#### Scenario: Path traversal
- **WHEN** `write_artifact("../../etc/passwd", "x")` é chamado
- **THEN** o arquivo é gravado como `outputs/<sessão>/artifacts/passwd` ou recusado, nunca fora do diretório

#### Scenario: Symlink
- **GIVEN** um symlink em `artifacts/` apontando para fora da sessão
- **WHEN** um artefato com esse nome é gravado
- **THEN** a escrita é recusada

### Requirement: Leitura web sem acesso à rede local
O sistema SHALL recusar requisições de ferramentas web a endereços de loopback, faixas
privadas, link-local e serviços de metadados, e a esquemas diferentes de `http`/`https`.

#### Scenario: Endereço interno
- **WHEN** o `web_reader` recebe `http://127.0.0.1:5432/` ou `http://169.254.169.254/`
- **THEN** a requisição não é feita e a ferramenta retorna erro explicando o bloqueio

#### Scenario: Nome que resolve para IP privado
- **GIVEN** um domínio que resolve para `192.168.0.10`
- **WHEN** o `web_reader` é chamado com esse domínio
- **THEN** a requisição é recusada

#### Scenario: Faixa CGNAT usada pelo Tailscale
- **WHEN** o `web_reader` recebe `http://100.110.171.110:6333/` ou um domínio que resolve para `100.64.0.0/10`
- **THEN** a requisição é recusada, pois só endereços globalmente roteáveis são permitidos

#### Scenario: IPv4 interno embutido em IPv6
- **WHEN** o `web_reader` recebe um host que resolve para `::ffff:127.0.0.1`
- **THEN** a requisição é recusada

### Requirement: ask_researcher em processo
O sistema SHALL encaminhar perguntas ao pesquisador por chamada direta ao orquestrador,
preservando deduplicação e registro da Spec G5.

#### Scenario: Pergunta repetida
- **GIVEN** uma pergunta já respondida na sessão
- **WHEN** um agente faz pergunta semelhante acima de `ASK_RESEARCHER_DEDUP_SIMILARITY`
- **THEN** a resposta anterior é reutilizada sem perguntar de novo

### Requirement: Busca do Researcher sem subprocesso de fornecedor
O sistema SHALL realizar a busca técnica do Researcher pela skill `search_quick`, sem executar
binários externos.

#### Scenario: Busca técnica
- **WHEN** o Researcher busca documentação de uma biblioteca
- **THEN** a skill `search_quick` é usada e nenhum subprocesso é criado

### Requirement: Limites de execução separados
O sistema SHALL limitar execuções de agentes por `MAX_AGENT_RUNS_PER_SESSION` e containers de
sandbox por `MAX_CONTAINERS_PER_SESSION`.

#### Scenario: Limite de execuções de agentes
- **WHEN** a sessão atinge `MAX_AGENT_RUNS_PER_SESSION`
- **THEN** o circuit breaker interrompe novas execuções de agentes e registra o evento

### Requirement: Sandbox não bloqueia o runtime
O sistema SHALL executar o sandbox de código fora do event loop do processo e SHALL limitar o tempo
da instalação de pacotes.

#### Scenario: Event loop livre durante a execução
- **GIVEN** uma execução de código no sandbox que leva 500 ms
- **WHEN** outra corrotina do processo agenda tarefas curtas
- **THEN** essas tarefas continuam sendo executadas durante o sandbox

#### Scenario: Instalação de pacotes travada
- **GIVEN** um `uv pip install` que não termina
- **WHEN** `CODE_SANDBOX_SETUP_TIMEOUT_SECONDS` é excedido
- **THEN** o container é encerrado e o resultado é `timed_out` com mensagem sobre a instalação

### Requirement: Artefatos do sandbox extraídos sem sair da pasta da tarefa
O sistema SHALL extrair no host apenas os membros do tar do sandbox que permanecem dentro da pasta
da tarefa, e MUST NOT alterar permissões de arquivos fora dela.

#### Scenario: Symlink para arquivo do host
- **GIVEN** código no sandbox que cria um link simbólico para um arquivo do host
- **WHEN** a execução termina e os artefatos são extraídos
- **THEN** o link não existe mais na pasta da tarefa (mesmo tendo sido criado pelo bind mount)
- **AND** as permissões do arquivo do host permanecem inalteradas

#### Scenario: Symlink interno à pasta da tarefa
- **GIVEN** um link simbólico cujo alvo está dentro da própria pasta da tarefa
- **WHEN** a execução termina
- **THEN** o link é preservado

#### Scenario: Caminho fora da pasta
- **GIVEN** um membro do tar com caminho absoluto ou `../`
- **WHEN** os artefatos são extraídos
- **THEN** o membro é ignorado e os demais artefatos são extraídos

### Requirement: Ingestão de documentos confinada à sessão
O sistema SHALL permitir que um agente ingira apenas arquivos de `input_snapshot/` ou `artifacts/`
da própria sessão, resolvendo links simbólicos antes da checagem.

#### Scenario: Arquivo do host
- **WHEN** um agente chama `ingest` com `/etc/passwd`
- **THEN** a ingestão é recusada com erro e nenhum extrator é executado

#### Scenario: Symlink para fora da sessão
- **GIVEN** um link em `input_snapshot/` apontando para um arquivo fora da sessão
- **WHEN** um agente chama `ingest` com esse link
- **THEN** a ingestão é recusada

## REMOVED Requirements

### Requirement: Agentes como containers efêmeros com IPC
**Motivo:** ADR 014. Removido na fase 2, após validação e aprovação explícita.

#### Scenario: Sem IPC de agentes
- **WHEN** a fase 2 é concluída
- **THEN** `src/ipc.py` e `agents/runner.py` não existem e nenhuma imagem de agente é construída
