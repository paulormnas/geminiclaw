# Tarefas: v18.7-source-layout

**Estado (2026-10-15):** implementada na branch `refactor/source-layout`, aguardando revisão e merge; pendente só o 6.2 (depois do merge). `ruff`, `lint-imports` e `pytest -m unit` verdes (3531 testes; linha de base 3518 mais 13 de estrutura); `pytest -m integration`: 36 passaram e 74 foram ignorados por falta de PostgreSQL e Docker no Mac.

**Desvios e dúvidas de spec registrados na implementação** (nenhuma lógica foi alterada):
- `src/utils/qdrant.py` já existia (`get_qdrant_client`); `_make_client` foi acrescentado a ele.
- `src/knowledge/ids.py` continha só as definições da §2.2; o arquivo inteiro foi movido (`git mv`) para `src/utils/node_id.py` e `ids.py` deixou de existir.
- `sha256_file` depende de `IngestionFileError`, `_confined`, `_open_regular` e `_CHUNK`, compartilhados com o resto de `ingestion_io`, e `insumo_tipo` de `_DATASET_EXT` e `_ARTIGO_EXT`; todos foram para `src/documents/hashing.py` e `ingestion_io` os importa de lá (a spec dizia que `documents/hashing.py` receberia só `insumo_tipo`, `sha256_file` e `MAX_HASH_BYTES`).
- A medição achou um segundo ciclo de pacotes, fora da spec: `config` ↔ `utils` (`src/config.py` importa `src/utils/node_id.py` dentro de função; `src/utils/qdrant.py` importa `src.config`). Entrou como exceção do contrato, com dono `v18.7-layer-cycles` (questão em aberto no design daquela mudança).
- A ferramenta trata pacotes na mesma linha como independentes entre si; por isso a linha de base do contrato foi dividida em `research_consult | utils | db`, `config` e `logger` (há importações entre eles). A exceção `egress` ↔ `llm` lista só as três importações de `egress.gate` para `llm`; as de volta (`llm` para `egress`) são permitidas na ordem desta etapa.
- `uv run geminiclaw --help` não funciona, antes e depois desta mudança, no Mac e no Pi: `pyproject.toml` não tem `[build-system]`, então o `uv` não instala o comando. O teste 4.4 confere o ponto de entrada (`src.cli.main:main` chamável) e `python -m src.cli.main --help`; o 6.2 fica pendente da decisão do pesquisador.
- Fora do que a spec listava: `main.py` da raiz, `pyproject.toml` (`per-file-ignores` do `ruff`), `--cov=agents` nas documentações e seis testes que varriam `agents/` na raiz (que passou a não existir e faria a varredura ser vazia sem falhar) passaram a varrer `src/`.

## 1. Preparação
- [x] 1.1 Conferir que nenhuma outra branch com código Python está aberta e que `dev` está sincronizada; criar a worktree `.worktrees/refactor-source-layout` (branch `refactor/source-layout`).
- [x] 1.2 Rodar a suíte `unit` e `integration` e o `ruff` antes de mover, e guardar o resultado como referência (mesmas falhas conhecidas, se houver, devem continuar iguais).
- [x] 1.3 `uv add --dev import-linter`.

## 2. Movimentação
- [x] 2.1 `git mv` dos módulos da tabela do design §2.1, num commit só de movimentação.
- [x] 2.2 `git mv` de `agents/` para `src/agents/` e de `src/agents/validator_agent.py` para `src/agents/validator/agent.py`.
- [x] 2.3 Mover as definições da tabela do design §2.2, com as auxiliares privadas, sem alterar o corpo; `Checkpoint` sob `TYPE_CHECKING` em `src/knowledge/resume_context.py`.
- [x] 2.4 Reescrever as importações em `src/`, `scripts/` e `tests/` por script, incluindo importações dentro de funções, `importlib` e alvos de `patch`/`monkeypatch` em texto.
- [x] 2.5 Corrigir os caminhos calculados a partir de `__file__` nos módulos movidos (`src/cli/main.py` e `src/host/platform_images.py` com `parents[2]`, nunca `src/` no `sys.path`; design §6 L1) e conferir `scripts/platform_images.py` e `scripts/setup_pi.sh`.
- [x] 2.7 Reescrever os caminhos citados como texto em `tests/unit/egress/test_wiring.py` (`src/research_data/context_loader.py`, `src/llm/model_router.py`) e os alvos de `patch`/`monkeypatch` das definições da §2.2 para o módulo novo (design §6 L2 e L3).
- [x] 2.6 Ponto de entrada `geminiclaw = "src.cli.main:main"` em `pyproject.toml`.

## 3. Contrato de camadas
- [x] 3.1 Contrato em `pyproject.toml` com as camadas do design §3 e a exceção única `egress` ↔ `llm` comentada com a referência a `v18.7-layer-cycles`.
- [x] 3.2 Teste `unit` que executa a verificação de contratos e falha se ela falhar.
- [x] 3.3 Teste `unit` com pacote e contrato temporários em `tmp_path` (`knowledge` importando `orchestration` dentro de função) que confirma que a verificação a acusa, sem criar arquivo dentro de `src/`.
- [x] 3.4 Teste `unit` do cenário "Importação de verificação de tipos não conta" (contrato do projeto passa; cópia sem a exclusão de `TYPE_CHECKING` acusa `resume_context` → `continuity`).

## 4. Testes de estrutura
- [x] 4.1 Teste: a raiz de `src/` contém só `__init__.py`, `config.py`, `logger.py` e `db.py`, e não existe `agents/` na raiz do repositório.
- [x] 4.2 Teste: nenhuma ocorrência textual dos caminhos antigos (`src.<módulo antigo>`, `agents.` como pacote, `src/<módulo antigo>.py`) em `src/`, `scripts/`, `tests/` e `.agents/`.
- [x] 4.3 Teste: os arquivos de dados apontados por caminhos calculados a partir de `__file__` existem (vocabulário, catálogo de modelos, manifesto de imagens, auxiliares científicos do sandbox).
- [x] 4.4 Teste: `uv run geminiclaw --help` termina com código 0 (subprocesso).
- [x] 4.5 Testes de segurança da estrutura (design §6): `sys.path` sem `src/` e `egress`/`agents` não importáveis sem prefixo; `PROJECT_ROOT` e a raiz do sandbox iguais à raiz do repositório; `test_wiring.py` cita os caminhos novos; nenhum alvo de `patch` de definição da §2.2 no módulo de origem.

## 5. Documentação
- [x] 5.1 `AGENTS.md` §7 (estrutura do projeto) e `README.md` com a estrutura nova (aprovação explícita registrada no PR).
- [x] 5.2 Caminhos em `.agents/rules/` e `.agents/workflows/`, `openspec/project.md` e `openspec/specs/`.
- [x] 5.3 Tabela de caminhos do design §2 copiada para `roadmaps/roadmap_V18.7.md`.

## 6. Validação
- [x] 6.1 `uv run ruff check .`, verificação de contratos e `uv run pytest -m "unit or integration"` verdes; o diff dos testes só altera caminhos de importação, alvos de `patch`/`monkeypatch` e caminhos citados como dados.
- [ ] 6.2 Depois do merge: `uv sync` e `uv run geminiclaw --help` no Mac e no Raspberry Pi; `scripts/setup_pi.sh` encontra `containers/images.yaml`.
- [x] 6.3 Atualizar esta lista e a linha de estado no PR.
