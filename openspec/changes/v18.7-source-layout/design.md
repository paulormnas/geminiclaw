# Design: organização do código por responsabilidade (Etapa 1)

## 1. Princípio

Só se move código: módulos inteiros e definições (funções, classes, constantes, com as auxiliares privadas de que dependem) de um módulo para outro, **sem alterar o corpo**, ajustando as importações. Importações usadas só em anotações de tipo passam para `TYPE_CHECKING` quando isso desfaz um ciclo. Nenhuma lógica muda; qualquer necessidade de mudar lógica que apareça na implementação volta ao Arquiteto e entra em `v18.7-layer-cycles` (ADR 024 §1).

## 2. Tabela de caminhos

A tabela foi gerada por um script que lê as importações reais (inclusive as feitas dentro de funções) e simula o grafo de pacotes depois das movimentações (§4). Os nomes dos módulos novos dentro de cada pacote seguem o assunto (por exemplo, `cli_graph` vira `cli/graph.py`, `artifact_profile` vira `artifacts/profile.py`).

### 2.1 Módulos

| Caminho antigo | Caminho novo |
|---|---|
| `src/agent_runtime/context.py` | `src/utils/agent_context.py` |
| `src/agents/validator_agent.py` | `src/agents/validator/agent.py` |
| `src/artifact_match.py` | `src/artifacts/match.py` |
| `src/artifact_profile.py` | `src/artifacts/profile.py` |
| `src/autonomous_loop.py` | `src/orchestration/autonomous_loop.py` |
| `src/claims/report.py` | `src/report/claims_report.py` |
| `src/cli.py` | `src/cli/main.py` |
| `src/cli_claims.py` | `src/cli/claims.py` |
| `src/cli_graph.py` | `src/cli/graph.py` |
| `src/cli_opportunities.py` | `src/cli/opportunities.py` |
| `src/cli_project.py` | `src/cli/project.py` |
| `src/cli_provenance.py` | `src/cli/provenance.py` |
| `src/context_loader.py` | `src/research_data/context_loader.py` |
| `src/continuity.py` | `src/session/continuity.py` |
| `src/egress/fragments.py` | `src/utils/egress_fragments.py` |
| `src/embeddings/reindex.py` | `src/documents/reindex.py` |
| `src/exploration.py` | `src/orchestration/exploration.py` |
| `src/health.py` | `src/host/health.py` |
| `src/heartbeat.py` | `src/session/heartbeat.py` |
| `src/history.py` | `src/session/history.py` |
| `src/human_gate.py` | `src/gate/human_gate.py` |
| `src/infrastructure.py` | `src/cli/infrastructure.py` |
| `src/knowledge/normalization.py` | `src/utils/normalization.py` |
| `src/llm_cache.py` | `src/llm/cache.py` |
| `src/metrics_file.py` | `src/artifacts/metrics_file.py` |
| `src/model_config.py` | `src/llm/model_config.py` |
| `src/model_router.py` | `src/llm/model_router.py` |
| `src/operation_metrics.py` | `src/report/operation_metrics.py` |
| `src/orchestrator.py` | `src/orchestration/orchestrator.py` |
| `src/output_manager.py` | `src/artifacts/output_manager.py` |
| `src/pipeline_errors.py` | `src/orchestration/errors.py` |
| `src/plan_normalizer.py` | `src/orchestration/plan_normalizer.py` |
| `src/platform_images.py` | `src/host/platform_images.py` |
| `src/platform_info.py` | `src/host/platform_info.py` |
| `src/project_session.py` | `src/cli/project_session.py` |
| `src/prompts.py` | `src/agents/prompts.py` |
| `src/rate_limiter.py` | `src/llm/rate_limiter.py` |
| `src/reserved_files.py` | `src/artifacts/reserved_files.py` |
| `src/resume.py` | `src/session/resume.py` |
| `src/session.py` | `src/session/manager.py` |
| `src/skills/code/manifest.py` | `src/utils/workspace_manifest.py` |
| `src/skills/document_processor/chunker.py` | `src/documents/chunker.py` |
| `src/skills/document_processor/descriptors.py` | `src/documents/descriptors.py` |
| `src/skills/document_processor/enrichment.py` | `src/documents/enrichment.py` |
| `src/skills/document_processor/extractors/` | `src/documents/extractors/` |
| `src/skills/document_processor/extractors/base.py` | `src/documents/extractors/base.py` |
| `src/skills/document_processor/extractors/csv_extractor.py` | `src/documents/extractors/csv_extractor.py` |
| `src/skills/document_processor/extractors/docling_extractor.py` | `src/documents/extractors/docling_extractor.py` |
| `src/skills/document_processor/extractors/fallback_extractor.py` | `src/documents/extractors/fallback_extractor.py` |
| `src/skills/document_processor/extractors/registry.py` | `src/documents/extractors/registry.py` |
| `src/skills/document_processor/extractors/text_extractor.py` | `src/documents/extractors/text_extractor.py` |
| `src/skills/document_processor/indexer.py` | `src/documents/indexer.py` |
| `src/skills/document_processor/pipeline.py` | `src/documents/pipeline.py` |
| `src/skills/document_processor/registry_store.py` | `src/documents/registry_store.py` |
| `src/subtask_output.py` | `src/artifacts/subtask_output.py` |
| `src/task_scheduler.py` | `src/orchestration/task_scheduler.py` |
| `src/telemetry.py` | `src/observability/telemetry.py` |
| `src/triage.py` | `src/orchestration/triage.py` |
| `src/unlimited_mode.py` | `src/orchestration/unlimited_mode.py` |
| `src/usage.py` | `src/orchestration/usage.py` |
| `agents/<subpacote>/...` (todo o pacote da raiz) | `src/agents/<subpacote>/...` |

