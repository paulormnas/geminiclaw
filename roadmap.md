# Roadmap de Desenvolvimento — GeminiClaw

Etapas e tarefas para construir o framework de orquestração de agentes.
Cada etapa é autossuficiente e pode ser delegada a um agente autônomo separado.
A ordem das etapas deve ser respeitada — cada uma depende da anterior.

---

## Etapa 0 — Scaffolding

Objetivo: repositório pronto para receber código.

- [x] Criar repositório Git e estrutura de diretórios:
  - `src/`, `agents/`, `containers/`, `tests/`
  - `store/` — banco SQLite e estado interno do framework
  - `outputs/` — todos os artefatos produzidos pelos agentes (código, documentos, imagens, modelos, etc.)
  - `logs/`, `.agents/rules/`
- [x] Criar `pyproject.toml` com dependências de produção e grupo `dev`
- [x] Executar `uv sync --all-groups` e versionar o `uv.lock`
- [x] Criar `.env.example` com todas as variáveis necessárias
- [x] Criar `.gitignore` cobrindo `.env`, `store/*.db`, `logs/`, `.venv/`, `__pycache__/`, `outputs/`
- [x] Criar `Dockerfile` base (`python:3.11-slim`) para containers de agente
- [x] Criar rede Docker isolada: `docker network create geminiclaw-net`
- [x] Commit: `chore: milestone/scaffolding`

---

## Etapa 1 — Convenção de outputs

Objetivo: estabelecer onde e como todos os agentes devem gravar seus resultados.
Esta etapa define a única fonte de verdade para artefatos produzidos —
nenhum agente deve gravar resultados fora desta convenção.

### Estrutura de diretórios

```
outputs/
└── <session_id>/          # Uma pasta por sessão do orquestrador
    └── <task_name>/       # Uma subpasta por tarefa do plano
        ├── *.py           # Código gerado
        ├── *.md           # Documentos e relatórios
        ├── *.json         # Dados estruturados
        ├── *.png / *.svg  # Imagens e gráficos
        ├── *.pkl          # Modelos serializados
        └── *.csv          # Dados tabulares
```

### Tarefas

- [x] Implementar `src/output_manager.py` com:
  - [x] `init_session(session_id)` → cria `outputs/<session_id>/` e retorna o caminho base
  - [x] `get_task_dir(session_id, task_name)` → cria e retorna `outputs/<session_id>/<task_name>/`
  - [x] `list_artifacts(session_id)` → retorna todos os arquivos da sessão com tipo e tamanho
  - [x] `cleanup_session(session_id)` → remove a pasta da sessão (usado em testes)
- [x] Adicionar `OUTPUT_BASE_DIR=./outputs` ao `.env.example`
- [x] Montar `outputs/<session_id>/` como volume no container do agente executor (`/outputs` dentro do container)
  - [x] Todo artefato produzido por um agente **deve** ser gravado em `/outputs/<task_name>/` dentro do container
  - [x] Gravar resultados fora deste caminho é um erro de comportamento do agente
- [x] Escrever testes unitários de `OutputManager` com sistema de arquivos temporário (`tmp_path` do pytest)
- [x] Commit: `feat(output): implementa convenção e gerenciamento de diretório de outputs`

---

## Etapa 2 — Logger

Objetivo: sistema de log JSON estruturado disponível para todos os módulos.

- [x] Implementar `JsonFormatter` em `src/logger.py`
- [x] Implementar `get_logger(name)` retornando logger configurado
- [x] Garantir que o logger não duplica handlers em chamadas repetidas
- [x] Escrever testes unitários cobrindo formatação JSON e campos obrigatórios (`timestamp`, `level`, `event`)
- [x] Commit: `feat(logger): implementa logger JSON estruturado`

---

## Etapa 3 — Configuração de ambiente

Objetivo: carregar e validar variáveis de ambiente de forma centralizada.

- [x] Implementar `src/config.py` que carrega o `.env` via `python-dotenv`
- [x] Definir e documentar todas as variáveis obrigatórias e opcionais, incluindo `OUTPUT_BASE_DIR`
- [x] Lançar erro descritivo na inicialização se variável obrigatória estiver ausente
- [x] Expor constantes tipadas (`DEFAULT_MODEL`, `AGENT_TIMEOUT_SECONDS`, `OUTPUT_BASE_DIR`, etc.)
- [x] Escrever testes unitários para variáveis ausentes, inválidas e com valores padrão
- [x] Commit: `feat(config): implementa carregamento e validação de variáveis de ambiente`

---

## Etapa 4 — Gerenciamento de sessões (SQLite)

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

## Etapa 5 — Container runner

Objetivo: spawnar, monitorar e destruir containers Docker de agentes.

- [x] Implementar `src/runner.py` com as funções:
  - [x] `spawn(agent_id, image, config)` → `ContainerHandle`
  - [x] `stop(container_id)` → `None`
  - [x] `cleanup_all()` → `None` (destrói todos os containers do projeto)
