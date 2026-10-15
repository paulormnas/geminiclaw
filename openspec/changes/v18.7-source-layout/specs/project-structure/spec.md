# Capacidade: project-structure

## ADDED Requirements

### Requirement: Pacotes por responsabilidade
O código Python do backend SHALL ficar em pacotes de `src/` organizados por responsabilidade, conforme a tabela de caminhos do design §2, e a raiz de `src/` MUST conter só `__init__.py`, `config.py`, `logger.py` e `db.py`. Os agentes SHALL ficar todos em `src/agents/`, e MUST NOT existir o pacote `agents/` na raiz do repositório (ADR 024 §2).

#### Scenario: Raiz de src só com módulos transversais
- **WHEN** o teste de estrutura lista os arquivos `.py` da raiz de `src/`
- **THEN** a lista é exatamente `__init__.py`, `config.py`, `db.py`, `logger.py`

#### Scenario: Agentes num só pacote
- **WHEN** o teste de estrutura procura o diretório `agents/` na raiz do repositório e o módulo `src/agents/validator/agent.py`
- **THEN** o diretório não existe e o módulo existe

### Requirement: Sem caminhos antigos
Nenhum módulo de compatibilidade SHALL reexportar caminhos antigos, e nenhuma importação, alvo de `patch`/`monkeypatch` ou referência textual a um caminho antigo MUST permanecer em `src/`, `scripts/`, `tests/` ou `.agents/` (ADR 024 §6).

#### Scenario: Busca textual pelos caminhos antigos
- **GIVEN** a lista de módulos antigos da tabela do design §2.1
- **WHEN** o teste de estrutura busca `src.<módulo antigo>` e `src/<módulo antigo>.py` em `src/`, `scripts/`, `tests/` e `.agents/`
- **THEN** não há nenhuma ocorrência

#### Scenario: Importação antiga falha
- **WHEN** um teste executa `importlib.import_module("src.orchestrator")`
- **THEN** a chamada lança `ModuleNotFoundError`

#### Scenario: Testes de segurança do egresso citam os caminhos novos
- **WHEN** o teste de estrutura lê `tests/unit/egress/test_wiring.py`
- **THEN** o texto cita `src/research_data/context_loader.py` e `src/llm/model_router.py`, não cita `src/context_loader.py` nem `src/model_router.py`, e os dois caminhos novos existem

#### Scenario: Alvo de patch de definição movida aponta para o módulo novo
- **GIVEN** os pares (módulo de origem depois da movimentação, definição) da tabela do design §2.2, por exemplo (`src.session.continuity`, `ST_CONCLUIDA`), (`src.agents.validator.agent`, `MetricCriterion`), (`src.knowledge.ids`, `uuid7`), (`src.orchestration.orchestrator`, `AgentTask`)
- **WHEN** o teste de estrutura procura em `tests/` alvos de `patch`/`monkeypatch` escritos como texto `"<módulo de origem>.<definição>"`
- **THEN** não há nenhuma ocorrência

### Requirement: Raiz do projeto nos caminhos calculados
`src/cli/main.py` SHALL inserir no `sys.path` só a raiz do repositório (o diretório que contém `pyproject.toml`), MUST NOT inserir `src/`, e `src/host/platform_images.py` SHALL calcular `PROJECT_ROOT` como essa mesma raiz; nenhum pacote de `src/` MUST ser importável por um nome sem o prefixo `src.` (ADR 024 §6; ADR 019, um só portão de egresso por processo).

#### Scenario: sys.path sem src
- **WHEN** o teste importa `src.cli.main`
- **THEN** `src.cli.main.root_path` é a raiz do repositório, o caminho de `src/` não está em `sys.path`, e `importlib.import_module("egress")` e `importlib.import_module("agents")` lançam `ModuleNotFoundError`

#### Scenario: Raiz do sandbox e das imagens
- **WHEN** o teste compara `src.host.platform_images.PROJECT_ROOT` e `Path(src.skills.code.sandbox.__file__).resolve().parents[3]` com a raiz do repositório
- **THEN** os dois são iguais à raiz

### Requirement: Contrato de camadas verificado
O projeto SHALL declarar um contrato de camadas com a ordem do design §3 e SHALL verificá-lo com a ferramenta de contratos de importação junto com o `ruff` e os testes; importações dentro de funções MUST contar e as que estão sob `TYPE_CHECKING` MUST NOT contar. A única exceção permitida é o ciclo `egress` ↔ `llm` declarado nominalmente e atribuído a `v18.7-layer-cycles` (ADR 024 §3).

#### Scenario: Contrato válido no código reorganizado
- **WHEN** o teste `unit` executa a verificação de contratos
- **THEN** a verificação termina com sucesso

#### Scenario: Importação proibida é acusada
- **GIVEN** um pacote temporário em `tmp_path` (fora da árvore do repositório) com os subpacotes `orchestration` e `knowledge`, em que `knowledge/mod.py` importa `orchestration` dentro de uma função, e um contrato temporário com as mesmas opções do projeto e as camadas `orchestration` acima de `knowledge`, com a raiz trocada pelo pacote temporário
- **WHEN** a verificação roda em subprocesso sobre esse contrato, com `tmp_path` no `PYTHONPATH`
- **THEN** ela termina com código diferente de 0 e a saída cita `knowledge` e `orchestration`

#### Scenario: Importação de verificação de tipos não conta
- **GIVEN** `src/knowledge/resume_context.py` importa `Checkpoint` de `src.session.continuity` só sob `TYPE_CHECKING`
- **WHEN** a verificação de contratos roda com o contrato do projeto e, em seguida, com uma cópia temporária do contrato sem a opção que exclui importações de `TYPE_CHECKING`
- **THEN** a primeira termina com sucesso e a segunda acusa a importação de `src.knowledge.resume_context` para `src.session.continuity`

### Requirement: Comportamento preservado
A reorganização MUST NOT alterar comportamento: a suíte `unit` e `integration` SHALL passar, e nos testes só podem mudar caminhos de importação, alvos de `patch`/`monkeypatch` e caminhos de arquivo citados como dados (ADR 024 §1).

#### Scenario: Ponto de entrada da CLI
- **WHEN** o teste executa `uv run geminiclaw --help` num subprocesso
- **THEN** o processo termina com código 0 e a ajuda é impressa

#### Scenario: Arquivos de dados acessíveis
- **WHEN** o teste resolve os caminhos calculados a partir de `__file__` do vocabulário (`data/vocabulary/metrics.yaml`), do catálogo de modelos (`src/llm/catalog.yaml`), do manifesto de imagens (`containers/images.yaml`, via a raiz do projeto de `src/host/platform_images.py`) e dos auxiliares científicos do sandbox (`src/skills/code/scientific_helpers.py`)
- **THEN** todos os arquivos existem
