# Design: Monitor de Recursos Multiplataforma e Configuração sem Designação de Máquina

## 0. Estado atual (verificado na branch `docs/adr-021-022-exploracao-contrato`, 2026-10-15)

| Ponto | Onde | O que faz hoje |
|---|---|---|
| Classe do monitor | `src/health.py:11` | `PiHealthMonitor`, "focado no Raspberry Pi 5", com "fallback gracioso" fora do Linux |
| Temperatura | `src/health.py:21-47` | fora do Linux devolve 45,0 (`:27`); no Linux lê `thermal_zone0` (`:31-34`) e, se falhar, `vcgencmd measure_temp` por subprocesso (`:40`) |
| Memória | `src/health.py:49-85` | fora do Linux devolve `{"total_mb": 8192.0, "available_mb": 4096.0, "percent": 50.0}` (`:56`); no Linux lê `/proc/meminfo` |
| CPU | `src/health.py:87-125` | fora do Linux devolve 20,0 (`:92`); no Linux lê `/proc/stat` duas vezes com `time.sleep(0.1)` |
| Limitação térmica | `src/health.py:127-143` | fora do Linux devolve `False` (`:130`); no Linux chama `vcgencmd get_throttled` (`:133`) |
| Limite de agentes | `src/agent_runtime/resources.py:33`, `:38-65` | `_DEFAULT_LIMIT = 3` quando a memória não é lida, com aviso que supõe macOS (`:62`) |
| Espera por saúde | `src/agent_runtime/resources.py:68-106` | aviso fixo em 70 °C (`:88-89`); compara com `PI_TEMPERATURE_LIMIT` e `PI_MIN_AVAILABLE_MEMORY_MB` (`:92-95`) |
| Telemetria | `src/autonomous_loop.py:40`, `:125`, `:1572-1600` | instancia `PiHealthMonitor` e grava `hardware_snapshots` com `is_throttled` do `vcgencmd` |
| Perfil | `src/config.py:134-153` | `DEPLOYMENT_PROFILE=pi5` muda `MAX_SUBTASKS_PER_TASK` (5), `MAX_CONCURRENT_AGENTS` (2) e `AGENT_TIMEOUT_SECONDS` (`None`); `AGENT_TIMEOUT_SECONDS` do ambiente passa por `int()` (`:147`), sem como expressar "sem limite" |
| Limites do Pi | `src/config.py:376-378` | `PI_TEMPERATURE_LIMIT` (75,0) e `PI_MIN_AVAILABLE_MEMORY_MB` (512,0) |
| Prioridade de provedores | `src/llm/availability.py:32-35`, `:71-76`; `src/llm/session.py:256`, `:279` | `PROFILE_PRIORITY["pi5"]` põe provedores locais primeiro; `parse_priority(raw, profile)` |
| Timeout do runtime | `src/agent_runtime/runtime.py:77-95` | `None` já significa sem tempo limite; nada a mudar aqui |
| Exemplo de ambiente | `.env.example:35`, `:170-174`, `:312-313`, `:408-411`, `:426` | traz `DEPLOYMENT_PROFILE=default`, `PI_TEMPERATURE_LIMIT=75.0`, `PI_MIN_AVAILABLE_MEMORY_MB=512.0`, `MAX_CONCURRENT_AGENTS=3` e `MAX_SUBTASKS_PER_TASK=10` explícitos |
| Documentação | `README.md:39`, `OLLAMA_PI5.md:38` | recomendam `DEPLOYMENT_PROFILE=pi5` |

Observação que muda a migração do Pi: como o `.env.example` declara `MAX_CONCURRENT_AGENTS=3` e `MAX_SUBTASKS_PER_TASK=10` explicitamente, um `.env` copiado dele já sobrepõe o perfil `pi5` nesses dois valores. "Os valores efetivos de hoje" no Pi não são necessariamente os do perfil (5 e 2); precisam ser lidos do processo real antes do merge (tarefa 0.2).

## 1. Decisões

### 1.1 Biblioteca de leitura: `psutil`