- [ ] Montar `outputs/<session_id>/` como volume no container (`/outputs`) em todo `containers.run()`
- [x] Aplicar limites de recursos em todo `containers.run()`: `mem_limit="512m"`, `nano_cpus=1_000_000_000`, `network="geminiclaw-net"`, `user="appuser"`, `remove=True`
- [x] Implementar `asyncio.Semaphore(3)` para limitar agentes simultâneos
- [x] Implementar tratamento de timeout: container que exceder `AGENT_TIMEOUT_SECONDS` é encerrado automaticamente
- [x] Escrever testes unitários com mock do `docker-py`
- [ ] Escrever teste de integração do ciclo de vida completo (spawn → execução → remoção)
- [ ] Escrever teste de integração para o limite de concorrência
- [ ] Commit: `feat(runner): implementa container runner com controle de concorrência`

---

## Etapa 6 — IPC (comunicação host ↔ container)

Objetivo: canal de mensagens confiável entre o orquestrador e os agentes nos containers.

- [x] Definir o protocolo de mensagens em JSON: campos `type`, `session_id`, `payload`, `timestamp`
- [x] Implementar `src/ipc.py` com:
  - [x] `send(container_id, message)` → `None`
  - [x] `receive(container_id, timeout)` → `Message`
  - [x] Serialização e desserialização de `Message`
- [x] Escolher e documentar o mecanismo de transporte (socket Unix ou pipe)
- [x] Implementar reconexão automática em caso de falha de transporte
- [x] Escrever testes unitários do protocolo de mensagens
- [x] Escrever teste de integração de round-trip: host envia → container recebe → container responde → host recebe
- [x] Commit: `feat(ipc): implementa canal de comunicação host-container`

---

## Etapa 7 — Agente base (ADK)

Objetivo: agente mínimo funcional que pode ser instanciado e executado em um container.

- [x] Implementar `agents/base/agent.py` com `root_agent` usando Google ADK
- [x] Definir `name`, `model`, `description` e `instruction` obrigatórios
- [ ] A instrução do agente base deve incluir explicitamente: *"Todos os artefatos que você produzir devem ser salvos em `/outputs/<task_name>/` dentro do container."*
- [x] Integrar o agente ao `SessionManager` (carrega contexto da sessão ao iniciar)
- [x] Integrar o agente ao logger estruturado
- [x] Construir imagem Docker do agente base e validar que sobe sem erros
- [x] Escrever teste unitário verificando atributos obrigatórios do agente
- [x] Escrever smoke test com mock do Gemini validando resposta não-vazia
- [x] Commit: `feat(agents): implementa agente base ADK com integração de sessão`

---

## Etapa 8 — Orquestrador principal

Objetivo: ponto de entrada que recebe uma solicitação do usuário, decide quantos agentes spawnar e coordena a execução.

- [x] Implementar `src/orchestrator.py` com:
  - [x] `handle_request(prompt)` → `OrchestratorResult`
  - [x] Lógica de decisão: quantos agentes, qual imagem, qual contexto
  - [x] Ciclo: cria sessão → inicializa `OutputManager` para a sessão → spawna containers com volume montado → envia mensagens via IPC → aguarda respostas → lista artefatos via `OutputManager` → fecha sessões → retorna resultado
- [x] Implementar tratamento de falha parcial: se um agente falhar, os demais continuam
- [x] Expor resultado consolidado com respostas de todos os agentes, status de cada um e lista de artefatos produzidos em `outputs/<session_id>/`
- [x] Escrever testes unitários com mocks do runner, IPC e OutputManager
- [x] Escrever teste de integração do fluxo completo com um único agente
- [x] Commit: `feat(orchestrator): implementa orquestrador principal`

---

## Etapa 9 — Raciocínio e planejamento entre agentes

Objetivo: antes de executar qualquer tarefa, o agente planejador decompõe o problema em passos e submete o plano a um agente validador. Apenas planos aprovados são enviados ao orquestrador para execução.

- [ ] Implementar `agents/planner/agent.py` com instrução especializada em decompor problemas em etapas ordenadas e executáveis
- [ ] O Planner deve incluir em cada tarefa do plano: nome, responsável e artefatos esperados em `/outputs/<task_name>/`
- [ ] Implementar `agents/validator/agent.py` com instrução especializada em revisar planos: identificar etapas ambíguas, dependências faltantes, abordagens inviáveis ou tarefas que não especificam onde salvar seus artefatos
- [ ] Definir o protocolo de revisão em `src/ipc.py`:
  - [ ] Planner envia plano ao Validator via IPC
  - [ ] Validator retorna `approved`, `rejected` ou `revision_needed` com justificativa
  - [ ] Se `revision_needed`, o Planner revisa e resubmete (máximo de 3 iterações)
  - [ ] Se `rejected` após 3 tentativas, o orquestrador é notificado e interrompe a tarefa
