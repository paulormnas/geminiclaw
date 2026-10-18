# Proposta: Monitor de Recursos Multiplataforma e Configuração sem Designação de Máquina

**ID:** `v18.7-resource-monitor-config` · **Versão:** V18.7 · **Capacidade:** `agent-runtime`, `llm-providers`, `operation-metrics`
**ADRs de origem:** [ADR 023](../../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) §1.1 (monitor multiplataforma, limites, variáveis sem designação de máquina); casos de aceite 16 e 17
**Depende de:** nenhuma mudança da V18.7 (pode ser implementada primeiro) Implementada depois de `v18.7-source-layout` e `v18.7-layer-cycles` (onda 0, ADR 024), cujos caminhos novos valem para os citados aqui.
**É pré-requisito de:** `v18.7-background-sessions` (verificação de memória antes de iniciar e conferência de PID) e `v18.7-exploration-limits` (acrescenta os nomes dela ao mecanismo `_REMOVED_VARIABLES` / `check_removed_variables` criado aqui)

## Por quê

O monitor de recursos (`src/health.py:11`, `PiHealthMonitor`) é específico do Raspberry Pi: lê `/proc` e `thermal_zone0`, chama `vcgencmd` por subprocesso (`src/health.py:40`, `src/health.py:133`) e, fora do Linux, devolve valores fixos (temperatura 45,0 em `src/health.py:27`, memória 8192/4096 MB em `src/health.py:56`, CPU 20,0 em `src/health.py:92`, sem limitação em `src/health.py:130`). Esses valores são dado inventado (AGENTS.md §1.6) e entram na telemetria (`src/autonomous_loop.py:1575-1598`) e nas métricas de operação.

A configuração também carrega a máquina no nome: `PI_TEMPERATURE_LIMIT` e `PI_MIN_AVAILABLE_MEMORY_MB` (`src/config.py:377-378`) e o perfil `DEPLOYMENT_PROFILE=pi5` (`src/config.py:135-153`, `src/llm/availability.py:32-35`), que muda em silêncio quatro padrões. O pesquisador decidiu (ADR 023, Contexto) que o sistema roda em máquinas diferentes e que nenhuma configuração fica atrelada a uma delas. A próxima mudança (`v18.7-background-sessions`) precisa de uma leitura de memória confiável em qualquer plataforma para decidir se uma pesquisa pode começar.

## O que muda

- **Novo:** `HealthMonitor` multiplataforma (Linux e macOS) em `src/health.py`, sobre a biblioteca `psutil`, sem subprocesso; leitura indisponível vem como `None` (desconhecido), nunca estimada.
- **Novo:** `TEMPERATURE_LIMIT` opcional, sem padrão; `MIN_AVAILABLE_MEMORY_MB` (padrão 512); `TEMPERATURE_SENSOR` opcional; `TEMPERATURE_WARNING_MARGIN_C` (padrão 5,0).
- **Novo:** mecanismo de nomes removidos na importação de `src/config.py` (`_REMOVED_VARIABLES` e `check_removed_variables`, reutilizado por `v18.7-exploration-limits`): `PI_TEMPERATURE_LIMIT`, `PI_MIN_AVAILABLE_MEMORY_MB` ou `DEPLOYMENT_PROFILE` no ambiente fazem a inicialização falhar com a mensagem do que fazer.
- **Modificado:** `AGENT_TIMEOUT_SECONDS=0` passa a significar sem tempo limite; valor negativo ou não inteiro falha na inicialização.
- **Modificado:** a limitação térmica registrada na telemetria (`is_throttled`) passa a ser a temperatura frente a `TEMPERATURE_LIMIT`; o aviso fixo de 70 °C (`src/agent_runtime/resources.py:88-89`) passa a derivar de `TEMPERATURE_LIMIT`.
- **Modificado:** `calculate_dynamic_limit` sem leitura de memória usa `MAX_CONCURRENT_AGENTS` com aviso explícito, em vez do padrão silencioso de 3 (`src/agent_runtime/resources.py:33`, `:49`, `:62`).
- **Modificado:** `parse_priority` deixa de receber o perfil (`src/llm/availability.py:71-76`, `src/llm/session.py:256`, `:279`); a prioridade padrão é uma só.
- **Removido:** classe `PiHealthMonitor`, chamadas a `vcgencmd` em `src/health.py`, valores fixos fora do Linux, `DEPLOYMENT_PROFILE`, `PROFILE_PRIORITY`, `PI_TEMPERATURE_LIMIT`, `PI_MIN_AVAILABLE_MEMORY_MB`.
- **Fora do escopo:** detecção de plataforma para escolher imagens (`src/platform_info.py`, `scripts.platform_images`); scripts de instalação no Pi (`scripts/setup_pi.sh`, `scripts/setup_ollama_pi5.sh`); o amostrador do benchmark (`scripts/benchmark/resources.py`), que mede o host do benchmark e continua como está (ver Questões em aberto do design); qualquer verificação de memória ao iniciar uma pesquisa (é de `v18.7-background-sessions`).