Escolha: `psutil` como dependência direta (`uv add psutil`). Motivos: cobre Linux e macOS com a mesma API (`virtual_memory`, `cpu_percent`, `sensors_temperatures`, `Process.create_time`); tem rodas para `aarch64` Linux e macOS arm64/x86_64; não chama comandos externos; já está no `uv.lock` (7.2.2) como transitiva de `accelerate`, então não aumenta o ambiente instalado; e será usada de novo em `v18.7-background-sessions` para conferir PID e hora de início de processo (evita falso "vivo" por reuso de PID). Alternativas rejeitadas: manter `/proc` e acrescentar leitura própria para macOS (duas implementações a manter e testar, `sysctl` exigiria subprocesso ou `ctypes`); `py-cpuinfo` ou bibliotecas só de temperatura (não cobrem memória).

### 1.2 Contrato do `HealthMonitor`

```python
class HealthMonitor:
    def __init__(self, *, backend: ResourceBackend | None = None) -> None: ...  # backend injetável em testes
    def get_temperature(self) -> float | None: ...       # °C; None = desconhecida
    def get_memory_usage(self) -> dict[str, float] | None: ...  # {"total_mb", "available_mb", "percent"}; None = desconhecida
    def get_cpu_usage(self) -> float | None: ...          # %; psutil.cpu_percent(interval=0.1); None = desconhecida
    def is_throttled(self) -> bool | None: ...            # temperatura >= TEMPERATURE_LIMIT; None sem limite ou sem leitura
```

- **Memória:** `psutil.virtual_memory()`; `available_mb = available / 2**20` (no Linux, `available` é o `MemAvailable` de hoje). Exceção ou plataforma sem suporte devolve `None`.
- **Temperatura:** `psutil.sensors_temperatures()` só existe no Linux e no FreeBSD; ausente (macOS) ou vazio devolve `None`. Com `TEMPERATURE_SENSOR` vazio (padrão), vale a maior leitura `current` entre os sensores (escolha conservadora: o componente mais quente); com valor, só o sensor de mesmo nome (`cpu_thermal` no Pi, por exemplo); sensor ausente devolve `None` com aviso uma única vez por processo.
- **Limitação térmica:** derivada, nunca lida de comando externo: `None` se `TEMPERATURE_LIMIT` não estiver definido ou a temperatura for `None`; senão `temperatura >= TEMPERATURE_LIMIT`.
- **Sem fallback fixo:** nenhum método devolve constante quando a leitura falha. O docstring da classe deixa de mencionar Raspberry Pi.

### 1.3 Quem consome o desconhecido

| Consumidor | Com leitura | Sem leitura (`None`) |
|---|---|---|
| `wait_for_health` (memória) | espera se `available_mb < MIN_AVAILABLE_MEMORY_MB`, como hoje | não espera; registra `WARNING` "memória desconhecida: verificação ignorada" uma vez por processo |
| `wait_for_health` (temperatura) | só com `TEMPERATURE_LIMIT` definido: espera se `>= TEMPERATURE_LIMIT`; aviso a partir de `TEMPERATURE_LIMIT - TEMPERATURE_WARNING_MARGIN_C` | ignorada, sem aviso repetido |
| `calculate_dynamic_limit` | faixas de hoje (>= 6 GB: 3; >= 3 GB: 2; abaixo: 1), limitadas por `MAX_CONCURRENT_AGENTS` | `MAX_CONCURRENT_AGENTS`, com `WARNING` explícito citando o valor usado |
| Telemetria (`hardware_snapshots`) | grava os valores lidos | grava `NULL` na coluna correspondente |
| Métricas de operação (picos) | picos a partir da telemetria | `null`, como a spec `operation-metrics` já prevê |

### 1.4 Configuração (`src/config.py`)

| Variável | Padrão | Significado |
|---|---|---|
| `MIN_AVAILABLE_MEMORY_MB` | `512` | mínimo de memória disponível para iniciar um agente na sessão (hoje) e para iniciar uma pesquisa (`v18.7-background-sessions`) |
| `TEMPERATURE_LIMIT` | vazio | sem valor, a temperatura não entra nas verificações; com valor (°C, > 0), vale como hoje o limite do Pi |
| `TEMPERATURE_WARNING_MARGIN_C` | `5.0` | o aviso de temperatura sai a partir de `TEMPERATURE_LIMIT - margem`; preserva o comportamento atual (aviso em 70 com limite 75) |
| `TEMPERATURE_SENSOR` | vazio | nome do sensor em `psutil.sensors_temperatures()`; vazio = maior leitura |
| `AGENT_TIMEOUT_SECONDS` | `300` | `0` = sem tempo limite (vira `None` internamente); negativo ou não inteiro: falha na inicialização |
| `MAX_SUBTASKS_PER_TASK` | `10` | sem perfil (padrão geral de hoje) |
| `MAX_CONCURRENT_AGENTS` | `3` | sem perfil (padrão geral de hoje) |
| `LLM_PROVIDER_PRIORITY` | vazio = `google,anthropic,openai,ollama,openai_compatible` | prioridade única (a de `PROFILE_PRIORITY["default"]` hoje) |

