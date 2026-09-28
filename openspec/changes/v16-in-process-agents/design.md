# Design: Agentes em Processo no Host

## Estado atual (levantamento)

- `Orchestrator._execute_agent`: cria sessão → socket IPC → `runner.spawn(...)` com
  `env_vars` (`TASK_NAME`, `LLM_MODEL`, `OLLAMA_ENABLE_THINKING`, `SESSION_MODE`) → aguarda
  conexão → envia prompt → recebe resposta com `_telemetry` → cleanup.
- Dentro do container, `agents/runner.py::run_ipc_loop` recebe a tarefa e chama
  `src/llm/agent_loop.py::run_agent_loop(prompt, instruction, tools, ...)`.
- Agentes e ferramentas leem estado **por tarefa** de `os.environ`: `SESSION_ID`,
  `AGENT_ID`, `SESSION_MODE`, `OUTPUT_BASE_DIR`, `AGENT_MODEL`
  (`agents/base/agent.py`, `agents/base/tools.py`, `agents/developer/agent.py`).
- `run_agent_loop` usa `get_provider()` global — não o provedor do papel.
- `write_artifact` escreve em `/outputs/artifacts/` (caminho do container).
- `agents/researcher/tools.py::search` executa o binário `gemini` como subprocesso.
- `agents/base/agent.py` instrui `import subprocess; subprocess.run(['pip', ...])`, enquanto
  `src/skills/code/skill.py` bloqueia `subprocess.` por padrão — instruções conflitantes.

## Decisões

### 1. Contexto por tarefa em `contextvars`

Em um único processo, várias tarefas rodam em paralelo; variáveis de ambiente são globais e
não podem carregar estado por tarefa.

```python
# src/agent_runtime/context.py
@dataclass(frozen=True)
class AgentContext:
    session_id: str          # sessão mestra
    agent_session_id: str    # sessão do agente
    agent_id: str            # papel: researcher | developer | summarizer | reviewer | curator...
    task_name: str
    mode: str                # SessionMode
    output_dir: Path         # outputs/<session_id>/ (absoluto, resolvido)
    model: str
    enable_thinking: bool

current_context: ContextVar[AgentContext]
def get_agent_context() -> AgentContext   # levanta erro se chamado fora de uma tarefa
```

Toda leitura de `os.environ` por tarefa nos módulos listados acima é substituída por
`get_agent_context()`. Configurações globais (`SKILL_*_ENABLED`) continuam em `src/config.py`.

### 2. Runtime

```python
# src/agent_runtime/runtime.py
class AgentRuntime:
    async def run(self, task: AgentTask, ctx: AgentContext) -> AgentResult
```

- Resolve a definição do agente por papel em um registro (`AGENT_DEFINITIONS`: papel →
  instrução, ferramentas, callbacks), substituindo `AGENT_REGISTRY` (papel → imagem).
- Obtém o provedor via `ModelRouter.get_provider(role)`; `run_agent_loop` passa a receber o
  provedor como parâmetro (sem `get_provider()` global).
- Executa dentro de `copy_context().run` / `asyncio.create_task` com `current_context` setado.
- **Supervisão:** `asyncio.wait_for(..., AGENT_TIMEOUT_SECONDS)`; qualquer exceção vira
  `AgentResult(status="error", error=...)`; `asyncio.CancelledError` é propagada somente para
  cancelamento da sessão. Uma falha nunca derruba o orquestrador.
- Concorrência: o semáforo `MAX_LOCAL_LLM_CONCURRENT` existente continua limitando execuções
  simultâneas.
- Telemetria: gravada diretamente pelo singleton do host (o canal `_telemetry` do IPC deixa
  de ser necessário).

### 3. `ask_researcher` sem IPC

A skill `human_feedback` recebe, via `AgentContext`, um callback
`ask_researcher(question) -> str` ligado a `Orchestrator._handle_ask_researcher` (que já faz
deduplicação e registro). O comportamento visível ao pesquisador não muda.

### 4. Salvaguardas das ferramentas no host

| Ferramenta | Regra |
|---|---|
| `write_artifact` | Grava apenas dentro de `ctx.output_dir / "artifacts"`; nome normalizado; caminho resolvido (`Path.resolve`) deve ser descendente do diretório; symlinks recusados. |
| Leitura de arquivos pelas skills | Mesma regra de confinamento ao diretório da sessão e ao `input_snapshot/`. |
| `web_reader` e buscas | Resolve o host antes de conectar e **recusa** IPs de loopback, privados (RFC 1918), link-local e metadados de nuvem (`169.254.169.254`); apenas `http`/`https`; limite de tamanho de resposta. |
| Skill de código | Único caminho de execução de código; continua no sandbox; pacotes via parâmetro `packages`. |
| Memória / bancos | Apenas funções do projeto com consultas parametrizadas. |
| Qualquer ferramenta | Nenhuma aceita código, comando de shell, SQL ou Cypher arbitrário vindo do LLM. |

A busca do Researcher passa a usar `src/skills/search_quick` (DDG/Brave já existentes), sem
subprocesso nem dependência de fornecedor.

### 5. Fases

- **Fase 1:** runtime em processo atrás de `AGENT_RUNTIME=inprocess|container` (default
  `inprocess`), permitindo voltar ao modo container durante a validação no Pi 5.
- **Fase 2 (após validação e aprovação):** remover o modo container de agentes, `src/ipc.py`,
  `agents/runner.py`, `SessionContainerRunner`, construção de imagens de agente em
  `ContainerRunner._ensure_images`, e ajustar `docker-compose.yml`/Dockerfiles. O
  `ContainerRunner` fica restrito à infraestrutura (Postgres/Qdrant) e o sandbox mantém seu
  próprio cliente Docker.

### 6. Circuit breakers

- `MAX_AGENT_RUNS_PER_SESSION` (novo, default = valor atual de `MAX_CONTAINERS_PER_SESSION`)
  limita execuções de agentes.
- `MAX_CONTAINERS_PER_SESSION` passa a contar apenas containers de sandbox.
- A unificação com limites de parada é da mudança `v18-usage-limits`.

## Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | `_execute_agent` reescrito; DAG, retries e revisão inalterados. |
| Agentes & Prompts | Contexto por `contextvars`; prompt base sem `subprocess`; Researcher sem Gemini CLI. |
| Sandboxes & Containers | Sandbox inalterado; containers de agente removidos na fase 2. |
| Persistência | Nenhuma migração. |
| Segurança | Maior superfície no host; mitigada pelas salvaguardas do §4 e revisão do Analista de Segurança. |
| Testes & Telemetria | Testes de isolamento entre tarefas concorrentes; telemetria direta. |

## Riscos

- **Vazamento de contexto entre tarefas concorrentes** — mitigação: teste com duas tarefas
  simultâneas gravando em sessões diferentes.
- **Bloqueio do event loop** por código síncrono pesado em ferramentas (ex.: extração de PDF) —
  mitigação: `asyncio.to_thread` nas ferramentas CPU-bound.
- **Parsing de arquivos não confiáveis no host** (PDF/DOCX pelo `document_processor`) — é
  código de biblioteca, não gerado, mas o Analista de Segurança deve avaliar mover a extração
  para o sandbox.