## Impacto

- **Código:** `src/health.py`, `src/agent_runtime/resources.py`, `src/autonomous_loop.py`, `src/config.py`, `src/llm/availability.py`, `src/llm/session.py`, `src/cli.py` (texto de ajuda de `--timeout`).
- **Contratos:** `HealthMonitor` mantém os métodos de hoje (`get_temperature`, `get_memory_usage`, `get_cpu_usage`, `is_throttled`), com `None` como desconhecido; `parse_priority(raw)` perde o segundo parâmetro.
- **Configuração e documentação:** `.env.example` (linhas 35, 170-174, 312-313, 408-411), `README.md:39`, `OLLAMA_PI5.md:38`.
- **Testes:** `tests/unit/test_health.py` (reescrito), `tests/unit/test_agent_runtime_resources.py`, `tests/unit/test_config.py`, `tests/unit/llm/test_availability.py:208`, novo `tests/unit/test_thermal_warning.py`; auxiliares compartilhados novos `tests/support/fake_psutil_backend.py` e `tests/support/env_override.py`.
- **Schema:** nenhum. A coluna `hardware_snapshots.is_throttled` (`scripts/init_db.sql:195`) já aceita `NULL`; muda só a semântica (derivada da temperatura).
- **Custo:** nenhum (sem chamada a LLM).

## Aprovações necessárias

- **Dependência nova:** `psutil` como dependência direta do núcleo (`uv add psutil`). Hoje ela já está no `uv.lock` (7.2.2) só como dependência transitiva de `accelerate`; passa a ser declarada em `pyproject.toml`.
- **Migração do `.env` em toda máquina derivada do `.env.example`**, inclusive o `.env` do Raspberry Pi usado nos testes, migrado junto com a mudança. Variáveis removidas: `DEPLOYMENT_PROFILE`, `PI_TEMPERATURE_LIMIT`, `PI_MIN_AVAILABLE_MEMORY_MB`. Variáveis a declarar no `.env` do Pi com os valores efetivos de hoje, capturados com o código atual antes do merge (tarefa 0.2): `MAX_SUBTASKS_PER_TASK`, `MAX_CONCURRENT_AGENTS`, `AGENT_TIMEOUT_SECONDS`, `LLM_PROVIDER_PRIORITY`, `TEMPERATURE_LIMIT`, `MIN_AVAILABLE_MEMORY_MB`. A edição do `.env` do Pi exige acesso ao Pi; pela decisão de 2026-10-07 (sem testes no Pi até a bateria final), o pesquisador decide quando ela é feita. A declaração de `TEMPERATURE_LIMIT` no `.env` do Pi é obrigatória (parecer de segurança, design §4, item 1) e bloqueia só a bateria no Pi: nenhuma execução no Pi começa sem ela, mas o merge não depende dela.
- **Auxiliares de teste compartilhados:** esta mudança cria `FakePsutilBackend` e `env_override` em `tests/support/` (tarefas 1.0 e 3.0), reutilizados pelas mudanças V18.7 seguintes. Nenhuma dependência de desenvolvimento nova (usam só `pytest`, `monkeypatch` e `importlib`, já presentes).
- **Schema:** nenhuma alteração.
- **Exclusão de arquivos:** nenhuma (o código removido fica dentro de arquivos que continuam existindo).