`TEMPERATURE_LIMIT` inválido (não numérico ou <= 0) e `TEMPERATURE_WARNING_MARGIN_C` negativa falham na inicialização com mensagem que cita a variável.

### 1.5 Nomes removidos falham na inicialização

Função `check_removed_variables(environ)` chamada no fim da importação de `src/config.py` (depois de `load_dotenv()`, então pega tanto o ambiente quanto o `.env`). Levanta `ConfigurationError` (subclasse de `RuntimeError`, que `main()` já trata em `src/cli.py:1645-1649` com código 1) com uma linha por nome encontrado:

| Nome encontrado | Mensagem (resumo) |
|---|---|
| `DEPLOYMENT_PROFILE=default` | "`DEPLOYMENT_PROFILE` foi removida (ADR 023 §1.1): remova a linha do `.env`." |
| `DEPLOYMENT_PROFILE=pi5` | "`DEPLOYMENT_PROFILE` foi removida: remova a linha e declare no `.env` os valores que o perfil aplicava e que você quer manter: `MAX_SUBTASKS_PER_TASK=5`, `MAX_CONCURRENT_AGENTS=2`, `AGENT_TIMEOUT_SECONDS=0`, `LLM_PROVIDER_PRIORITY=ollama,openai_compatible,google,anthropic,openai`." |
| `DEPLOYMENT_PROFILE` com outro valor | "`DEPLOYMENT_PROFILE` foi removida: remova a linha." (o valor não é ecoado) |
| `PI_TEMPERATURE_LIMIT` | "renomeie para `TEMPERATURE_LIMIT` (sem padrão: sem valor, a temperatura não é verificada)." |
| `PI_MIN_AVAILABLE_MEMORY_MB` | "renomeie para `MIN_AVAILABLE_MEMORY_MB`." |

Esta mudança é a dona do mecanismo: o dicionário `_REMOVED_VARIABLES` (nome → mensagem fixa, ou função do valor para as mensagens que dependem dele, como `DEPLOYMENT_PROFILE`) e `check_removed_variables(environ)`, que junta todos os nomes encontrados numa única `ConfigurationError`. `v18.7-exploration-limits`, mergeada depois, só acrescenta os nomes dela ao dicionário (design §12 daquela mudança), sem mecanismo próprio. Sem sinônimos: o nome antigo nunca é lido como valor. A verificação na importação cobre todo ponto de entrada (CLI, processo da sessão da próxima mudança, scripts, benchmark e `pytest`). Consequência deliberada: um `.env` local não migrado faz também os testes falharem, com a mesma mensagem.

### 1.6 Prioridade de provedores

`PROFILE_PRIORITY` vira `DEFAULT_PRIORITY: tuple[str, ...] = ("google", "anthropic", "openai", "ollama", "openai_compatible")`; `parse_priority(raw: str | None) -> tuple[str, ...]`. Quem quiser provedores locais primeiro declara `LLM_PROVIDER_PRIORITY`. Sem mudança na política de dados: com `LLM_DATA_POLICY=self_hosted_only` (padrão), os provedores de nuvem já são descartados antes da prioridade.

## 2. Mapa dos casos de aceite do ADR 023

| Caso | Requisito (spec desta mudança) | Teste |
|---|---|---|
| 16 — nomes antigos no ambiente | `agent-runtime` / "Nomes de configuração com designação de máquina removidos" | `tests/unit/test_config_removed_names.py` (unidade) |
| 17 — leitura indisponível (temperatura no macOS) | `agent-runtime` / "Monitor de recursos multiplataforma" e "Valor desconhecido tratado explicitamente" | `tests/unit/test_health.py` com backend simulado (unidade) |

