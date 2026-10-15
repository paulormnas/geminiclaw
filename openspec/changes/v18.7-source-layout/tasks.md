# Tarefas: v18.7-source-layout

**Estado (2026-10-15):** não iniciada.

## 1. Preparação
- [ ] 1.1 Conferir que nenhuma outra branch com código Python está aberta e que `dev` está sincronizada; criar a worktree `.worktrees/refactor-source-layout` (branch `refactor/source-layout`).
- [ ] 1.2 Rodar a suíte `unit` e `integration` e o `ruff` antes de mover, e guardar o resultado como referência (mesmas falhas conhecidas, se houver, devem continuar iguais).
- [ ] 1.3 `uv add --dev import-linter`.

## 2. Movimentação
- [ ] 2.1 `git mv` dos módulos da tabela do design §2.1, num commit só de movimentação.
- [ ] 2.2 `git mv` de `agents/` para `src/agents/` e de `src/agents/validator_agent.py` para `src/agents/validator/agent.py`.
- [ ] 2.3 Mover as definições da tabela do design §2.2, com as auxiliares privadas, sem alterar o corpo; `Checkpoint` sob `TYPE_CHECKING` em `src/knowledge/resume_context.py`.
- [ ] 2.4 Reescrever as importações em `src/`, `scripts/` e `tests/` por script, incluindo importações dentro de funções, `importlib` e alvos de `patch`/`monkeypatch` em texto.
- [ ] 2.5 Corrigir os caminhos calculados a partir de `__file__` nos módulos movidos (`src/cli/main.py` e `src/host/platform_images.py` com `parents[2]`, nunca `src/` no `sys.path`; design §6 L1) e conferir `scripts/platform_images.py` e `scripts/setup_pi.sh`.
- [ ] 2.7 Reescrever os caminhos citados como texto em `tests/unit/egress/test_wiring.py` (`src/research_data/context_loader.py`, `src/llm/model_router.py`) e os alvos de `patch`/`monkeypatch` das definições da §2.2 para o módulo novo (design §6 L2 e L3).
- [ ] 2.6 Ponto de entrada `geminiclaw = "src.cli.main:main"` em `pyproject.toml`.

## 3. Contrato de camadas
- [ ] 3.1 Contrato em `pyproject.toml` com as camadas do design §3 e a exceção única `egress` ↔ `llm` comentada com a referência a `v18.7-layer-cycles`.
- [ ] 3.2 Teste `unit` que executa a verificação de contratos e falha se ela falhar.
- [ ] 3.3 Teste `unit` com pacote e contrato temporários em `tmp_path` (`knowledge` importando `orchestration` dentro de função) que confirma que a verificação a acusa, sem criar arquivo dentro de `src/`.
- [ ] 3.4 Teste `unit` do cenário "Importação de verificação de tipos não conta" (contrato do projeto passa; cópia sem a exclusão de `TYPE_CHECKING` acusa `resume_context` → `continuity`).

## 4. Testes de estrutura
- [ ] 4.1 Teste: a raiz de `src/` contém só `__init__.py`, `config.py`, `logger.py` e `db.py`, e não existe `agents/` na raiz do repositório.
- [ ] 4.2 Teste: nenhuma ocorrência textual dos caminhos antigos (`src.<módulo antigo>`, `agents.` como pacote, `src/<módulo antigo>.py`) em `src/`, `scripts/`, `tests/` e `.agents/`.
- [ ] 4.3 Teste: os arquivos de dados apontados por caminhos calculados a partir de `__file__` existem (vocabulário, catálogo de modelos, manifesto de imagens, auxiliares científicos do sandbox).
- [ ] 4.4 Teste: `uv run geminiclaw --help` termina com código 0 (subprocesso).
- [ ] 4.5 Testes de segurança da estrutura (design §6): `sys.path` sem `src/` e `egress`/`agents` não importáveis sem prefixo; `PROJECT_ROOT` e a raiz do sandbox iguais à raiz do repositório; `test_wiring.py` cita os caminhos novos; nenhum alvo de `patch` de definição da §2.2 no módulo de origem.

## 5. Documentação
- [ ] 5.1 `AGENTS.md` §7 (estrutura do projeto) e `README.md` com a estrutura nova (aprovação explícita registrada no PR).
- [ ] 5.2 Caminhos em `.agents/rules/` e `.agents/workflows/`, `openspec/project.md` e `openspec/specs/`.
- [ ] 5.3 Tabela de caminhos do design §2 copiada para `roadmaps/roadmap_V18.7.md`.

## 6. Validação
- [ ] 6.1 `uv run ruff check .`, verificação de contratos e `uv run pytest -m "unit or integration"` verdes; o diff dos testes só altera caminhos de importação, alvos de `patch`/`monkeypatch` e caminhos citados como dados.
- [ ] 6.2 Depois do merge: `uv sync` e `uv run geminiclaw --help` no Mac e no Raspberry Pi; `scripts/setup_pi.sh` encontra `containers/images.yaml`.
- [ ] 6.3 Atualizar esta lista e a linha de estado no PR.