- [ ] Integrar o ciclo planner → validator no `src/orchestrator.py` como etapa obrigatória antes do dispatch de agentes executores
- [ ] Garantir que o plano aprovado é persistido na sessão SQLite antes da execução
- [ ] Implementar log estruturado de cada iteração do ciclo de revisão
- [ ] Escrever testes unitários do protocolo de revisão com mocks do planner e do validator
- [ ] Escrever teste de integração do ciclo completo: planner → validator → aprovação → dispatch
- [ ] Escrever teste do fluxo de rejeição: 3 iterações sem aprovação → orquestrador notificado
- [ ] Commit: `feat(agents): implementa ciclo de raciocínio e validação de planos entre agentes`

---

## Etapa 10 — Agente researcher

Objetivo: primeiro agente especializado, capaz de buscar e sintetizar informações.

- [x] Criar `agents/researcher/agent.py` estendendo o agente base
- [x] Definir instrução especializada de pesquisa em português
- [x] Implementar ferramenta `search(query)` usando Gemini CLI como subprocesso
- [x] Implementar cache de resultados de busca com TTL configurável (padrão: 1 hora)
- [ ] Salvar resultados de pesquisa em `/outputs/<task_name>/research.md` dentro do container
- [x] Registrar o researcher no orquestrador como tipo de agente disponível
- [x] Escrever testes unitários da ferramenta de busca com mock
- [x] Escrever teste de integração do researcher dentro de um container
- [x] Escrever smoke test E2E com API real
- [x] Commit: `feat(agents): implementa agente researcher com cache de busca`

---

## Etapa 11 — Interface de entrada

Objetivo: ponto de entrada para o usuário interagir com o framework.

- [x] Implementar `src/cli.py` com interface de linha de comando simples
- [x] Aceitar prompt do usuário via argumento ou modo interativo (`input()`)
- [x] Exibir resultado formatado no terminal
- [x] Exibir status de cada agente durante a execução (aguardando, executando, concluído, erro)
- [x] Ao final de cada execução, listar os artefatos gerados com seus caminhos em `outputs/<session_id>/`
- [x] Implementar sinal de interrupção (`Ctrl+C`) que encerra containers abertos de forma limpa
- [x] Escrever testes unitários do parsing de argumentos
- [x] Commit: `feat(cli): implementa interface de linha de comando`

---

## Etapa 12 — Validação no Raspberry Pi 5

Objetivo: garantir que o framework funciona no hardware alvo.

- [ ] Clonar o repositório no Pi 5 e executar `uv sync --all-groups`
- [ ] Construir a imagem Docker no Pi (`docker build`) e validar para ARM64
- [ ] Rodar a suite de testes completa: `uv run pytest -m "unit or integration" -v`
- [ ] Executar o smoke test E2E com API real no hardware
- [ ] Monitorar temperatura durante execução paralela de 3 agentes
- [ ] Monitorar uso de memória por container (`docker stats`)
- [ ] Verificar que artefatos aparecem corretamente em `outputs/<session_id>/` após execução
- [ ] Documentar ajustes necessários no `SETUP.md`
- [ ] Configurar e validar o serviço systemd
- [ ] Commit: `chore: milestone/v1.0.0 — framework validado no Raspberry Pi 5`

---

## Etapa 13 — Documentação de arquitetura

Objetivo: registrar no `README.md` como o sistema funciona, como os agentes se comunicam e como a arquitetura evoluiu ao longo do desenvolvimento.

- [x] Criar `README.md` na raiz com as seções:
  - [x] **Visão geral** — o que é o GeminiClaw e qual problema resolve
  - [x] **Arquitetura** — diagrama em texto (`src/`, `agents/`, containers, SQLite, IPC, `outputs/`) e descrição de cada componente
  - [x] **Convenção de outputs** — onde os agentes gravam resultados e como acessá-los após uma sessão
  - [x] **Fluxo de execução** — do prompt do usuário até a resposta consolidada, passando pelo ciclo planner → validator → orquestrador → agentes executores
  - [x] **Agentes disponíveis** — tabela com nome, responsabilidade e quando é ativado
  - [x] **Comunicação entre agentes** — protocolo IPC, campos de mensagem e fluxo de aprovação de planos
  - [x] **Como rodar** — comandos mínimos para subir o projeto localmente e no Pi 5
  - [x] **Como adicionar um novo agente** — passo a passo para estender o framework
- [x] Atualizar o `README.md` sempre que uma das seguintes mudanças ocorrer:
- [x] Revisar `AGENTS.md` e `GEMINI.md` para garantir consistência com o README
- [x] Commit: `docs: adiciona README.md com arquitetura e fluxo de comunicação entre agentes`

---

## Dependências entre etapas

```
0 (scaffolding)
└── 1 (outputs)
    └── 2 (logger)
        └── 3 (config)
            ├── 4 (session)
            │   └── 7 (agente base)
            │       └── 10 (researcher)
            └── 5 (runner)
                └── 6 (ipc)
                    └── 8 (orquestrador)
                        └── 9 (planner + validator)
                            ├── 10 (researcher)
                            └── 11 (cli)
                                └── 12 (validação Pi 5)
                                    └── 13 (documentação README)
```