# Roadmap V18.7 — Exploração Rastreável, Contrato de Contexto e Pesquisa em Segundo Plano

> **Estado (2026-10-15):** mudanças OpenSpec escritas e em revisão; nenhuma implementada. ADRs 021, 022, 023 e 024 aprovados.

## Objetivo

Fazer os agentes explorarem livremente, com toda exploração rastreável até uma hipótese, e tornar o sistema usável em explorações longas. A etapa nasce da bateria V18.6 ([`docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md`](../docs/benchmarks/2026-10-15-bateria-v18-6-resultados.md)), em que nenhuma combinação fechou por solução encontrada:

- planos esvaziados pela governança (pré-processamento e baseline retirados por falta de hipótese, com cascata de retiradas);
- o Developer não recebia o contrato da subtarefa (critérios, artefatos esperados, hipótese, critério do Problema);
- o laço replanejava em erro de cota do provedor; a cadeia de proveniência saía divergente com retentativas; o relatório comparava o limite de egresso com o total errado;
- o REPL ficava ocupado durante a pesquisa, e decisões do pesquisador liam o terminal de dentro da sessão.

ADRs de origem: [021](../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) (exploração rastreável por hipóteses), [022](../docs/decisions/adr_022_contrato_contexto_por_chamada.md) (contrato de contexto por chamada e regimento da pesquisa), [023](../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) (pesquisa em segundo plano) e [024](../docs/decisions/adr_024_organizacao_do_codigo.md) (organização do código).

## Decisões do pesquisador (2026-10-15)

- Hipóteses rejeitadas pelo pesquisador não são executadas; toda exploração nasce de uma hipótese, e não há nós soltos no grafo.
- Sem teto de hipóteses ou de ciclos; os limites são de custo, tokens, tempo e egresso, configuráveis e desligáveis pelo pesquisador; a parada é pelo objetivo do Problema, conforme o tipo.
- No `assisted`, o sistema aguarda o pesquisador; no `semi` e no `auto`, segue por decisão do Researcher e do Validator.
- O Developer recebe a cada chamada o prompt do papel e o contrato da subtarefa; um regimento comum da pesquisa, sem emojis e direto, é consultado por todos os agentes.
- A pesquisa roda em segundo plano; nos modos autônomos vai até o fim e encerra o processo; no `assisted`, suspende quando o terminal fecha e pergunta pela retomada ao abrir a aplicação.
- Nada de configuração atrelada ao Raspberry Pi; várias pesquisas disputando a máquina ficam para depois.

## Dependências

- V18.6 arquivada (atendido em 2026-10-14).
- Nenhuma outra branch com código Python aberta durante a Tarefa 0 (ADR 024 §1).

## Tarefas

### Tarefa 0: Organização do código (ADR 024)
- **Specs:** [`v18.7-source-layout`](../openspec/changes/v18.7-source-layout/proposal.md) e, logo depois, [`v18.7-layer-cycles`](../openspec/changes/v18.7-layer-cycles/proposal.md)
- **Critérios de aceite:** [ ] raiz de `src/` só com `__init__.py`, `config.py`, `logger.py`, `db.py` · [ ] suíte inteira verde sem alterar asserções · [ ] regra de camadas verificada a cada commit · [ ] lista de exceções vazia ao fim de `v18.7-layer-cycles`
- **Complexidade estimada:** Alta (volume), baixa em lógica

### Tarefa 1: Correções da bateria V18.6
- **Spec:** [`v18.7-benchmark-fixes`](../openspec/changes/v18.7-benchmark-fixes/proposal.md)
- **Critérios de aceite:** [ ] erro de cota ou de teto de gasto encerra a sessão com `limite_cota_provedor` e checkpoint, sem replanejar · [ ] retentativas não tornam a cadeia de proveniência divergente · [ ] relatório compara o limite de egresso com a categoria que ele limita
- **Complexidade estimada:** Média

### Tarefa 2: Monitor de recursos e configuração sem designação de máquina
- **Spec:** [`v18.7-resource-monitor-config`](../openspec/changes/v18.7-resource-monitor-config/proposal.md)
- **Critérios de aceite:** [ ] leituras em Linux e macOS, desconhecido quando não exposto · [ ] `PI_*` e `DEPLOYMENT_PROFILE` removidos com falha explícita na inicialização · [ ] `AGENT_TIMEOUT_SECONDS=0` sem limite · [ ] `.env` do Pi migrado preservando os valores efetivos
- **Complexidade estimada:** Média

### Tarefa 3: Relações de exploração no grafo
- **Spec:** [`v18.7-graph-exploration-relations`](../openspec/changes/v18.7-graph-exploration-relations/proposal.md)
- **Critérios de aceite:** [ ] `papel` do experimento · [ ] hipótese do sistema com chave estruturada e referência fixada · [ ] `PREPARA`, `REFERENCIA_DE`, `DERIVADA_DE -> Hipotese` · [ ] leitura compatível de nós antigos
- **Complexidade estimada:** Média

