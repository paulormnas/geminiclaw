# Proposta: organização do código por responsabilidade (Etapa 1)

**ID:** `v18.7-source-layout` · **Versão:** V18.7 · **Capacidade:** `project-structure` (nova)
**ADRs de origem:** [ADR 024](../../../../docs/decisions/adr_024_organizacao_do_codigo.md) §1 (Etapa 1), §2 (estrutura alvo), §3 (regra de camadas), §6 (sem caminhos antigos), §7 (o que é atualizado junto), §8 (aprovações)
**Depende de:** nenhuma mudança em aberto. É a primeira da V18.7: todas as outras mudanças `v18.7-*` são implementadas depois do merge desta, e os caminhos citados nelas valem pela tabela do `design.md` §2.

## Por quê

A raiz de `src/` tem 44 módulos (cerca de 23 mil linhas) de seis assuntos, os agentes estão em dois lugares (`agents/` na raiz do repositório e `src/agents/validator_agent.py`) e há 16 pares de pacotes que se importam mutuamente. A V18.7 cria módulos novos e mexe nos módulos maiores; sem reorganizar antes, a raiz e os ciclos crescem (ADR 024, Contexto).

## O que muda

### Novo
- Pacotes `src/cli/`, `src/orchestration/`, `src/session/`, `src/gate/`, `src/artifacts/`, `src/documents/`, `src/observability/`, `src/host/` com os módulos da tabela do `design.md` §2.
- Módulos novos que só recebem definições movidas sem alterar o corpo: `src/knowledge/subtask_states.py`, `src/knowledge/metric_criteria.py`, `src/documents/hashing.py`, `src/utils/node_id.py`, `src/agent_runtime/types.py`.
- Contrato de camadas verificado por ferramenta de contratos de importação (`import-linter`, dependência de desenvolvimento), executado com o `ruff` e os testes, com uma única exceção inicial: o ciclo `egress` ↔ `llm`, removido por `v18.7-layer-cycles`.
- Testes de estrutura: raiz de `src/` só com os módulos permitidos, nenhum caminho antigo em código ou texto, arquivos de dados acessíveis pelos caminhos calculados a partir de `__file__`.

### Modificado
- Todo o pacote `agents/` da raiz passa para `src/agents/`; `src/agents/validator_agent.py` vira `src/agents/validator/agent.py`.
- Importações em `src/`, `scripts/` e `tests/`; alvos de `patch`/`monkeypatch` escritos como texto; caminhos de arquivo citados como dados nos testes.
- Ponto de entrada: `geminiclaw = "src.cli.main:main"` em `pyproject.toml`.
- Caminhos calculados a partir de `__file__` nos módulos movidos (`src/cli.py:21`, `src/platform_images.py:29`) e scripts que dependem da raiz do projeto (`scripts/platform_images.py`, `scripts/setup_pi.sh`).
- Seção de estrutura do `AGENTS.md` (§7) e do `README.md`; caminhos citados em `.agents/rules/` e `.agents/workflows/`; `openspec/project.md` e `openspec/specs/` onde citam caminhos de módulo; tabela de caminhos copiada para `roadmaps/roadmap_V18.7.md`.

### Removido
- Os 41 módulos da raiz de `src/` que mudam de lugar (ficam só `__init__.py`, `config.py`, `logger.py`, `db.py`) e o pacote `agents/` da raiz. Sem módulos de compatibilidade nos caminhos antigos.

### Fora do escopo
- Resolver o ciclo `egress` ↔ `llm` (mudança de lógica): `v18.7-layer-cycles`.
- Dividir `autonomous_loop`, `orchestrator`, `cli/main` e `human_gate`: feito pelas mudanças da V18.7 que alteram esses trechos (ADR 024 §5).
- Dividir `src/knowledge/` em subpacotes (adiado, ADR 024 alternativa J).
- Trocar o nome do pacote (ADR 011).

## Impacto

- **Código:** só movimentação e ajuste de importações; nenhuma mudança de comportamento. Critério: suíte `unit` e `integration` inteira verde, e nos testes só mudam caminhos de importação, alvos de `patch`/`monkeypatch` e caminhos citados como dados.
- **Contratos:** caminhos de módulo e o ponto de entrada da CLI. Nomes de logger mudam com `get_logger(__name__)`; não há filtro por nome de logger (`src/logger.py`).
- **Schema:** nenhum. **Docker:** nenhum (o sandbox não copia `src/` nem `agents/`).
- **Custo:** nenhum custo de execução; um PR grande, que exige não haver outra branch com código Python aberta.
- **Operação:** depois do merge, `uv sync` no Mac e no Raspberry Pi para reinstalar o comando `geminiclaw`.

## Aprovações necessárias

- **Alteração do `AGENTS.md`** (seção de estrutura do projeto, §7), que exige aprovação explícita (AGENTS.md §8).
- **Remoção do pacote `agents/` da raiz e dos módulos movidos** (com `git mv`, preservando o histórico).
- **Nova dependência de desenvolvimento:** `import-linter` (`uv add --dev import-linter`).