O `src/skills/document_processor/` passa a conter só `__init__.py` e `skill.py` (a ferramenta de agente), que importam de `src/documents/`. O manifesto do espaço de trabalho (`skills/code/manifest.py`) vai para `src/utils/workspace_manifest.py`, e não para `src/artifacts/` como a tabela do ADR 024 previa: ele só depende de `logger`, e em `artifacts` formaria o ciclo `llm` → `artifacts` → `egress` → `llm` (achado da simulação; o ADR registra o ajuste). O `src/session/` usa `manager.py` para o antigo `src/session.py` (classe `SessionManager`), porque o nome do pacote e o do módulo coincidiriam.

### 2.2 Definições movidas sem alterar o corpo

| Definição (módulo antigo) | Módulo novo |
|---|---|
| `_METRIC_ALIASES`, `_metric_key`, `MetricCriterion`, `_comparisons`, `_metric_criteria`, `_OPERATORS`, `_compare`, `_group_named`, `_evaluate_comparison`, `_evaluate_comparison_found`, `_evaluate_metric_criteria`, `evaluated_metric_names`, `Comparison` (`src/agents/validator_agent.py`) | `src/knowledge/metric_criteria.py` |
| `Checkpoint` (`src/continuity.py`) | sob `TYPE_CHECKING` (só anotação) |
| `ST_CONCLUIDA`, `ST_EM_ANDAMENTO`, `ST_PENDENTE`, `ST_ABANDONADA`, `ST_FALHOU` (`src/continuity.py`) | `src/knowledge/subtask_states.py` |
| `_make_client` (`src/embeddings/reindex.py`) | `src/utils/qdrant.py` |
| `get_or_create_node_id`, `generate_node_id`, `_node_id_config_dir`, `uuid7` (`src/knowledge/ids.py`) | `src/utils/node_id.py` |
| `insumo_tipo` (`src/knowledge/ingestion.py`) | `src/documents/hashing.py` |
| `sha256_file`, `MAX_HASH_BYTES` (`src/knowledge/ingestion_io.py`) | `src/documents/hashing.py` |
| `AgentResult`, `AgentTask` (`src/orchestrator.py`) | `src/agent_runtime/types.py` |

Cada definição leva junto as auxiliares privadas que só ela usa; o módulo de origem passa a importá-la do módulo novo quando ainda precisar dela (importação para baixo, permitida). A lista final, com as auxiliares, é conferida na implementação pela verificação de camadas (§3): se faltar uma definição, o ciclo reaparece e a verificação falha.

## 3. Contrato de camadas

O contrato fica em `pyproject.toml` (seção da ferramenta) e lista os pacotes de cima para baixo. A ordem saiu da simulação do grafo depois das movimentações (altura de cada pacote no grafo de dependências, sem o ciclo da Etapa 2). Pacotes na mesma linha não têm ordem entre si, mas também não podem formar ciclo:

