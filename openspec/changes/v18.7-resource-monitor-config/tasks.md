# Tarefas: v18.7-resource-monitor-config

**Estado (2026-10-15):** não iniciada.

## 0. Pré-requisitos
- [ ] 0.1 Revisar esta mudança contra o código de `dev` (as referências de linha do design são de 2026-10-15).
- [ ] 0.2 Com o código atual (antes do merge) e com autorização do pesquisador para acessar o Pi, capturar os valores efetivos no Pi: `MAX_SUBTASKS_PER_TASK`, `MAX_CONCURRENT_AGENTS`, `AGENT_TIMEOUT_SECONDS`, prioridade de provedores resolvida, `PI_TEMPERATURE_LIMIT`, `PI_MIN_AVAILABLE_MEMORY_MB` (só nomes e valores não secretos; registrar no PR).

## 1. Dependência e monitor
- [ ] 1.0 Criar o auxiliar de teste compartilhado `FakePsutilBackend` em `tests/support/fake_psutil_backend.py`: backend injetável do `HealthMonitor` com memória, CPU e sensores de temperatura (`sensors_temperatures`) roteirizados por chamada, opção de plataforma sem o método e de leitura que levanta exceção. Reutilizado pelas mudanças V18.7 seguintes (`v18.7-background-sessions`).
- [ ] 1.1 `uv add psutil`; conferir `pyproject.toml` e `uv.lock`.
- [ ] 1.2 `src/health.py`: `HealthMonitor` sobre `psutil` com backend injetável; remover `PiHealthMonitor`, `subprocess`, `vcgencmd` e os valores fixos.
- [ ] 1.3 Testes (`tests/unit/test_health.py`, reescrito): memória lida; leitura que falha devolve `None`; plataforma sem `sensors_temperatures` devolve temperatura `None`; `TEMPERATURE_SENSOR` escolhe o sensor; sensor ausente devolve `None`; `is_throttled` derivado do limite e `None` sem limite ou sem leitura; nenhum subprocesso criado (monkeypatch de `subprocess.run` que falha o teste).

## 2. Consumidores
- [ ] 2.1 `src/agent_runtime/resources.py`: `HealthMonitor`; `MIN_AVAILABLE_MEMORY_MB`; `TEMPERATURE_LIMIT` opcional; aviso a partir de `TEMPERATURE_LIMIT - TEMPERATURE_WARNING_MARGIN_C`; remover `_DEFAULT_LIMIT`; sem leitura usa `MAX_CONCURRENT_AGENTS` com aviso.
- [ ] 2.2 Testes (`tests/unit/test_agent_runtime_resources.py`): espera por memória; temperatura ignorada sem limite; aviso derivado (limite 80, margem 5: aviso em 75, não em 74); limite sem leitura igual a `MAX_CONCURRENT_AGENTS` com `WARNING` no log.
- [ ] 2.3 `src/autonomous_loop.py:40`, `:125`: trocar a classe; snapshot grava `NULL` no que é desconhecido.
- [ ] 2.4 Teste: snapshot com temperatura desconhecida grava `cpu_temp_c=None` e `is_throttled=None`.
- [ ] 2.5 Aviso de proteção térmica desligada (requisito de segurança, design §4, item 1): na inicialização, no Linux com temperatura legível e `TEMPERATURE_LIMIT` não definido, um `WARNING` uma única vez por processo; o REPL mostra o aviso no cabeçalho; a inicialização não falha.
- [ ] 2.6 Testes (`tests/unit/test_thermal_warning.py`, com `FakePsutilBackend` e `env_override`): cenários "Aviso no Linux com sensor legível e sem limite" (um único aviso em duas inicializações) e "Sem aviso quando o limite está definido ou não há leitura" de `specs/agent-runtime`; cabeçalho do REPL com o aviso.

## 3. Configuração
- [ ] 3.0 Criar o auxiliar de teste compartilhado `env_override` em `tests/support/env_override.py`: gerenciador de contexto que define e remove variáveis de ambiente isoladas (inclusive sem ler o `.env` local), reimporta `src.config` com elas e restaura ambiente e módulo ao sair. Substitui os `importlib.reload(src.config)` avulsos dos testes tocados por esta mudança; reutilizado pelas mudanças V18.7 seguintes (`v18.7-exploration-limits`). Sem dependência nova.
- [ ] 3.1 `src/config.py`: remover o bloco `DEPLOYMENT_PROFILE` (`:134-153`) e `PI_*` (`:377-378`); declarar as variáveis do design §1.4; `AGENT_TIMEOUT_SECONDS=0` vira `None`; validação de valores inválidos.
- [ ] 3.2 `_REMOVED_VARIABLES` (mensagem fixa ou função do valor) e `check_removed_variables` com as mensagens do design §1.5, chamada na importação; interface estável para `v18.7-exploration-limits` acrescentar nomes.
- [ ] 3.3 Testes (`tests/unit/test_config_removed_names.py` e `tests/unit/test_config.py`): cada nome removido falha com a mensagem do nome novo; `DEPLOYMENT_PROFILE=default` pede só remover a linha; `pi5` lista os quatro valores; valor de outro nome não é ecoado; `AGENT_TIMEOUT_SECONDS=0` dá `None`; `-1` e `abc` falham; ajustar `tests/unit/test_config.py:22-24`, `:54`, `:107`.
- [ ] 3.4 `src/llm/availability.py`: `DEFAULT_PRIORITY`; `parse_priority(raw)`; `src/llm/session.py:256`, `:279`.
- [ ] 3.5 Testes (`tests/unit/llm/test_availability.py`): prioridade padrão sem perfil; `LLM_PROVIDER_PRIORITY` explícito vale; remover o caso `pi5` (`:208`).
- [ ] 3.6 `src/cli.py:139-144`: ajuda de `--timeout` mostra "sem limite" quando `AGENT_TIMEOUT_SECONDS` é `None`.

## 4. Documentação e ambiente
- [ ] 4.1 `.env.example`: remover `DEPLOYMENT_PROFILE` e `PI_*`; documentar as variáveis novas; corrigir os comentários das linhas 35 e 312.
- [ ] 4.2 `README.md:39` e `OLLAMA_PI5.md:38`: trocar `DEPLOYMENT_PROFILE=pi5` pelas variáveis explícitas.
- [ ] 4.3 Migrar o `.env` do Pi com os valores da tarefa 0.2, quando o pesquisador autorizar (só nomes no PR). `TEMPERATURE_LIMIT` é obrigatório nessa migração (design §4, item 1); esta tarefa bloqueia só a bateria no Pi, não o merge.

## 5. Validação final
- [ ] 5.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v` verde (com o `.env` local migrado).
- [ ] 5.2 Conferir que nenhum `vcgencmd`, `PiHealthMonitor`, `DEPLOYMENT_PROFILE` ou `PI_` restou em `src/` e `tests/` (`grep`).
- [ ] 5.3 Revisão nos 7 eixos; PR para `dev` citando esta mudança; atualizar a linha **Estado** deste arquivo.
