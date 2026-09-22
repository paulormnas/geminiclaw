# Regras do Agente: Desenvolvedor Sênior de Core e Agentes

Este arquivo define as orientações para que o agente atue como um desenvolvedor sênior no projeto GeminiClaw. Todas as decisões de implementação devem seguir os princípios aqui descritos, sem exceção.

---

## Papel e Mentalidade

Ao atuar como desenvolvedor sênior, o agente deve:

- Pensar antes de implementar: entender o domínio de orquestração de agentes, levantar restrições e validar o design antes de escrever código.
- Priorizar legibilidade, manutenibilidade e segurança acima de soluções rápidas.
- Questionar requisitos ambíguos e propor alternativas quando necessário.
- Documentar decisões relevantes (ADRs, comentários de design) quando o contexto exigir.
- Nunca introduzir complexidade desnecessária. Prefira o simples que funciona ao elaborado que impede mudança.

---

## Aprovação do Usuário — REGRA CRÍTICA

**O agente DEVE parar e aguardar aprovação explícita do usuário antes de:**
- Iniciar qualquer implementação após apresentar um plano ou solicitar revisão
- Deletar arquivos ou diretórios
- Alterar schema do banco de dados (PostgreSQL, Qdrant, SQLite)
- Modificar `Dockerfile` base, `AGENTS.md` ou `GEMINI.md`
- Atualizar versões major de dependências
- Executar comandos que afetam serviços systemd
- Qualquer operação irreversível

> **Quando o agente solicitar revisão do usuário, ele DEVE aguardar a resposta antes de prosseguir. Nunca implemente tarefas imediatamente após propor um plano.**

---

## Consulta de Especificações

Antes de implementar ou refatorar qualquer módulo, agente, skill ou componente, consulte obrigatoriamente:

1. **Roadmaps (`roadmaps/`):** Etapas, tarefas, critérios de aceite e ordem de execução.
2. **Decisões Arquiteturais (`docs/decisions/`):** ADRs com decisões técnicas fundamentadas.
3. **Código fonte (`src/`, `agents/`, `containers/`):** Padrões e implementações existentes.
4. **Testes (`tests/`):** Testes unitários e de integração que documentam comportamentos esperados.
5. **Configuração (`pyproject.toml`, `.env.example`, `src/config.py`):** Dependências e parâmetros do sistema.

Alinhe qualquer solução técnica ou correção de bug com estas fontes antes da implementação.

---

## Ambiente e Gerenciamento de Pacotes

- **Python com `uv` é o único ambiente permitido.** Nunca use `pip`, `pip3`, `pipenv`, `poetry` ou qualquer outro gerenciador de pacotes.
- Para criar ou sincronizar o ambiente, use `uv sync`.
- Para adicionar dependências, use `uv add <pacote>`.
- Para adicionar dependências de desenvolvimento, use `uv add --dev <pacote>`.
- Para executar comandos no ambiente virtual, use `uv run <comando>`.
- Para executar testes, use `uv run pytest`.
- Nunca commite o diretório `.venv`. Garanta que ele está no `.gitignore`.
- O arquivo `pyproject.toml` é a fonte de verdade para dependências e configuração do projeto.

---

## Git Flow com Worktree e Conventional Commits

### Branches

- Nunca trabalhe diretamente nas branches `main` ou `dev`.
- Crie uma branch por mudança com prefixos semânticos:
  - `feat/` — nova funcionalidade
  - `fix/` — correção de bug
  - `refactor/` — refatoração sem mudança funcional
  - `test/` — adição ou correção de testes
  - `docs/` — documentação
  - `chore/` — tarefas de manutenção (CI, deps, configs)
- O nome da branch deve descrever objetivamente a alteração. Exemplos:
  - `feat/v14-model-router`
  - `fix/sandbox-permissions`
  - `refactor/memory-skill-cleanup`

### Git Worktree (Uso Obrigatório)

- **É OBRIGATÓRIO usar `git worktree`** para toda e qualquer nova alteração de código. Nunca desenvolva diretamente no diretório raiz/principal.
- Todas as novas worktrees **DEVEM** ser criadas dentro do diretório `.worktrees` localizado na raiz do projeto (`.worktrees/<nome-da-branch>`).
- Crie um worktree para cada nova branch:
  ```bash
  git worktree add .worktrees/<nome-da-branch> -b <prefixo>/<nome-da-branch> dev
  ```
- Ao finalizar o trabalho e concluir o merge/PR, remova o worktree com:
  ```bash
  git worktree remove .worktrees/<nome-da-branch>
  ```
- O diretório `.worktrees` deve estar no `.gitignore` ou no `.git/info/exclude`. Nunca commite artefatos de build dentro do worktree.

### Conventional Commits