1. `src.cli`
2. `src.orchestration`
3. `src.agent_runtime`
4. `src.agents`
5. `src.report`, `src.session`
6. `src.claims`, `src.skills`
7. `src.knowledge`
8. `src.numeric_refs`
9. `src.provenance`, `src.research_data`
10. `src.artifacts`, `src.documents`, `src.llm`
11. `src.egress`, `src.embeddings`, `src.gate`, `src.host`, `src.observability`
12. `src.research_consult`, `src.utils`, `src.config`, `src.logger`, `src.db`

Nesta etapa, `src.egress` fica abaixo de `src.llm` porque é o sentido da maioria das importações atuais; a ordem final, depois de `v18.7-layer-cycles`, põe `src.egress` acima de `src.llm` (o gate envolve o provedor) e está no design daquela mudança.

Regras do contrato:

- importações dentro de funções contam; as que estão sob `TYPE_CHECKING` não contam (opção da ferramenta para excluir importações de verificação de tipos);
- **exceção inicial única:** `src.egress.gate` → `src.llm.base`, `src.llm.session`, `src.llm.allocation`, e o caminho de volta (`src.llm.model_router`, `src.llm.vision`, `src.llm.metering` → `src.egress.gate`), declarada nominalmente como importação ignorada, com comentário que aponta para `v18.7-layer-cycles`;
- a verificação roda com `uv run lint-imports` junto com `uv run ruff check .` e com os testes; um teste `unit` chama a ferramenta e falha se o contrato quebrar, para que a regra valha também no CI e no Pi.

Novos módulos da V18.7 entram no pacote do seu assunto; um pacote novo exige atualizar o contrato no mesmo PR.

## 4. Procedimento

1. Branch `refactor/source-layout`, worktree própria, com nenhuma outra branch com código Python aberta (ADR 024 §1).
2. Movimentações com `git mv`, num commit só de movimentação, para o histórico seguir os arquivos (`git log --follow`).
3. Movimentação das definições da §2.2 em commit próprio.
4. Reescrita das importações por script (mapa da §2), em `src/`, `scripts/` e `tests/`, incluindo as importações dentro de funções, `importlib.import_module("...")` e alvos de `patch`/`monkeypatch` escritos como texto (155 alvos para módulos da raiz, mais os de `agents.*`).
5. Busca textual pelos caminhos antigos (`src.<módulo antigo>`, `"agents.`, `src/<módulo antigo>.py`) em todo o repositório fora de `docs/`, `openspec/changes/archive/` e ADRs; cada ocorrência restante é corrigida ou justificada no PR.
6. Caminhos calculados a partir de `__file__`: `src/cli.py:21` (`sys.path`), `src/platform_images.py:29` (`PROJECT_ROOT`, usado por `scripts/setup_pi.sh:28` e `scripts/platform_images.py:23`), e qualquer outro em módulo movido; `src/knowledge/vocabulary.py:40`, `src/llm/catalog.py:33-34` e `src/skills/code/skill.py:38` não se movem, mas entram no teste de arquivos de dados.
7. `pyproject.toml`: ponto de entrada e contrato de camadas; `uv add --dev import-linter`.
8. Documentação: `AGENTS.md` §7, `README.md`, `.agents/`, `openspec/project.md`, `openspec/specs/`, tabela no roadmap V18.7.
9. Suíte inteira, `ruff`, contrato de camadas; depois do merge, `uv sync` e `uv run geminiclaw --help` no Mac e no Raspberry Pi.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Arquitetura | Pacotes por responsabilidade e contrato de camadas; um ciclo restante, com dono. |
| Dados e schema | Nenhum. |
| Segurança | Nenhuma barreira muda de lugar lógico; o filtro de egresso continua envolvendo todo provedor. Risco: um alvo de `patch` que ainda resolve por acaso vira mock silencioso; mitigado pela busca textual e pela ausência de módulos de compatibilidade. |
| Desempenho e recursos no Pi | Nenhum em execução; importação igual. |
| Operação | `uv sync` depois do merge; scripts do Pi (`setup_pi.sh`) conferidos. |
| Testes | Só caminhos mudam; testes novos de estrutura e de contrato. |

