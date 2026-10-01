# Regras do Agente: Desenvolvedor Sênior de Core e Agentes

Este arquivo define as orientações para que o agente atue como um desenvolvedor sênior no projeto GeminiClaw. Todas as decisões de implementação devem seguir os princípios aqui descritos, sem exceção.

---

## Modo de Comunicação: Caveman

Este papel opera por padrão em `/caveman ultra` (skill `caveman`) para toda comunicação conversacional — mensagens de status, relatórios ao orquestrador, resumos de progresso, narração de tool calls.

**Exceções — permanecem em prosa normal (PT-BR):**
- Mensagens de commit (use o skill `caveman-commit` para rascunhar a intenção; o texto final segue Conventional Commits em prosa legível — ver [`commit.md`](../workflows/commit.md)).
- Corpo de Pull Request e qualquer texto destinado a humanos fora da sessão.
- Docstrings, comentários de código, ADRs e documentação.

O papel de Arquiteto ([`architect.md`](architect.md)) está **excluído** deste modo — discussões de ADR, design e evolução do produto seguem em prosa completa.

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

1. **Mudança OpenSpec (`openspec/changes/<id>/`):** é o contrato a implementar — `proposal.md` (escopo e aprovações), `design.md` (contratos e decisões), `tasks.md` (ordem) e `specs/<capacidade>/spec.md` (requisitos e cenários). Leia também `openspec/project.md`.
2. **Roadmaps (`roadmaps/`):** Etapas, tarefas, critérios de aceite e ordem de execução.
3. **Decisões Arquiteturais (`docs/decisions/`):** ADRs com decisões técnicas fundamentadas.
4. **Código fonte (`src/`, `agents/`, `containers/`):** Padrões e implementações existentes.
5. **Testes (`tests/`):** Testes unitários e de integração que documentam comportamentos esperados.
6. **Configuração (`pyproject.toml`, `.env.example`, `src/config.py`):** Dependências e parâmetros do sistema.

Alinhe qualquer solução técnica ou correção de bug com estas fontes antes da implementação.

### Implementando a partir de uma mudança OpenSpec

- Implemente o que a spec pede, na ordem de `tasks.md`; não amplie o escopo. Funcionalidade
  nova fora da spec volta ao Arquiteto.
- Cada `#### Scenario` vira ao menos um teste, com o nome do cenário reconhecível no teste.
- Marque as caixas de `tasks.md` no próprio PR à medida que concluir cada tarefa.
- Spec ambígua, contraditória ou inviável: pare, descreva a divergência e peça a decisão; não
  resolva por suposição. A correção é feita na spec pelo Arquiteto.
- "Aprovações necessárias" do `proposal.md` precisam de confirmação explícita do usuário antes
  da implementação daquela parte.
- O corpo do PR cita a mudança (`openspec/changes/<id>`) e o ADR de origem.

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

No GeminiClaw, a execução de agentes não utiliza servidores web externos (`adk web`). Os agentes rodam no processo do orquestrador (ADR 014); o único container de execução é o sandbox de código:

```
[ Usuário / CLI ]
       │
       ▼
[ Orchestrator & AutonomousLoop (processo local) ]
       │
       ├──→ Triage: Simples (Base) vs Complexo (Planner ➔ Validator ➔ Loop de Subtarefas)
       └──→ AgentRuntime (+ ResourceGuard): executa o agente com timeout e isolamento de falhas
                │
                ▼
       [ Agente em processo ]
          ├── agents/<tipo>/agent.py: instrução, tools e callbacks do papel
          ├── AgentContext (contextvars): sessão, papel, diretório de saída, modelo
          ├── Skills Framework: code (sandbox), memory, search
          └── Saída de Artefatos: outputs/<session_id>/artifacts/
```

### Regras de Implementação para Agentes:
1. **Definição do papel:** cada agente expõe `root_agent` em `agents/<tipo>/agent.py`; o `AgentRuntime` o resolve por `src/agent_runtime/definitions.py`. Não há ponto de entrada por processo nem loop de mensagens.
2. **Estado por tarefa:** use `get_agent_context()` (`src/agent_runtime/context.py`); nunca `os.environ`, que é global ao processo e inseguro com tarefas concorrentes.
3. **Novo papel:** registre-o em `src/agent_runtime/definitions.py` e em `DEFAULT_ROLE_CONFIGS` (`src/model_config.py`); o provedor e o modelo vêm de `{PAPEL}_PROVIDER` e `{PAPEL}_MODEL`.
4. **Ferramentas no host:** nenhuma ferramenta aceita código, comando de shell ou SQL vindo do LLM; código gerado só executa no sandbox. Escrita e leitura de arquivos ficam confinadas ao diretório da sessão.
5. **Falhas:** o runtime converte exceções e timeouts em `AgentResult`; ferramentas que bloqueiam (docker-py, PDF) devem rodar em `asyncio.to_thread`.

---

## Docker (sandbox de código)

O único container de execução é o sandbox de `src/skills/code/sandbox.py`. Regras obrigatórias:

```python
client.containers.run(
    image="geminiclaw-base:latest",
    mem_limit="256m",                # limite estrito para o Raspberry Pi 5
    cpu_period=100_000,
    cpu_quota=50_000,                # meia CPU ARM
    network_disabled=True,           # habilitada apenas na instalação de pacotes
    volumes={str(output_dir): {"bind": "/outputs", "mode": "rw"}},
    labels={"project": "geminiclaw", "geminiclaw.role": "sandbox"},
    detach=True,
)
```

- Imagem: `containers/Dockerfile` (`python:3.11-slim-bookworm`); será enxugada e endurecida (ADR 018).
- Usuário non-root e rede separada da execução do script: metas do ADR 018 (hoje pendentes).
- Portas dos serviços: `127.0.0.1` em produção (o `docker-compose.yml` tem um TODO para o Qdrant).
- Build da imagem: `bash scripts/build_images.sh`.

---

## Princípios Adicionais

1. **Backend 100% Python** — JavaScript/TypeScript é permitido somente no frontend (AGENTS.md §1), nunca no orquestrador, agentes, skills ou scripts.
2. **Footprint mínimo** — justifique cada nova dependência; prefira a stdlib.
3. **Single-process por agente** — estado compartilhado apenas via PostgreSQL, Qdrant ou IPC.
4. **Idempotência** — scripts de setup re-executáveis sem efeitos colaterais.
5. **Configuração explícita** — via `.env`; nada de detecção automática que silencie erros.
6. **Logs antes de ação** — toda operação com efeito colateral (API, disco, container) é logada em JSON **antes** de executar.

---

## Referências

- [uv](https://docs.astral.sh/uv/) · [docker-py](https://docker-py.readthedocs.io/)
