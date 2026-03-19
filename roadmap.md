# Roadmap de Desenvolvimento — GeminiClaw

Etapas e tarefas para construir o framework de orquestração de agentes.
Cada etapa é autossuficiente e pode ser delegada a um agente autônomo separado.
A ordem das etapas deve ser respeitada — cada uma depende da anterior.

---

## Etapa 0 — Scaffolding

Objetivo: repositório pronto para receber código.

- [x] Criar repositório Git e estrutura de diretórios (`src/`, `agents/`, `containers/`, `tests/`, `store/`, `logs/`, `.agents/rules/`)
- [x] Criar `pyproject.toml` com dependências de produção e grupo `dev`
- [x] Executar `uv sync --all-groups` e versionar o `uv.lock`
- [x] Criar `.env.example` com todas as variáveis necessárias
- [x] Criar `.gitignore` cobrindo `.env`, `*.db`, `logs/`, `.venv/`, `__pycache__/`
- [x] Adicionar `AGENTS.md`, `GEMINI.md` e arquivos em `.agents/rules/`
- [x] Criar `Dockerfile` base (`python:3.11-slim`) para containers de agente
- [x] Criar rede Docker isolada: `docker network create geminiclaw-net`
- [x] Commit: `chore: milestone/scaffolding`

---

## Etapa 1 — Logger

Objetivo: sistema de log JSON estruturado disponível para todos os módulos.

- [x] Implementar `JsonFormatter` em `src/logger.py`
- [x] Implementar `get_logger(name)` retornando logger configurado
- [x] Garantir que o logger não duplica handlers em chamadas repetidas
- [x] Escrever testes unitários cobrindo formatação JSON e campos obrigatórios (`timestamp`, `level`, `event`)
- [x] Commit: `feat(logger): implementa logger JSON estruturado`

---

## Etapa 2 — Configuração de ambiente

Objetivo: carregar e validar variáveis de ambiente de forma centralizada.

- [x] Implementar `src/config.py` que carrega o `.env` via `python-dotenv`
- [x] Definir e documentar todas as variáveis obrigatórias e opcionais
- [x] Lançar erro descritivo na inicialização se variável obrigatória estiver ausente
- [x] Expor constantes tipadas (`DEFAULT_MODEL`, `AGENT_TIMEOUT_SECONDS`, etc.)
- [x] Escrever testes unitários para variáveis ausentes, inválidas e com valores padrão
- [x] Commit: `feat(config): implementa carregamento e validação de variáveis de ambiente`

---

## Etapa 3 — Gerenciamento de sessões (SQLite)

Objetivo: persistir e recuperar o estado das sessões de agentes.

- [x] Implementar `init_db(path)` em `src/session.py` com PRAGMAs otimizados (`WAL`, `NORMAL`, cache de 32MB)
- [x] Criar schema da tabela `agent_sessions` com campos: `id`, `agent_id`, `status`, `created_at`, `updated_at`, `payload`
- [x] Implementar `SessionManager` com métodos:
  - [x] `create(agent_id)` → `Session`
  - [x] `get(session_id)` → `Session | None`
  - [x] `update(session_id, payload)` → `Session`
  - [x] `close(session_id)` → `None`
  - [x] `list_active()` → `list[Session]`
- [x] Adicionar índice em `agent_id` para queries frequentes
- [x] Escrever testes unitários com SQLite em memória cobrindo todos os métodos
- [x] Escrever teste de concorrência (múltiplas escritas simultâneas)
- [x] Commit: `feat(session): implementa SessionManager com SQLite`

---

## Etapa 4 — Container runner

Objetivo: spawnar, monitorar e destruir containers Docker de agentes.

- [ ] Implementar `src/runner.py` com as funções:
  - [ ] `spawn(agent_id, image, config)` → `ContainerHandle`
  - [ ] `stop(container_id)` → `None`
  - [ ] `cleanup_all()` → `None` (destrói todos os containers do projeto)
- [ ] Aplicar limites de recursos em todo `containers.run()`: `mem_limit="512m"`, `nano_cpus=1_000_000_000`, `network="geminiclaw-net"`, `user="appuser"`, `remove=True`
- [ ] Implementar `asyncio.Semaphore(3)` para limitar agentes simultâneos
- [ ] Implementar tratamento de timeout: container que exceder `AGENT_TIMEOUT_SECONDS` é encerrado automaticamente
- [ ] Escrever testes unitários com mock do `docker-py`
- [ ] Escrever teste de integração do ciclo de vida completo (spawn → execução → remoção)
- [ ] Escrever teste de integração para o limite de concorrência
- [ ] Commit: `feat(runner): implementa container runner com controle de concorrência`

---

## Etapa 5 — IPC (comunicação host ↔ container)

Objetivo: canal de mensagens confiável entre o orquestrador e os agentes nos containers.

