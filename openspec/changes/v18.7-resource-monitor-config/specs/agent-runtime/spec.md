# Delta: agent-runtime

## ADDED Requirements

### Requirement: Monitor de recursos multiplataforma
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
_Origem: parecer do Analista de Segurança (design §4, item 1)._
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
