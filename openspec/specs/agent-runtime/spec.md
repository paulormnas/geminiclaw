# Especificação: agent-runtime

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md), [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md), [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Agentes executam em processo no host
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
O sistema SHALL executar os agentes (Researcher, Developer, Summarizer, Validator e
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
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
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
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
O sistema SHALL isolar cada execução de agente com timeout e captura de exceções.

#### Scenario: Timeout
- **WHEN** um agente excede `AGENT_TIMEOUT_SECONDS`
- **THEN** o resultado é `AgentResult(status="timeout")` e as demais tarefas do DAG seguem

#### Scenario: Exceção
- **WHEN** uma ferramenta levanta exceção não tratada
- **THEN** o resultado é `AgentResult(status="error")` com a mensagem, e o orquestrador continua

### Requirement: Código gerado executa apenas no sandbox
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
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
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
O sistema SHALL recusar qualquer escrita de artefato fora de `outputs/<sessão>/artifacts/`.

#### Scenario: Path traversal
- **WHEN** `write_artifact("../../etc/passwd", "x")` é chamado
- **THEN** o arquivo é gravado como `outputs/<sessão>/artifacts/passwd` ou recusado, nunca fora do diretório

#### Scenario: Symlink
- **GIVEN** um symlink em `artifacts/` apontando para fora da sessão
- **WHEN** um artefato com esse nome é gravado
- **THEN** a escrita é recusada

### Requirement: Leitura web sem acesso à rede local
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
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
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
O sistema SHALL encaminhar perguntas ao pesquisador por chamada direta ao orquestrador,
preservando deduplicação e registro da Spec G5.

#### Scenario: Pergunta repetida
- **GIVEN** uma pergunta já respondida na sessão
- **WHEN** um agente faz pergunta semelhante acima de `ASK_RESEARCHER_DEDUP_SIMILARITY`
- **THEN** a resposta anterior é reutilizada sem perguntar de novo

### Requirement: Busca do Researcher sem subprocesso de fornecedor
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
O sistema SHALL realizar a busca técnica do Researcher pela skill `search_quick`, sem executar
binários externos.

#### Scenario: Busca técnica
- **WHEN** o Researcher busca documentação de uma biblioteca
- **THEN** a skill `search_quick` é usada e nenhum subprocesso é criado

### Requirement: Limites de execução separados
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL contar as execuções de agente da sessão (planejamento e subtarefa, em contadores distintos) e as relatar nas métricas de operação, e MUST NOT interromper novas execuções nem encerrar a sessão por esse número (ADR 021 §5.1). O controle de gasto fica com os limites de custo, tokens, tempo e egresso (spec `usage-limits`). `MAX_AGENT_RUNS_PER_SESSION` e o alias `MAX_CONTAINERS_PER_SESSION` deixam de existir.
(Antes: o circuit breaker por `MAX_AGENT_RUNS_PER_SESSION` interrompia novas execuções e fechava com `limite_execucoes`.)

#### Scenario: Muitas execuções não encerram a sessão
- **GIVEN** uma sessão simulada que já fez 45 execuções de subtarefa e 25 de planejamento, com limites de uso folgados
- **WHEN** uma nova subtarefa é despachada
- **THEN** a execução ocorre, nenhuma `AgentRunLimitReached` é lançada e nenhum `motivo_parada = "limite_execucoes"` é gravado
- **AND** `operation_metrics.custo_recursos.execucoes_agente` registra `{"planejamento": 25, "execucao": 46}` no fechamento

### Requirement: Sandbox não bloqueia o runtime
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
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
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
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
_Origem: [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md)_
O sistema SHALL permitir que um agente ingira apenas arquivos de `input_snapshot/` ou `artifacts/`
da própria sessão, resolvendo links simbólicos antes da checagem.

#### Scenario: Arquivo do host
- **WHEN** um agente chama `ingest` com `/etc/passwd`
- **THEN** a ingestão é recusada com erro e nenhum extrator é executado

#### Scenario: Symlink para fora da sessão
- **GIVEN** um link em `input_snapshot/` apontando para um arquivo fora da sessão
- **WHEN** um agente chama `ingest` com esse link
- **THEN** a ingestão é recusada

### Requirement: Papéis de subtarefa do plano
_Origem: [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md)_
Uma subtarefa do plano SHALL ser atribuída só a `developer` ou `researcher`. O normalizador do plano
SHALL reparar `base` para `developer` e SHALL tratar `reviewer` e `summarizer` (e sinônimos) como não
recuperáveis, com mensagem que lista os papéis válidos.

#### Scenario: `base` no plano
- **GIVEN** um plano com uma subtarefa `agent_id: "base"`
- **WHEN** o plano é normalizado
- **THEN** a subtarefa fica com `agent_id = "developer"`
- **AND** o reparo `normalize_agent_id` é registrado

#### Scenario: `reviewer` no plano
- **GIVEN** um plano com uma subtarefa `agent_id: "reviewer"`
- **WHEN** o plano é normalizado
- **THEN** o plano tem um problema não recuperável que cita `developer` e `researcher`

#### Scenario: Papéis internos continuam executáveis
- **WHEN** o runtime em processo monta `AGENT_DEFINITIONS`
- **THEN** o registro contém `developer`, `researcher`, `summarizer`, `base` e `curator`
- **AND** não contém `reviewer`

### Requirement: Monitor de recursos multiplataforma
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
O sistema SHALL ler memória, CPU e temperatura por um único `HealthMonitor` que funciona em Linux e macOS sobre a biblioteca `psutil`, MUST NOT executar comandos externos (`vcgencmd` ou outro subprocesso) para isso e MUST NOT devolver valor fixo ou estimado quando a plataforma não expõe uma leitura: a leitura indisponível vem como `None` (ADR 023 §1.1, item 1).

#### Scenario: Temperatura indisponível no macOS
- **GIVEN** um backend simulado sem `sensors_temperatures` (como no macOS) e com memória disponível de 2048 MB
- **WHEN** o monitor é consultado
- **THEN** `get_temperature()` devolve `None` e `get_memory_usage()["available_mb"]` devolve `2048.0`
- **AND** `is_throttled()` devolve `None`

#### Scenario: Nenhum subprocesso
- **GIVEN** `subprocess.run` e `subprocess.Popen` substituídos por funções que falham o teste
- **WHEN** os quatro métodos do monitor são chamados em backend Linux simulado
- **THEN** nenhum subprocesso é criado

#### Scenario: Leitura de memória que falha
- **GIVEN** um backend cuja leitura de memória levanta exceção
- **WHEN** `get_memory_usage()` é chamado
- **THEN** devolve `None`, nunca `{"total_mb": 8192.0, "available_mb": 4096.0, ...}`

#### Scenario: Sensor escolhido
- **GIVEN** sensores simulados `cpu_thermal` a 61,0 °C e `nvme` a 48,0 °C
- **WHEN** a temperatura é lida com `TEMPERATURE_SENSOR` vazio e depois com `TEMPERATURE_SENSOR=nvme`
- **THEN** as leituras são 61,0 e 48,0
- **AND** com `TEMPERATURE_SENSOR=inexistente` a leitura é `None`

### Requirement: Valor desconhecido tratado explicitamente
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
Quem consome o monitor SHALL tratar `None` como desconhecido: a espera por saúde MUST NOT esperar por uma leitura desconhecida e SHALL registrar aviso; a temperatura SHALL entrar nas verificações somente com `TEMPERATURE_LIMIT` definido (sem padrão); o aviso de temperatura SHALL sair a partir de `TEMPERATURE_LIMIT - TEMPERATURE_WARNING_MARGIN_C` (padrão 5,0), não em 70 °C fixos (ADR 023 §1.1, item 2).

#### Scenario: Temperatura ignorada sem limite
- **GIVEN** `TEMPERATURE_LIMIT` vazio e temperatura lida de 90,0 °C, memória disponível de 4096 MB
- **WHEN** `wait_for_health` roda
- **THEN** retorna sem esperar e sem aviso de temperatura

#### Scenario: Espera por temperatura com limite
- **GIVEN** `TEMPERATURE_LIMIT=80` e leituras sucessivas de 82,0, 81,0 e 70,0 °C
- **WHEN** `wait_for_health` roda com intervalo simulado
- **THEN** retorna depois da terceira leitura

#### Scenario: Aviso derivado do limite
- **GIVEN** `TEMPERATURE_LIMIT=80` e `TEMPERATURE_WARNING_MARGIN_C=5`
- **WHEN** a temperatura lida é 75,0 e depois 74,0
- **THEN** há aviso de temperatura elevada para 75,0 e não para 74,0

#### Scenario: Memória desconhecida não bloqueia
- **GIVEN** `get_memory_usage()` devolve `None`
- **WHEN** `wait_for_health` roda
- **THEN** retorna sem esperar e registra `WARNING` "memória desconhecida"

#### Scenario: Limitação térmica derivada
- **GIVEN** `TEMPERATURE_LIMIT=75`
- **WHEN** a temperatura lida é 76,0, depois 60,0, depois desconhecida
- **THEN** `is_throttled()` devolve `True`, `False` e `None`

### Requirement: Aviso de proteção térmica desligada
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
Na inicialização, quando a plataforma é Linux, o `HealthMonitor` lê uma temperatura (valor diferente de `None`) e `TEMPERATURE_LIMIT` não está definido, o sistema SHALL registrar um `WARNING` uma única vez por processo dizendo que a proteção térmica está desligada e que `TEMPERATURE_LIMIT` deve ser declarado no `.env`, e o REPL SHALL mostrar o mesmo aviso no cabeçalho. O sistema MUST NOT emitir o aviso quando `TEMPERATURE_LIMIT` está definido, quando a plataforma não é Linux ou quando a temperatura não pode ser lida. O aviso MUST NOT impedir a inicialização.

#### Scenario: Aviso no Linux com sensor legível e sem limite
- **GIVEN** plataforma Linux, `TEMPERATURE_LIMIT` vazio e sensor simulado com 55,0 °C
- **WHEN** a inicialização roda duas vezes no mesmo processo
- **THEN** há exatamente um `WARNING` que cita `TEMPERATURE_LIMIT`
- **AND** a inicialização conclui sem erro

#### Scenario: Sem aviso quando o limite está definido ou não há leitura
- **GIVEN** plataforma Linux com sensor simulado a 55,0 °C e `TEMPERATURE_LIMIT=80`; depois plataforma Linux sem leitura de temperatura e `TEMPERATURE_LIMIT` vazio; depois plataforma não Linux com `TEMPERATURE_LIMIT` vazio
- **WHEN** a inicialização roda em cada caso
- **THEN** nenhum `WARNING` de proteção térmica desligada é registrado

### Requirement: Limite de agentes simultâneos sem padrão silencioso
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
`calculate_dynamic_limit` SHALL manter as faixas atuais (6 GB ou mais disponíveis: 3; 3 GB ou mais: 2; abaixo: 1), limitadas por `MAX_CONCURRENT_AGENTS`, e, sem leitura de memória, SHALL usar `MAX_CONCURRENT_AGENTS` com aviso explícito, em vez de um padrão fixo de 3 (ADR 023 §1.1, item 2).

#### Scenario: Sem leitura de memória
- **GIVEN** `MAX_CONCURRENT_AGENTS=2` e memória desconhecida
- **WHEN** o limite é calculado
- **THEN** o limite é 2 e o log tem `WARNING` citando `MAX_CONCURRENT_AGENTS=2`

#### Scenario: Faixa de memória
- **GIVEN** `MAX_CONCURRENT_AGENTS=3` e 3500 MB disponíveis
- **WHEN** o limite é calculado
- **THEN** o limite é 2

### Requirement: Limites de recursos sem designação de máquina
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
O sistema SHALL ler o mínimo de memória para iniciar um agente de `MIN_AVAILABLE_MEMORY_MB` (padrão 512) e o limite de temperatura de `TEMPERATURE_LIMIT` (sem padrão), e SHALL usar os padrões gerais `MAX_SUBTASKS_PER_TASK=10`, `MAX_CONCURRENT_AGENTS=3` e `AGENT_TIMEOUT_SECONDS=300` em qualquer máquina; nenhum perfil de máquina muda padrões (ADR 023 §1.1, item 3).

#### Scenario: Padrões gerais
- **GIVEN** um ambiente sem nenhuma das variáveis
- **WHEN** `src.config` é importado
- **THEN** `MIN_AVAILABLE_MEMORY_MB == 512`, `TEMPERATURE_LIMIT is None`, `MAX_SUBTASKS_PER_TASK == 10`, `MAX_CONCURRENT_AGENTS == 3` e `AGENT_TIMEOUT_SECONDS == 300`

#### Scenario: Limite de temperatura inválido
- **GIVEN** `TEMPERATURE_LIMIT=-1`
- **WHEN** `src.config` é importado
- **THEN** a importação falha com mensagem que cita `TEMPERATURE_LIMIT`

### Requirement: Tempo limite do agente desligável por configuração
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
`AGENT_TIMEOUT_SECONDS=0` SHALL significar sem tempo limite para o agente; valor negativo ou não inteiro MUST fazer a inicialização falhar com mensagem que cita a variável (ADR 023 §1.1, item 3).

#### Scenario: Zero é sem limite
- **GIVEN** `AGENT_TIMEOUT_SECONDS=0`
- **WHEN** `src.config` é importado e um agente simulado demora 2 s
- **THEN** `AGENT_TIMEOUT_SECONDS is None` e o agente não é interrompido por tempo

#### Scenario: Valor inválido
- **GIVEN** `AGENT_TIMEOUT_SECONDS=abc` (e depois `-5`)
- **WHEN** `src.config` é importado
- **THEN** a importação falha com mensagem que cita `AGENT_TIMEOUT_SECONDS`

### Requirement: Nomes de configuração com designação de máquina removidos
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
Se `PI_TEMPERATURE_LIMIT`, `PI_MIN_AVAILABLE_MEMORY_MB` ou `DEPLOYMENT_PROFILE` estiver definido no ambiente ou no `.env`, a inicialização MUST falhar com `ConfigurationError` cuja mensagem diz o que fazer com cada nome; os nomes antigos MUST NOT ser lidos como sinônimo (ADR 023 §1.1, item 3; caso de aceite 16).

#### Scenario: Prefixo PI_
- **GIVEN** `PI_TEMPERATURE_LIMIT=75.0` e `PI_MIN_AVAILABLE_MEMORY_MB=512.0` no ambiente
- **WHEN** `src.config` é importado
- **THEN** a importação falha com `ConfigurationError`
- **AND** a mensagem cita `TEMPERATURE_LIMIT` e `MIN_AVAILABLE_MEMORY_MB` como nomes novos

#### Scenario: Perfil default
- **GIVEN** `DEPLOYMENT_PROFILE=default`
- **WHEN** `src.config` é importado
- **THEN** a importação falha e a mensagem pede só remover a linha

#### Scenario: Perfil pi5
- **GIVEN** `DEPLOYMENT_PROFILE=pi5`
- **WHEN** `src.config` é importado
- **THEN** a mensagem lista `MAX_SUBTASKS_PER_TASK=5`, `MAX_CONCURRENT_AGENTS=2`, `AGENT_TIMEOUT_SECONDS=0` e `LLM_PROVIDER_PRIORITY=ollama,openai_compatible,google,anthropic,openai`

#### Scenario: Comando direto com nome antigo
- **GIVEN** `PI_MIN_AVAILABLE_MEMORY_MB=512.0` no ambiente de um subprocesso
- **WHEN** `uv run geminiclaw "tarefa"` é executado
- **THEN** o processo termina com código 1 antes de qualquer chamada a provedor, com a mensagem do nome novo

## Requisitos removidos

- Agentes como containers efêmeros com IPC (removido por [`v16-in-process-agents`](../../changes/archive/v16-in-process-agents/proposal.md))
- Agente Reviewer, `src/agents/reviewer/` (removido por [`v18.6-remove-unused-agents`](../../changes/archive/v18.6-remove-unused-agents/proposal.md)): a revisão de subtarefa é feita pelo `validator` (ADR 007)