### Tarefa 4: Ligação de toda exploração a hipóteses
- **Spec:** [`v18.7-hypothesis-linking`](../openspec/changes/v18.7-hypothesis-linking/proposal.md)
- **Critérios de aceite:** [ ] preparação e referência não são retiradas por falta de hipótese · [ ] hipótese do sistema criada e aprovada conforme o modo · [ ] Researcher recebe as retiradas · [ ] hipótese rejeitada pelo pesquisador nunca executa
- **Complexidade estimada:** Alta

### Tarefa 5: Sessão em processo próprio e gate persistente (entregar juntas)
- **Specs:** [`v18.7-background-sessions`](../openspec/changes/v18.7-background-sessions/proposal.md) e [`v18.7-persistent-human-gate`](../openspec/changes/v18.7-persistent-human-gate/proposal.md)
- **Critérios de aceite:** [ ] `semi`/`auto` rodam até o fim e encerram o processo · [ ] `assisted` suspende sem terminal e pergunta pela retomada · [ ] nenhum caminho da sessão lê a entrada padrão · [ ] só o terminal responde ao gate · [ ] caixa de entrada entregue no replanejamento
- **Complexidade estimada:** Alta

### Tarefa 6: Eventos de progresso e terminal
- **Spec:** [`v18.7-session-events-terminal`](../openspec/changes/v18.7-session-events-terminal/proposal.md)
- **Critérios de aceite:** [ ] eventos gravados na hora e filtrados · [ ] atualizações no REPL sem apagar a digitação · [ ] comandos de acompanhamento e ações imediatas · [ ] consulta só leitura ao Researcher, contada no orçamento da sessão · [ ] texto livre é conversa e `nova <tarefa>` inicia a pesquisa
- **Complexidade estimada:** Média

### Tarefa 7: Limites da exploração e parada pelo objetivo
- **Spec:** [`v18.7-exploration-limits`](../openspec/changes/v18.7-exploration-limits/proposal.md)
- **Critérios de aceite:** [ ] sem teto de hipóteses e ciclos como parada · [ ] limite de custo por sessão (`limite_custo`, padrão US$ 20) · [ ] objetivo tipado e política ao atingir o objetivo · [ ] estagnação como intervenção do Curator e saturação · [ ] restrições por direção
- **Complexidade estimada:** Alta

### Tarefa 8: Contrato da subtarefa
- **Spec:** [`v18.7-subtask-contract`](../openspec/changes/v18.7-subtask-contract/proposal.md)
- **Critérios de aceite:** [ ] Developer recebe o contrato (itens 1 a 9) uma vez por tentativa, em prefixo estável · [ ] critérios de aceite separados das regras de integridade · [ ] chaves `<modelo>.<metrica>` e `criterio_ambiguo` · [ ] contaminação herdada do Researcher
- **Complexidade estimada:** Alta

### Tarefa 9: Regimento da pesquisa e prompts por papel
- **Spec:** [`v18.7-agent-system-prompts`](../openspec/changes/v18.7-agent-system-prompts/proposal.md)
- **Critérios de aceite:** [ ] auditoria de cada prompt contra o código · [ ] regimento v1 comum, injetado por recorte · [ ] versão e hash por sessão · [ ] teste de coerência entre regimento, prompts e código
- **Complexidade estimada:** Alta

### Tarefa 10: Métricas da exploração
- **Spec:** [`v18.7-exploration-metrics`](../openspec/changes/v18.7-exploration-metrics/proposal.md)
- **Critérios de aceite:** [ ] contadores por papel e origem da hipótese · [ ] substituição de `reprovacoes_sem_hipotese` · [ ] hash do contrato por tentativa e tokens do contrato por execução
- **Complexidade estimada:** Baixa

## Ordem de implementação

| Onda | Tarefas | Por quê |
|---|---|---|
| 0 | Tarefa 0 (`source-layout`, depois `layer-cycles`) | Reorganiza antes de qualquer código novo (ADR 024) |
| 1 | Tarefas 1, 2 e 3, em paralelo | Sem dependências entre si |
| 2 | Tarefa 5 (as duas mudanças mergeadas juntas); Tarefa 4 | 5 depende de 2; 4 depende de 3 |
| 3 | Tarefa 7; depois Tarefa 8; Tarefa 6 em paralelo | 7 depende de 1, 2, 3, 4 e 5; 8 depende de 4 e é mergeada depois de 7; 6 depende de 5 |
| 4 | Tarefa 10; por último, Tarefa 9 | 10 depende de 4 e 8; 9 depende de 4, 5, 7 e 8 |

Os motivos de parada e os códigos de saída têm uma tabela única em `v18.7-background-sessions/design.md` §1.4, com cada valor novo atribuído a uma só mudança. O catálogo de pedidos ao gate pertence a `v18.7-persistent-human-gate`. O mecanismo de variáveis removidas (`_REMOVED_VARIABLES`) pertence a `v18.7-resource-monitor-config`.