- [ ] Definir o protocolo de mensagens em JSON: campos `type`, `session_id`, `payload`, `timestamp`
- [ ] Implementar `src/ipc.py` com:
  - [ ] `send(container_id, message)` → `None`
  - [ ] `receive(container_id, timeout)` → `Message`
  - [ ] Serialização e desserialização de `Message`
- [ ] Escolher e documentar o mecanismo de transporte (socket Unix ou pipe)
- [ ] Implementar reconexão automática em caso de falha de transporte
- [ ] Escrever testes unitários do protocolo de mensagens
- [ ] Escrever teste de integração de round-trip: host envia → container recebe → container responde → host recebe
- [ ] Commit: `feat(ipc): implementa canal de comunicação host-container`

---

## Etapa 6 — Agente base (ADK)

Objetivo: agente mínimo funcional que pode ser instanciado e executado em um container.

- [ ] Implementar `agents/base/agent.py` com `root_agent` usando Google ADK
- [ ] Definir `name`, `model`, `description` e `instruction` obrigatórios
- [ ] Integrar o agente ao `SessionManager` (carrega contexto da sessão ao iniciar)
- [ ] Integrar o agente ao logger estruturado
- [ ] Construir imagem Docker do agente base e validar que sobe sem erros
- [ ] Escrever teste unitário verificando atributos obrigatórios do agente
- [ ] Escrever smoke test com mock do Gemini validando resposta não-vazia
- [ ] Commit: `feat(agents): implementa agente base ADK com integração de sessão`

---

## Etapa 7 — Orquestrador principal

Objetivo: ponto de entrada que recebe uma solicitação do usuário, decide quantos agentes spawnar e coordena a execução.

- [ ] Implementar `src/orchestrator.py` com:
  - [ ] `handle_request(prompt)` → `OrchestratorResult`
  - [ ] Lógica de decisão: quantos agentes, qual imagem, qual contexto
  - [ ] Ciclo: cria sessão → spawna containers → envia mensagens via IPC → aguarda respostas → fecha sessões → retorna resultado
- [ ] Implementar tratamento de falha parcial: se um agente falhar, os demais continuam
- [ ] Expor resultado consolidado com respostas de todos os agentes e status de cada um
- [ ] Escrever testes unitários com mocks do runner e do IPC
- [ ] Escrever teste de integração do fluxo completo com um único agente
- [ ] Commit: `feat(runner): implementa orquestrador principal`

---

## Etapa 8 — Agente researcher

Objetivo: primeiro agente especializado, capaz de buscar e sintetizar informações.

- [ ] Criar `agents/researcher/agent.py` estendendo o agente base
- [ ] Definir instrução especializada de pesquisa em português
- [ ] Implementar ferramenta `search(query)` usando Gemini CLI como subprocesso
- [ ] Implementar cache de resultados de busca com TTL configurável (padrão: 1 hora)
- [ ] Registrar o researcher no orquestrador como tipo de agente disponível
- [ ] Escrever testes unitários da ferramenta de busca com mock
- [ ] Escrever teste de integração do researcher dentro de um container
- [ ] Escrever smoke test E2E com API real
- [ ] Commit: `feat(agents): implementa agente researcher com cache de busca`

---

## Etapa 9 — Interface de entrada

Objetivo: ponto de entrada para o usuário interagir com o framework.

- [ ] Implementar `src/cli.py` com interface de linha de comando simples
- [ ] Aceitar prompt do usuário via argumento ou modo interativo (`input()`)
- [ ] Exibir resultado formatado no terminal
- [ ] Exibir status de cada agente durante a execução (aguardando, executando, concluído, erro)
- [ ] Implementar sinal de interrupção (`Ctrl+C`) que encerra containers abertos de forma limpa
- [ ] Escrever testes unitários do parsing de argumentos
- [ ] Commit: `feat(cli): implementa interface de linha de comando`

---

## Etapa 10 — Validação no Raspberry Pi 5

Objetivo: garantir que o framework funciona no hardware alvo.

- [ ] Clonar o repositório no Pi 5 e executar `uv sync --all-groups`
- [ ] Construir a imagem Docker no Pi (`docker build`) e validar para ARM64
- [ ] Rodar a suite de testes completa: `uv run pytest -m "unit or integration" -v`
- [ ] Executar o smoke test E2E com API real no hardware
- [ ] Monitorar temperatura durante execução paralela de 3 agentes
- [ ] Monitorar uso de memória por container (`docker stats`)
- [ ] Documentar ajustes necessários no `SETUP.md`
- [ ] Configurar e validar o serviço systemd
- [ ] Commit: `chore: milestone/v1.0.0 — framework validado no Raspberry Pi 5`

---

## Dependências entre etapas

```
0 (scaffolding)
└── 1 (logger)
    └── 2 (config)
        ├── 3 (session)
        │   └── 6 (agente base)
        │       └── 8 (researcher)
        └── 4 (runner)
            └── 5 (ipc)
                └── 7 (orquestrador)
                    ├── 8 (researcher)
                    └── 9 (cli)
                        └── 10 (validação Pi 5)
```