## 6. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.** Nenhuma barreira muda de lugar lógico: `src/egress/gate.py`, `src/llm/providers/`, `src/skills/code/sandbox.py` e o `ContextLoader` com `authorize_vision` continuam os mesmos, e a imagem do sandbox não copia `src/` nem `agents/` (`containers/sandbox/Dockerfile` copia só `requirements.lock`). Os riscos estão nos caminhos calculados e nos testes que citam caminhos como texto. As ressalvas L1 a L3 são requisitos desta mudança, com cenário na spec e tarefa.

- **L1 (alta) — `sys.path` com `src/` depois da movimentação.** `src/cli.py:21` põe `Path(__file__).parent.parent` no `sys.path`. Em `src/cli/main.py`, a mesma expressão aponta para `src/`: os pacotes passariam a ser importáveis com dois nomes (`egress.gate` e `src.egress.gate`), cada um com o seu estado de módulo (portão corrente `_current_gate`, portão `sem_sessao`, registro de provedores, cache do roteador), e `import agents` voltaria a funcionar apontando para `src/agents/`. Um módulo importado pelo nome curto usaria outro portão e outro registro, fora do que os testes conferem. Requisito: a raiz inserida é a do repositório (`Path(__file__).resolve().parents[2]`), `src/` não entra no `sys.path`, e `src/host/platform_images.py` calcula `PROJECT_ROOT` com a mesma raiz.
- **L2 (média) — testes de segurança que citam caminhos como texto.** `tests/unit/egress/test_wiring.py` compara caminhos relativos: `if rel == "src/context_loader.py": assert "authorize_vision" in text` deixa de executar se o caminho não for reescrito (a verificação da visão fica mais fraca sem falhar), e `"src/model_router.py"` está na lista do `create_provider`. A busca textual da tarefa 4.2 acusa esses textos em `tests/`; o requisito é que eles sejam reescritos para `src/research_data/context_loader.py` e `src/llm/model_router.py`, e um teste de estrutura confere que esses caminhos estão citados em `test_wiring.py` e existem.
- **L3 (média) — alvo de `patch` de definição movida que vira mock que não age.** As definições da §2.2 continuam importadas pelo módulo de origem. Um alvo `patch("src.session.continuity.ST_CONCLUIDA")` (o módulo reescrito, com o nome antigo da definição) troca o nome no módulo de origem, mas o código que usa a definição a lê do módulo novo: o teste segue rodando com o valor real. Requisito: nenhum alvo de `patch`/`monkeypatch` em `tests/` aponta para uma definição da §2.2 no módulo de origem; todos apontam para o módulo novo ou para o módulo que a usa.
- **Registro:** `src/skills/code/sandbox.py` calcula a raiz do repositório com `parents[3]` para `SANDBOX_WORK_DIR` e para a limpeza de diretórios órfãos (que apaga diretórios). O módulo não se move; o teste de arquivos de dados confere que essa raiz é a do repositório, para que uma movimentação futura não aponte a limpeza para outro diretório.
- **Registro:** os nomes de logger mudam com o módulo (`get_logger(__name__)`); não há filtro de redação por nome de logger em `src/logger.py`, então nenhum segredo passa a ser registrado por isso.

## 7. Riscos e mitigações

- **Conflito com branches abertas:** a Etapa 1 só começa sem outra branch com código Python aberta, e as mudanças da V18.7 começam depois do merge.
- **Mock silencioso por alvo de `patch` antigo:** sem módulos de compatibilidade, um alvo antigo falha com `ModuleNotFoundError`/`AttributeError`; a busca textual cobre os casos de alvo que ainda existiria.
- **Arquivo de dados perdido:** teste que confere a existência dos arquivos apontados por caminhos calculados a partir de `__file__`.
- **Pacotes importáveis com dois nomes:** raiz do `sys.path` conferida por teste (§6, L1).
- **Verificação de segurança enfraquecida sem falhar:** caminhos citados em `test_wiring.py` e alvos de `patch` de definições movidas conferidos por teste (§6, L2 e L3).
- **Ciclo novo escondido:** a verificação de camadas falha no próprio PR.

## 8. Questões em aberto

Nenhuma decisão do pesquisador pendente; o ADR 024 foi aprovado em 2026-10-15.