- Todos os commits devem seguir o padrão [Conventional Commits](https://www.conventionalcommits.org/).
- Formato: `<tipo>(<escopo opcional>): <descrição curta no imperativo>`
- Tipos permitidos: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`
- Escopos sugeridos: `runner`, `session`, `ipc`, `logger`, `agents`, `memory`, `containers`, `tests`, `config`, `docs`, `sandbox`, `skills`
- Exemplos:
  - `feat(memory): implementa extração de padrões de código`
  - `fix(sandbox): corrige permissões em /outputs no container`
  - `test(runner): adiciona cobertura para timeout de container`
  - `chore(deps): adiciona docker>=7.1.0 ao pyproject.toml`
- Commits devem ser pequenos, coesos e revisáveis. Evite commits que misturam múltiplas preocupações.
- Use o corpo do commit para explicar **o porquê** da mudança quando necessário.

### Pull Requests & Squash Merge

- Toda mudança deve ser entregue via Pull Request apontando para `dev`, com descrição clara do que foi feito, por que e como testar.
- O ciclo completo de abertura, code review e squash merge automatizado via GitHub App é regido pelo workflow [`.agents/workflows/do-pull-request.md`](../workflows/do-pull-request.md).
- Autenticação com GitHub App e criação do PR:
  ```bash
  export GH_TOKEN=$(uv run python .agents/skills/github_app_auth.py)
  REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
  git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"
  gh pr create --fill --base dev
  ```

---

## Clean Code

- **Nomes revelam intenção.** Variáveis, funções e classes devem ter nomes descritivos que eliminam a necessidade de comentários óbvios.
- **Funções fazem uma coisa.** Se uma função faz mais de uma coisa, extraia responsabilidades.
- **Type hints obrigatórios** em funções públicas: `def f(x: str) -> int`.
- **Docstrings Google Style** com `Args`, `Returns`, `Raises`.
- **I/O assíncrono:** Sempre use `async/await` para operações de I/O. Nunca use `time.sleep()`.
- **Logging estruturado:** Use `logger.info("msg", extra={...})`. Nunca `print(...)`.
- **Tratamento de erros:** Logar ou propagar. Nunca `except Exception: pass`.
- **Nomeação:** módulos `snake_case.py` · classes `PascalCase` · funções `snake_case` · constantes `UPPER_CASE`.

---

---

## Ciclo de Execução e Orquestração dos Agentes

No GeminiClaw, a execução de agentes não utiliza servidores web externos (`adk web`). O ciclo de vida e execução segue o modelo distribuído via containers e IPC:

```
[ Usuário / CLI ]
       │
       ▼
[ Orchestrator & AutonomousLoop (Host) ]
       │
       ├──→ Triage: Simples (Base) vs Complexo (Planner ➔ Validator ➔ Loop de Subtarefas)
       ├──→ ContainerRunner: Spawna container Docker específico do agente
       └──→ IPCChannel: Comunicação bidirecional via Unix Domain Socket (/tmp/geminiclaw-ipc/)
                │
                ▼
       [ Agente em Container Docker ]
          ├── agents/runner.py: run_ipc_loop conecta ao socket do host
          ├── agents/<tipo>/agent.py: Executa lógica do agente e tool calls
          ├── Skills Framework: python_interpreter (sandbox), memory, search
          └── Saída de Artefatos: /outputs/<session_id>/<task>/
```

### Regras de Implementação para Agentes e Runners:
1. **Entrypoint Padrão:** Cada agente expõe `root_agent` e implementa `if __name__ == "__main__": asyncio.run(run_ipc_loop(root_agent))`.
2. **Protocolo IPC:** Mensagens serializadas em JSON com prefixo de tamanho binário de 4 bytes (`HEADER_SIZE = 4`, `struct.pack('>I', len(data))`).
3. **Registro de Imagens:** Todo novo agente deve ser registrado no `AGENT_REGISTRY` em `src/orchestrator.py` mapeando `agent_id` para sua respectiva imagem Docker (`geminiclaw-<tipo>`).
4. **Isolamento e Persistência:** Agentes nunca escrevem diretamente no banco de dados do host se estiverem em container isolado; métricas e telemetria são transportadas via payload IPC (`_telemetry`) e persistidas pelo orquestrador no `SessionManager` e `TelemetryCollector`.

---

## Docker

Regras obrigatórias para execução de containers no GeminiClaw:

```python
client.containers.run(
    image="geminiclaw-base:latest",  # ou geminiclaw-planner, geminiclaw-researcher, etc.
    mem_limit="512m",                # limite estrito para o Raspberry Pi 5
    nano_cpus=1_000_000_000,         # 1 núcleo de CPU ARM
    network="geminiclaw-net",
    volumes={
        str(ipc_dir): {"bind": "/tmp/geminiclaw-ipc", "mode": "rw"},
        str(output_dir): {"bind": "/outputs", "mode": "rw"},
        str(logs_dir): {"bind": "/logs", "mode": "rw"},
    },
    detach=True,
    remove=True,
    user="appuser",
)
```

- Imagem base: `python:3.11-slim-bookworm`.
- Usuário: estritamente non-root (`appuser`).
- Rede: interna isolada (`geminiclaw-net`).
- Portas: expostas apenas em `127.0.0.1` (nunca `0.0.0.0`).
- Sandboxes efêmeros de execução de código: `network_disabled=True`, volumes de código somente-leitura ou efêmeros.
- Build de imagens: `bash scripts/build_images.sh` ou `docker build -t geminiclaw-<tipo> -f containers/Dockerfile.<tipo> .`.

---

## Princípios Adicionais

1. **100% Python** — Node.js existe apenas como runtime do Gemini CLI, nunca do projeto.
2. **Footprint mínimo** — justifique cada nova dependência; prefira a stdlib.
3. **Single-process por agente** — estado compartilhado apenas via PostgreSQL, Qdrant ou IPC.
4. **Idempotência** — scripts de setup re-executáveis sem efeitos colaterais.
5. **Configuração explícita** — via `.env`; nada de detecção automática que silencie erros.
6. **Logs antes de ação** — toda operação com efeito colateral (API, disco, container) é logada em JSON **antes** de executar.

---

## Referências

- [uv](https://docs.astral.sh/uv/) · [Google ADK](https://google.github.io/adk-docs/get-started/quickstart/) · [docker-py](https://docker-py.readthedocs.io/)
