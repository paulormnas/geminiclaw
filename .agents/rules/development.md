---
trigger: always_on
---

# Regras de Desenvolvimento — GeminiClaw

Stack: Python 3.11+, Google ADK, Docker, uv.
Nenhum arquivo `.js`, `.ts` ou `.mjs` deve existir neste projeto.

---

## Princípios arquiteturais

1. **100% Python** — o Node.js existe apenas como runtime do Gemini CLI (ferramenta), não do projeto.
2. **Footprint mínimo** — cada dependência nova deve ser justificada. Prefira a stdlib.
3. **Single-process por agente** — cada agente roda em seu próprio container Docker. Estado compartilhado apenas via SQLite.
4. **Idempotência** — qualquer script de setup deve poder ser re-executado sem efeitos colaterais.
5. **Sem magia implícita** — configuração via `.env` e `GEMINI.md` explícitos. Nada de detecção automática de ambiente que possa silenciar erros.
6. **Logs antes de tudo** — toda operação com efeito colateral (chamada de API, escrita em disco, spawn de container) deve ser logada em JSON **antes** de ser executada.

---

## Gerenciamento de pacotes — sempre uv, nunca pip

```bash
# Criar ambiente virtual
uv venv .venv

# Ativar
source .venv/bin/activate

# Instalar todas as dependências (produção + dev)
uv sync --all-groups

# Adicionar dependência de produção
uv add nome-do-pacote

# Adicionar dependência de desenvolvimento
uv add --dev nome-do-pacote

# Atualizar dependências
uv sync --upgrade

# Rodar script ou ferramenta dentro do ambiente
uv run pytest
uv run adk web
uv run python src/runner.py
```

> `pip install` é proibido neste projeto. Sempre use `uv add` ou `uv sync`.
> O `uv.lock` deve ser versionado junto com o projeto — ele garante reprodutibilidade entre máquina local e Raspberry Pi.

---

## Convenções de código Python

### Type hints — obrigatórios em funções públicas

```python
# ✅ Correto
def spawn_agent(config: AgentConfig) -> AgentHandle: ...
async def get_session(session_id: str) -> Session | None: ...

# ❌ Errado
def spawn_agent(config): ...
```

### Docstrings — formato Google Style

```python
def create_session(agent_id: str, timeout: int = 120) -> Session:
    """Cria uma nova sessão para o agente especificado.

    Args:
        agent_id: Identificador único do agente.
        timeout: Tempo máximo de inatividade em segundos.

    Returns:
        Objeto Session com ID gerado e timestamp de criação.

    Raises:
        ValueError: Se agent_id for vazio ou None.
    """
```

### Logger estruturado — nunca `print()`

```python
# ✅ Correto
from src.logger import get_logger
logger = get_logger(__name__)
logger.info("Container iniciado", extra={"extra": {"container_id": cid}})

# ❌ Errado
print(f"Container {cid} iniciado")
```

### Async/await — para todas as operações de I/O

```python
# ✅ Correto
async def run_agent(agent_id: str) -> AgentResult:
    session = await session_manager.get_or_create(agent_id)
    container = await container_runner.spawn(agent_id)
    return await container.wait_for_result()

# ❌ Errado — bloqueia a event loop
def run_agent(agent_id: str) -> AgentResult:
    time.sleep(5)
```

### Errors como valores quando possível

```python
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass
class Ok(Generic[T]):
    value: T

@dataclass
class Err:
    message: str

Result = Ok[T] | Err
```

---

## Nomeação

| Tipo | Convenção | Exemplo |
|---|---|---|
| Módulo Python | `snake_case.py` | `container_runner.py` |
| Classe | `PascalCase` | `SessionManager` |
| Função/método | `snake_case` | `spawn_agent()` |
| Constante | `SCREAMING_SNAKE_CASE` | `MAX_AGENT_TIMEOUT` |
| Variável de ambiente | `SCREAMING_SNAKE_CASE` | `AGENT_TIMEOUT_SECONDS` |
| Tabela SQLite | `snake_case` | `agent_sessions` |
| Pasta de agente ADK | `snake_case/` | `agents/web_researcher/` |