As ajudas de teste compartilhadas são criadas pela primeira mudança que precisa delas e reaproveitadas pelas seguintes: provedor simulado com respostas roteirizadas e erros de cota (Tarefa 1); leituras de recursos simuladas e importação isolada de `src.config` (Tarefa 2); construtores de grafo em memória (Tarefa 3); processo de sessão de teste, relógio controlável, PostgreSQL com o papel do terminal e REPL com entrada simulada (Tarefa 5); gate simulado com a interface comum de aprovação (Tarefa 5).

As mudanças foram escritas antes da reorganização do código: os caminhos de arquivo citados nelas valem pela tabela abaixo (cópia de `v18.7-source-layout`, design §2). Cada uma das mudanças que alteram `autonomous_loop`, `orchestrator`, `cli/main` ou `human_gate` começa pela divisão do módulo (tarefa 0.9, ADR 024 §5).

### Caminho antigo → caminho novo

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

| Definição (módulo antigo) | Módulo novo |
|---|---|
| `_METRIC_ALIASES`, `_metric_key`, `MetricCriterion`, `_comparisons`, `_metric_criteria`, `_OPERATORS`, `_compare`, `_group_named`, `_evaluate_comparison`, `_evaluate_comparison_found`, `_evaluate_metric_criteria`, `evaluated_metric_names`, `Comparison` (`src/agents/validator_agent.py`) | `src/knowledge/metric_criteria.py` |
| `Checkpoint` (`src/continuity.py`) | sob `TYPE_CHECKING` (só anotação) |
| `ST_CONCLUIDA`, `ST_EM_ANDAMENTO`, `ST_PENDENTE`, `ST_ABANDONADA`, `ST_FALHOU` (`src/continuity.py`) | `src/knowledge/subtask_states.py` |
| `_make_client` (`src/embeddings/reindex.py`) | `src/utils/qdrant.py` |
| `get_or_create_node_id`, `generate_node_id`, `_node_id_config_dir`, `uuid7` (`src/knowledge/ids.py`) | `src/utils/node_id.py` |
| `insumo_tipo` (`src/knowledge/ingestion.py`) | `src/documents/hashing.py` |
| `sha256_file`, `MAX_HASH_BYTES` (`src/knowledge/ingestion_io.py`) | `src/documents/hashing.py` |
| `AgentResult`, `AgentTask` (`src/orchestrator.py`) | `src/agent_runtime/types.py` | Cada desenvolvedor confere a spec com o código antes de começar (AGENTS.md §1.10).

## Aprovações necessárias

Listadas em cada `proposal.md`, em resumo:

- **Schema do banco:** colunas novas em `agent_sessions`; tabelas `terminal_presence`, `gate_requests`, `session_inbox`, `session_events`; gatilhos; papel de banco do terminal (Tarefa 5 e 6).
- **Schema do grafo:** papéis e propriedades de `Experimento` e `Hipotese`, `PREPARA`, `REFERENCIA_DE`, `DERIVADA_DE -> Hipotese`, nó `Restricao` com `RESTRINGE`, valores novos de `Sessao.motivo_parada` (Tarefas 1, 3, 5 e 7).
- **Dependência nova:** `psutil` (Tarefa 2); ferramenta de contratos de importação (Tarefa 0).
- **Configuração:** remoção de variáveis com falha na inicialização e migração de todo `.env`, inclusive o do Pi (Tarefas 2 e 7).
- **Texto do regimento v1** e a decisão reservada nova para o adendo de projeto (Tarefa 9).
- **`AGENTS.md`** e remoção de `agents/` da raiz (Tarefa 0).

## Cenários para testes futuros

Anotados a pedido do pesquisador (2026-10-15); nenhum bloqueia a V18.7.

- **Limiar mascarado para o Developer** (`v18.7-subtask-contract`, design §11.1): Researcher local (aceita dados brutos) e Developer de nuvem sobre dados sintéticos tratados como confidenciais, comparado a um Developer auto-hospedado; medir o sucesso do Developer com o limiar mascarado. Exige o caso de pesquisa e os dados sintéticos que o pesquisador pretende construir.
- **Dados completos para o Developer:** pesquisas que exigem olhar registros, texto, imagem ou espectros, com Developer auto-hospedado.
- **Políticas de parada na bateria:** `ON_PLAN_REJECTIONS=parar` e `ON_MODEL_VERSION_CHANGE=parar` no benchmark; no uso normal, `explorar` e `retomar` (troca de versão com checkpoint e retomada, ou substituição por outro modelo previsto no catálogo).
- **Calibração do veredito:** ADR 025.

## Validação da Etapa

- [ ] Todos os testes unitários e de integração passam, com a regra de camadas.
- [ ] Bateria curta no Raspberry Pi 5 e em outra máquina, só com confirmação do pesquisador.
- [ ] Revisões do Analista de Segurança concluídas.
- [ ] ADRs 021 a 024 marcados como Aceitos.
- [ ] PRs mergeados em `dev`; mudanças arquivadas.
