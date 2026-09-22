# AGENTS.md — Guia Global de Governança para Agentes

Este documento é o **ponto de entrada e fonte primária de governança** para agentes de IA que atuam no repositório **GeminiClaw**. Ele define as regras invioláveis de desenvolvimento, a ordem de atuação por papéis e o índice de manuais especializados.

**Projeto:** Framework leve de orquestração de agentes Gemini para Raspberry Pi 5.
**Stack:** Python 3.11+, Google ADK, Docker, PostgreSQL 16, Qdrant, pytest, uv.

---

## 1. Princípios Invioláveis de Governança

1. **100% Python:** Nenhum arquivo `.js`, `.ts` ou `.mjs` deve existir neste projeto. Node.js existe apenas como runtime do Gemini CLI, nunca do projeto.
2. **Nunca comitar em `main` ou `dev`:** Todas as alterações devem ser feitas em branches dedicadas com prefixos semânticos (`feat/`, `fix/`, `refactor/`, `chore/`, `docs/`, `test/`).
3. **Uso Obrigatório de Git Worktree:** Toda nova alteração deve ser desenvolvida em worktree exclusiva criada em `.worktrees/<nome-da-branch>`.
4. **Commits Semânticos:** Todos os commits devem seguir [Conventional Commits](https://www.conventionalcommits.org/) (`feat: ...`, `fix: ...`, `test: ...`, `docs: ...`, `refactor: ...`).
5. **Aprovação Explícita do Usuário:** O agente DEVE parar e aguardar aprovação explícita antes de: deletar arquivos, alterar schemas de banco, modificar Dockerfiles base, executar operações destrutivas (`docker rm -f`, `DROP TABLE`) ou qualquer ação irreversível.
6. **Fail-Fast e Integridade Metodológica:** Nunca inventar dados fictícios ou gerar mocks silenciosos em fluxos de produção. Erros devem ser explícitos e acionáveis.
7. **Zero Secrets em Código:** Credenciais e chaves de API vêm exclusivamente de variáveis de ambiente gerenciadas em `.env` e `src/config.py`. Nunca versionar `.env`, `*.db` ou arquivos de log.
8. **Gerenciamento Exclusivo com `uv`:** Nunca usar `pip`, `pip3`, `pipenv` ou `poetry`. Sempre `uv add`, `uv sync`, `uv run`.
9. **Testes Antes de Commit:** Nunca commitar com testes falhando. Executar `uv run pytest -m "unit or integration" -v` antes de cada commit.

---

## 2. Fluxo Padrão de Entrega

Para qualquer nova funcionalidade, refatoração relevante ou correção estrutural:

```
[1. Arquiteto de Soluções] ──→ [2. Analista de Segurança] ──→ [3. Devs Core/Agentes] ──→ [4. Tester / QA] ──→ [5. Pull Request]
    (Impacto, ADR & Specs)        (Modelagem & Hardening)       (Worktree & Código)        (pytest & Docker)       (Revisão & Merge)
```

1. **Arquiteto de Soluções:** Entende o domínio de orquestração de agentes, avalia impactos nos 6 eixos, registra o ADR em `docs/decisions/` e gera as specs no padrão do projeto.
2. **Analista de Segurança:** Avalia a arquitetura contra ameaças de escape de sandbox, vazamento de segredos, injeção de prompt e contenção de recursos no Pi 5.
3. **Desenvolvedor (Core / Agentes):** Cria a worktree exclusiva, implementa respeitando Clean Code/Architecture e adiciona testes automatizados com pytest.
4. **Tester / QA:** Valida critérios de aceite com testes unitários, de integração e benchmarks, homologa o fechamento de Não Conformidades.
5. **Pull Request:** Abre o PR detalhado no GitHub apontando para `dev` via GitHub App.

> **Nota:** Para etapas futuras que incluam frontend (dashboard de monitoramento, UI de controle), os papéis de **Designer de Produto** e **Desenvolvedor Frontend** serão ativados conforme o roadmap do projeto.

---

## 3. Índice de Regras por Papel (`.agents/rules/`)

Ao assumir um papel específico, o agente deve consultar e seguir integralmente seu respectivo manual:

| Papel | Arquivo de Regras | Foco Principal |
|---|---|---|
| **Arquiteto de Soluções** | [`.agents/rules/architect.md`](.agents/rules/architect.md) | Domínio de orquestração de agentes, separação de camadas, ADRs, trade-offs e análise de impacto. |
| **Analista de Segurança** | [`.agents/rules/security-analyst.md`](.agents/rules/security-analyst.md) | Escape de sandbox, contenção Docker, vazamento de segredos, STRIDE adaptado para agentes de IA. |
| **Desenvolvedor Core / Agentes** | [`.agents/rules/backend-dev.md`](.agents/rules/backend-dev.md) | Python 3.11+, Google ADK, Docker, `uv`, Clean Architecture, DDD, pytest. |
| **Tester / QA** | [`.agents/rules/tester.md`](.agents/rules/tester.md) | pytest, pytest-asyncio, fixtures Docker, mocks de LLM, benchmarks no Raspberry Pi 5. |
| **Designer de Produto** *(futuro)* | [`.agents/rules/designer.md`](.agents/rules/designer.md) | Design System, tokens semânticos, dark mode e UI para dashboard de monitoramento. |
| **Desenvolvedor Frontend** *(futuro)* | [`.agents/rules/frontend-dev.md`](.agents/rules/frontend-dev.md) | Frontend Python-first (ou framework a definir), acessibilidade e componentes visuais. |

---

## 4. Índice de Workflows Operacionais (`.agents/workflows/`)

Procedimentos operacionais padronizados para execução de tarefas complexas:

- 🚀 **Ciclo de Nova Feature:** [`.agents/workflows/new-feature.md`](.agents/workflows/new-feature.md) — Fluxo ponta a ponta desde o design até o merge.
- 📐 **Especificação de Nova Etapa do Roadmap:** [`.agents/workflows/stage-spec.md`](.agents/workflows/stage-spec.md) — Criação coordenada de specs de etapas completas do roadmap.
- 🧩 **Especificação de Componente:** [`.agents/workflows/component-spec.md`](.agents/workflows/component-spec.md) — Design e estados de componentes visuais *(futuro)*.
- 🔍 **Análise de Impacto & Proposta Técnica:** [`.agents/workflows/impact-analysis.md`](.agents/workflows/impact-analysis.md) — Avaliação em 6 eixos antes do código.
- 🛠️ **Ciclo de Correção de NC:** [`.agents/workflows/fix-nc.md`](.agents/workflows/fix-nc.md) — Tratamento de desvios reportados pelo tester.
- 🔀 **Pull Request, Code Review & Merge:** [`.agents/workflows/do-pull-request.md`](.agents/workflows/do-pull-request.md) — Criação de PR, revisão técnica, ciclo de melhorias e merge.
- 🚨 **Hotfix em Produção:** [`.agents/workflows/hotfix.md`](.agents/workflows/hotfix.md) — Correção acelerada com validação obrigatória.
- 🎨 **Auditoria de Design:** [`.agents/workflows/design-review.md`](.agents/workflows/design-review.md) — Conformidade de tokens e acessibilidade *(futuro)*.
- 🧹 **Limpeza de Ambiente:** [`.agents/workflows/clean.md`](.agents/workflows/clean.md) — Limpa logs, outputs e registros nos bancos.
- 📝 **Commit:** [`.agents/workflows/commit.md`](.agents/workflows/commit.md) — Sequência padronizada para commit.
- 🧪 **Execução de Testes:** [`.agents/workflows/run-tests.md`](.agents/workflows/run-tests.md) — Guia rápido de execução de testes.
- ▶️ **Execução do Projeto:** [`.agents/workflows/run_project.md`](.agents/workflows/run_project.md) — Execução do projeto e validação de agentes.

---

## 5. Ambiente

```bash
# Criar ambiente virtual
uv venv .venv

# Ativar
source .venv/bin/activate

# Instalar dependências do projeto
uv sync

# Adicionar nova dependência (atualiza pyproject.toml e uv.lock)
uv add nome-do-pacote

# Adicionar dependência de desenvolvimento
uv add --dev nome-do-pacote

# Atualizar todas as dependências
uv sync --upgrade
```

> Nunca use `pip` diretamente. Sempre use `uv`.

---

## 6. Comandos Essenciais

```bash
# Rodar todos os testes
uv run pytest

# Rodar apenas testes unitários (rápido)
uv run pytest -m unit -v

# Rodar com cobertura
uv run pytest --cov=src --cov=agents --cov-report=term-missing

# Subir agente em modo desenvolvimento
cd agents/<nome-do-agente> && uv run adk web

# Verificar containers ativos
docker ps --filter "name=geminiclaw"
```

---

## 7. Estrutura do Projeto

```
geminiclaw/
├── AGENTS.md                  # Este arquivo
├── GEMINI.md                  # Contexto persistente do Gemini CLI
├── .agents/                   # Governança de agentes de IA
│   ├── rules/                 # Regras detalhadas por papel
│   │   ├── architect.md
│   │   ├── backend-dev.md
│   │   ├── security-analyst.md
│   │   ├── tester.md
│   │   ├── designer.md        # (futuro)
│   │   ├── frontend-dev.md    # (futuro)
│   │   └── review.md
│   └── workflows/             # Workflows operacionais
│       ├── new-feature.md
│       ├── do-pull-request.md
│       ├── impact-analysis.md
│       ├── stage-spec.md
│       ├── fix-nc.md
│       ├── hotfix.md
│       ├── clean.md
│       ├── commit.md
│       ├── run-tests.md
│       └── run_project.md
├── pyproject.toml             # Dependências e configuração (fonte da verdade)
├── uv.lock                    # Lockfile gerado pelo uv (versionar)
├── .env / .env.example        # Credenciais (nunca versionar .env)
├── src/                       # Orquestrador Python
├── agents/                    # Agentes ADK
├── containers/                # Dockerfiles
├── tests/                     # Testes pytest
├── roadmaps/                  # Roadmaps de versões (V10–V14+)
├── docs/decisions/            # ADRs (Architectural Decision Records)
├── store/                     # SQLite (runtime)
└── logs/                      # Logs (runtime)
```

---

## 8. Limites — O Agente Nunca Deve

- Usar `pip install` em qualquer circunstância
- Criar arquivos `.js`, `.ts` ou `.mjs`
- Commitar `.env`, `*.db` ou arquivos de log
- Alterar `GEMINI.md` sem instrução explícita do usuário
- Executar operações destrutivas (`docker rm -f`, `DROP TABLE`) sem confirmação
- Commitar com testes falhando
- Implementar antes de obter aprovação explícita do usuário em planos