---

## Containers Docker

- **Imagem base:** `python:3.11-slim`
- **Usuário:** sempre non-root (`USER appuser`)
- **Memória:** `mem_limit="512m"` em todo `containers.run()`
- **Rede:** rede interna isolada (`network="geminiclaw-net"`)
- **Volumes:** apenas o diretório de dados do agente (`/data`)
- **Cleanup:** `remove=True` em toda execução

```python
# ✅ Padrão obrigatório
container = client.containers.run(
    image="geminiclaw-agent:latest",
    mem_limit="512m",
    nano_cpus=1_000_000_000,
    network="geminiclaw-net",
    volumes={str(data_dir): {"bind": "/data", "mode": "rw"}},
    detach=True,
    remove=True,
    user="appuser",
)
```

---

## Performance (ARM64 / Pi 5)

- Temperatura > 75°C: pause benchmarks antes de prosseguir (`vcgencmd measure_temp`)
- Cache de respostas do Gemini com TTL configurável (padrão: 1 hora)

---

## Segurança

- Nunca versione `.env`, `*.db` ou arquivos de log
- Variáveis sensíveis carregadas via `python-dotenv` apenas em runtime
- Portas de containers expostas apenas em `127.0.0.1`, nunca em `0.0.0.0`
- Subprocessos com input externo: use lista de argumentos, nunca `shell=True`

```python
# ✅ Correto
subprocess.run(["gemini", "--model", model_name], check=True)

# ❌ Errado
subprocess.run(f"gemini --model {model_name}", shell=True)
```

---

## Fluxo de desenvolvimento

```
1. Crie uma worktree: `git worktree add ../geminiclaw-<feature> -b <branch>`
2. Entre na pasta e ative o ambiente: `cd ../geminiclaw-<feature> && uv sync`
3. Escreva o teste antes do código (TDD quando possível)
4. Rode os testes: `uv run pytest`
5. Verifique containers: `docker stats`
6. Commit o código APENAS se todos os requisitos do desenvolvimento da tarefa forem atendidos.
7. Commit seguindo o `@.agents/workflows/commit.md`
```

### Mensagens de commit

```
feat: adiciona suporte a múltiplos agentes em paralelo
fix: corrige vazamento de memória no container runner
docs: atualiza SETUP.md com passos de swap
test: adiciona smoke test para o agente researcher
refactor: extrai lógica de IPC para módulo separado
chore: atualiza dependências no pyproject.toml
```

---

## O agente nunca deve

- Usar `pip install` em qualquer circunstância
- Criar arquivos `.js`, `.ts` ou `.mjs`
- Modificar `.env` sem instrução explícita do usuário
- Alterar `GEMINI.md` ou `AGENTS.md` sem instrução explícita
- Sempre use `AGENTS.md` ao invés de `GEMINI.md` para manter compatibilidade com outros projetos
- Usar `print()` no lugar do logger estruturado
- Usar `except Exception: pass` — todo erro deve ser logado ou propagado
- Usar `# type: ignore` sem comentário explicando o motivo
- Executar `docker rm -f` em recursos não relacionados ao projeto
- NÃO commitar com testes falhando. Primeiro eles devem ser resolvidos
- Implementar alterações diretamente na pasta raiz do repositório; sempre utilize `git worktree` para novas features ou correções

## O agente deve pedir confirmação antes de

- Deletar qualquer arquivo ou diretório
- Alterar o schema do banco de dados SQLite
- Modificar o `Dockerfile` base
- Atualizar versões major de dependências no `pyproject.toml`
- Executar comandos que afetam serviços systemd
- Qualquer operação irreversível

---

## Referências

- [uv — Docs](https://docs.astral.sh/uv/)
- [Google ADK Python](https://github.com/google/adk-python)
- [ADK Quickstart](https://google.github.io/adk-docs/get-started/quickstart/)
- [docker-py](https://docker-py.readthedocs.io/)
- [Gemini CLI](https://geminicli.com/docs)