## 3. Análise de impacto (6 eixos)

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Baixo | `ResourceGuard` e a coleta de telemetria trocam a classe; o limite sem leitura passa a `MAX_CONCURRENT_AGENTS`. |
| Agentes & Prompts | Nenhum | Nenhum prompt ou ferramenta muda. |
| Sandboxes & Containers | Nenhum | O sandbox tem limites próprios (`CODE_SANDBOX_MEMORY_LIMIT`), inalterados. |
| Persistência | Baixo | Sem schema; `hardware_snapshots.is_throttled` muda de semântica (derivado) e passa a ser `NULL` sem `TEMPERATURE_LIMIT`. |
| Segurança | Baixo | Remove dois subprocessos (`vcgencmd`); nenhuma credencial envolvida; a falha por nome antigo é fail-fast. |
| Testes & Telemetria | Médio | `test_health.py` reescrito com backend simulado; testes de config e prioridade atualizados; incidentes de limitação térmica deixam de vir do firmware do Pi. |

## 4. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.** A remoção do `vcgencmd` é positiva.

1. **Médio: a proteção térmica deixa de existir por padrão.** Hoje `PI_TEMPERATURE_LIMIT` vale 75 (`src/config.py:377`), e `TEMPERATURE_LIMIT` não terá padrão. Requisito: o `.env` do Pi declara `TEMPERATURE_LIMIT` antes de qualquer execução no Pi (tarefa 0.2). Quando há sensor legível e `TEMPERATURE_LIMIT` não está definido, a inicialização registra um `WARNING` uma única vez e o REPL mostra o aviso no cabeçalho.
2. **Baixo: memória desconhecida.** Em `wait_for_health`, memória desconhecida gera só aviso e a execução segue. É aceitável porque, no Linux do Pi, a leitura existe. A bateria confirma `psutil.virtual_memory()` no aarch64.
3. **Baixo:** confirmado que as mensagens de nomes removidos não ecoam valores (§1.5). Declarar `psutil` com limite inferior de versão, igual ao do `uv.lock`.

Pontos para o parecer: a remoção do `vcgencmd` elimina duas execuções de subprocesso do host; `psutil` lê só informação do próprio sistema; a mensagem de erro de nome removido não ecoa valores de variáveis (só distingue `default` e `pi5` de `DEPLOYMENT_PROFILE`, que não são segredo).

## 5. Riscos e mitigações

- **Perda do sinal de limitação por subtensão no Pi.** O `vcgencmd get_throttled` também indicava subtensão e limite de frequência, que a temperatura não mostra. Mitigação: o benchmark continua registrando esses bits pelo amostrador próprio (`scripts/benchmark/resources.py`), fora do escopo desta mudança; o ADR 023 decide que a telemetria do sistema não depende de ferramenta de um fabricante.
- **Mudança silenciosa de comportamento no Pi** se o `.env` não for migrado. Mitigação: a inicialização falha com os nomes antigos (§1.5), então não há como rodar com o perfil esquecido.
- **Sensor errado escolhido pelo máximo** (por exemplo, sensor de disco NVMe mais quente que a CPU). Mitigação: `TEMPERATURE_SENSOR` fixa o sensor; o padrão conservador só antecipa o aviso.
- **`cpu_percent(interval=0.1)` bloqueia 100 ms**, como a leitura atual (`time.sleep(0.1)` em `src/health.py:112`). Sem mudança de custo.

## 6. Questões em aberto

1. O amostrador do benchmark (`scripts/benchmark/resources.py:11`, `:24-30`, `:93-98`) também lê `thermal_zone0` e o `vcgencmd`. Esta mudança o deixa como está (é medição do host do benchmark, não configuração). O pesquisador quer migrá-lo para `psutil` na `v18.7-benchmark-fixes`?
2. O argumento `--timeout` da CLI (`src/cli.py:139-144`) não é lido em lugar nenhum (`args.timeout` não tem uso em `src/`). Esta mudança só ajusta o texto de ajuda para "sem limite" quando `AGENT_TIMEOUT_SECONDS=0`; remover o argumento morto fica para decisão do pesquisador.
3. Valores do `.env` do Pi: a tarefa 0.2 os captura do processo real; se divergirem do perfil `pi5` (provável em `MAX_CONCURRENT_AGENTS` e `MAX_SUBTASKS_PER_TASK`, por causa do `.env.example`), o pesquisador confirma quais declarar.
