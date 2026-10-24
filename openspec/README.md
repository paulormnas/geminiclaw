# OpenSpec — Especificações Orientadas a Mudanças

Este diretório segue a abordagem [OpenSpec](https://github.com/Fission-AI/OpenSpec): cada
mudança do sistema é especificada **antes** da implementação, em um pacote autocontido que
qualquer agente consegue implementar sem reler toda a conversa que originou a decisão.

> A ferramenta CLI do OpenSpec (Node.js) **não** é usada por enquanto: seguimos apenas a
> estrutura e o formato, validados na revisão. JavaScript/TypeScript é permitido pelo
> AGENTS.md somente no frontend; adotar a CLI exigiria decisão própria.

---

## Estrutura

```
openspec/
├── README.md          ← este arquivo: como ler, implementar e arquivar specs
├── project.md         ← contexto do projeto e convenções válidas para toda spec
├── specs/             ← verdade atual do sistema, por capacidade (preenchido ao arquivar)
└── changes/
    ├── <id-da-mudanca>/
    │   ├── proposal.md    ← Por quê, o que muda, impacto, ADRs de origem
    │   ├── design.md      ← Decisões técnicas, contratos, análise de impacto, riscos
    │   ├── tasks.md       ← Checklist ordenado de implementação e testes
    │   └── specs/<capacidade>/spec.md  ← requisitos (deltas) com cenários verificáveis
    └── archive/           ← mudanças concluídas (movidas após merge)
```

## Formato dos requisitos

Os marcadores estruturais ficam em inglês (padrão OpenSpec); o conteúdo, em português.

```markdown
## ADDED Requirements

### Requirement: <nome curto>
O sistema SHALL <comportamento obrigatório>.

#### Scenario: <situação>
- **GIVEN** <estado inicial>          (opcional)
- **WHEN** <ação ou evento>
- **THEN** <resultado verificável>
- **AND** <resultado adicional>        (opcional)
```

- `SHALL` / `MUST` = obrigatório; `SHOULD` = recomendado; `MAY` = opcional.
- Todo requisito tem **ao menos um cenário**. Cada cenário vira ao menos um teste.
- Seções possíveis: `## ADDED Requirements`, `## MODIFIED Requirements`,
  `## REMOVED Requirements`.

## Ciclo de vida de uma mudança

1. **Proposta** — o Arquiteto escreve os quatro arquivos (`architect.md`).
2. **Revisão** — Analista de Segurança (quando a mudança toca sandbox, rede, permissões ou
   banco) e aprovação do pesquisador responsável.
3. **Implementação** — um worktree por mudança, seguindo `.agents/workflows/new-feature.md`;
   as caixas de `tasks.md` são marcadas no próprio PR.
4. **Arquivamento** — após o merge em `dev`, a pasta vai para `changes/archive/` e os
   requisitos são consolidados em `specs/<capacidade>/spec.md`.

## Mudanças

**Arquivadas em 2026-10-13 e 2026-10-14:** as 32 mudanças de V16 a V18.5 e as 8 da V18.6 (links para
`changes/archive/`), com os requisitos consolidados em [`specs/`](specs/README.md) e os itens
abertos em [`changes/archive/PENDENCIAS.md`](changes/archive/PENDENCIAS.md). **Arquivadas em 2026-10-18:** 8 mudanças da V18.7 (`v18.7-source-layout`, `v18.7-layer-cycles`, `v18.7-graph-exploration-relations`, `v18.7-resource-monitor-config`, `v18.7-benchmark-fixes`, `v18.7-hypothesis-linking`, `v18.7-persistent-human-gate` e `v18.7-exploration-limits`), com os requisitos consolidados em [`specs/`](specs/README.md) e as pendências conhecidas em [`changes/archive/PENDENCIAS.md`](changes/archive/PENDENCIAS.md). Em aberto: 6 mudanças da V18.7 (`v18.7-background-sessions`, com a confirmação na bateria pendente; `v18.7-subtask-contract`, implementada em 2026-10-18 e à espera da bateria para o arquivamento; `v18.7-dependency-artifacts`, especificada em 2026-10-18; e as não iniciadas `v18.7-agent-system-prompts`, `v18.7-exploration-metrics` e `v18.7-session-events-terminal`; roadmap [`roadmap_V18.7.md`](../roadmaps/roadmap_V18.7.md)), V19 e V20.

| Versão | Mudança | Capacidade | ADRs | Depende de |
|---|---|---|---|---|
| V16 | [v16-provider-registry](changes/archive/v16-provider-registry/proposal.md) | `llm-providers` | 011 | — |
| V16 | [v16-anthropic-provider](changes/archive/v16-anthropic-provider/proposal.md) | `llm-providers` | 011 | v16-provider-registry |
| V16 | [v16-local-embeddings](changes/archive/v16-local-embeddings/proposal.md) | `embeddings` | 011 | — |
| V16 | [v16-in-process-agents](changes/archive/v16-in-process-agents/proposal.md) | `agent-runtime` | 014 | v16-provider-registry |
| V16 | [v16-research-assistant-prompts](changes/archive/v16-research-assistant-prompts/proposal.md) | `agent-prompts` | 010, 011 | v16-in-process-agents |
| V16 (robustez) | [v16-pipeline-robustness](changes/archive/v16-pipeline-robustness/proposal.md) | `pipeline-robustness` | 002, 010 | v16-in-process-agents (implementada) |
| V16 (robustez) | [v16-agent-communication-eval](changes/archive/v16-agent-communication-eval/proposal.md) | `communication-eval` | 012, 002, 019, 011 | v16-pipeline-robustness |
| V16 (complemento) | [v16-model-catalog-router](changes/archive/v16-model-catalog-router/proposal.md) | `llm-providers` | 017, 011 | v16-provider-registry |
| V16 (complemento) | [v16-sandbox-slim-image](changes/archive/v16-sandbox-slim-image/proposal.md) | `code-sandbox` | 018, 014, 003 | v16-in-process-agents |
| V16 (complemento) | [v16-platform-images](changes/archive/v16-platform-images/proposal.md) | `platform-images` | 018 | v16-sandbox-slim-image |
| V17 | [v17-graph-store](changes/archive/v17-graph-store/proposal.md) | `knowledge-graph` | 009, 015 | V16 |
| V17 | [v17-controlled-vocabulary](changes/archive/v17-controlled-vocabulary/proposal.md) | `vocabulary` | 015 | v17-graph-store |
| V17 | [v17-evidence-verdict](changes/archive/v17-evidence-verdict/proposal.md) | `evidence-scoring` | 015 | — (módulo puro) |
| V17 | [v17-research-project](changes/archive/v17-research-project/proposal.md) | `research-project` | 015 | v17-graph-store, v17-controlled-vocabulary |
| V17 | [v17-structural-fact-ingestion](changes/archive/v17-structural-fact-ingestion/proposal.md) | `knowledge-ingestion` | 009, 015 | v17-research-project |
| V17 | [v17-knowledge-semantic-index](changes/archive/v17-knowledge-semantic-index/proposal.md) | `knowledge-semantics` | 011, 015 | v16-local-embeddings, v17-graph-store |
| V17 | [v17-domain-search](changes/archive/v17-domain-search/proposal.md) | `domain-search` | 015, 011, 012 | v17-controlled-vocabulary, v17-knowledge-semantic-index |
| V17 | [v17-curator-agent](changes/archive/v17-curator-agent/proposal.md) | `curator` | 012, 015 | todas as anteriores de V17 |
| V17 | [v17-graph-cli](changes/archive/v17-graph-cli/proposal.md) | `graph-cli` | 015 | v17-graph-store, v17-curator-agent |
| V17 | [v17-input-document-index](changes/archive/v17-input-document-index/proposal.md) | `input-documents` | 015, 011, 019 | v16-local-embeddings, v17-research-project, v17-structural-fact-ingestion |
| V18 | [v18-usage-limits](changes/archive/v18-usage-limits/proposal.md) | `usage-limits` | 010, 012 | V16 |
| V18 | [v18-research-continuity](changes/archive/v18-research-continuity/proposal.md) | `session-continuity` | 010 | v18-usage-limits, v17-structural-fact-ingestion |
| V18 | [v18-hypothesis-loop](changes/archive/v18-hypothesis-loop/proposal.md) | `hypothesis-loop` | 010, 012 | V17, v18-usage-limits, v18-research-continuity |
| V18 | [v18-researcher-consult](changes/archive/v18-researcher-consult/proposal.md) | `researcher-consult` | 012, 010, 019 | v18-usage-limits |
| V18.5 | [v18.5-model-catalog-locality](changes/archive/v18.5-model-catalog-locality/proposal.md) | `llm-providers` | 019, 017 | V18, v16-model-catalog-router |
| V18.5 | [v18.5-egress-gate](changes/archive/v18.5-egress-gate/proposal.md) | `data-egress` | 019, 014 | v18.5-model-catalog-locality |
| V18.5 | [v18.5-research-data-ingestion](changes/archive/v18.5-research-data-ingestion/proposal.md) | `research-data` | 019 | v18.5-egress-gate (entregar junto) |
| V18.5 | [v18.5-sandbox-phases](changes/archive/v18.5-sandbox-phases/proposal.md) | `code-sandbox` | 019, 014, 018 | V18, v16-sandbox-slim-image |
| V18.5 | [v18.5-execution-provenance](changes/archive/v18.5-execution-provenance/proposal.md) | `execution-provenance` | 019, 015 | v18.5-sandbox-phases, v17-research-project |
| V18.5 | [v18.5-numeric-references](changes/archive/v18.5-numeric-references/proposal.md) | `numeric-provenance` | 019 | v18.5-execution-provenance |
| V18.5 | [v18.5-claim-verification](changes/archive/v18.5-claim-verification/proposal.md) | `claim-verification` | 019, 015 | v18.5-numeric-references, v18.5-model-catalog-locality |
| V18.5 | [v18.5-operation-metrics](changes/archive/v18.5-operation-metrics/proposal.md) | `operation-metrics` | 019 | v18.5-egress-gate, v18.5-execution-provenance, v18.5-claim-verification |
| V18.6 | [v18.6-review-evidence](changes/archive/v18.6-review-evidence/proposal.md) | `pipeline-robustness` | 002, 010, 019 | — |
| V18.6 | [v18.6-benchmark-harness](changes/archive/v18.6-benchmark-harness/proposal.md) | `benchmark` | 005, 009, 010, 020 | — (item de juiz: v18.6-validator-independence) |
| V18.6 | [v18.6-validator-independence](changes/archive/v18.6-validator-independence/proposal.md) | `llm-providers` | 020, 017, 019 | ADR 020 (aprovado) |
| V18.6 | [v18.6-hypothesis-closure](changes/archive/v18.6-hypothesis-closure/proposal.md) | `hypothesis-loop` | 009, 010, 012, 015, 019 | v18.6-review-evidence |
| V18.6 | [v18.6-remove-unused-agents](changes/archive/v18.6-remove-unused-agents/proposal.md) | `agent-runtime`, `llm-providers`, `communication-eval` | 007, 020 | v18.6-validator-independence |
| V18.6 | [v18.6-profile-hardening](changes/archive/v18.6-profile-hardening/proposal.md) | `pipeline-robustness`, `data-egress` | 019 | v18.6-review-evidence |
| V18.6 | [v18.6-auto-metrics-and-stop-reasons](changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md) | `hypothesis-loop`, `vocabulary`, `operation-metrics`, `benchmark` | 010, 012, 015, 020 | v18.6-hypothesis-closure |
| V18.6 | [v18.6-models-gemini4-gpt6](changes/archive/v18.6-models-gemini4-gpt6/proposal.md) | `llm-providers`, `benchmark` | 017, 019, 020 | v18.6-benchmark-harness, v18.6-validator-independence |
| V18.7 | [v18.7-source-layout](changes/archive/v18.7-source-layout/proposal.md) | `project-structure` (nova) | 024 | — (onda 0, antes de todas) |
| V18.7 | [v18.7-layer-cycles](changes/archive/v18.7-layer-cycles/proposal.md) | `project-structure`, `data-egress`, `llm-providers` | 024, 019, 017 | v18.7-source-layout |
| V18.7 | [v18.7-benchmark-fixes](changes/archive/v18.7-benchmark-fixes/proposal.md) | `llm-providers`, `usage-limits`, `session-continuity`, `execution-provenance`, `operation-metrics`, `benchmark` | 011, 017, 019 (correção) | — |
| V18.7 | [v18.7-resource-monitor-config](changes/archive/v18.7-resource-monitor-config/proposal.md) | `agent-runtime`, `llm-providers`, `operation-metrics` | 023 | — |
| V18.7 | [v18.7-graph-exploration-relations](changes/archive/v18.7-graph-exploration-relations/proposal.md) | `knowledge-graph` | 021 | — |
| V18.7 | [v18.7-background-sessions](changes/v18.7-background-sessions/proposal.md) | `session-continuity`, `benchmark` | 023 | v18.7-resource-monitor-config; mergeada com v18.7-persistent-human-gate |
| V18.7 | [v18.7-persistent-human-gate](changes/archive/v18.7-persistent-human-gate/proposal.md) | `researcher-consult`, `hypothesis-loop` | 023 | v18.7-background-sessions (mergeadas juntas) |
| V18.7 | [v18.7-hypothesis-linking](changes/archive/v18.7-hypothesis-linking/proposal.md) | `hypothesis-loop`, `pipeline-robustness` | 021 | v18.7-graph-exploration-relations |
| V18.7 | [v18.7-exploration-limits](changes/archive/v18.7-exploration-limits/proposal.md) | `hypothesis-loop`, `usage-limits`, `agent-runtime`, `operation-metrics`, `benchmark`, `session-continuity`, `research-project`, `knowledge-graph`, `researcher-consult`, `pipeline-robustness` | 021 | v18.7-graph-exploration-relations, v18.7-hypothesis-linking, v18.7-background-sessions, v18.7-persistent-human-gate, v18.7-resource-monitor-config, v18.7-benchmark-fixes |
| V18.7 | [v18.7-session-events-terminal](changes/v18.7-session-events-terminal/proposal.md) | `session-continuity`, `researcher-consult` | 023, 019 | v18.7-background-sessions, v18.7-persistent-human-gate |
| V18.7 | [v18.7-subtask-contract](changes/v18.7-subtask-contract/proposal.md) | `agent-prompts`, `pipeline-robustness`, `data-egress` | 022 | v18.7-hypothesis-linking (mergeada depois de v18.7-exploration-limits) |
| V18.7 | [v18.7-dependency-artifacts](changes/v18.7-dependency-artifacts/proposal.md) | `code-sandbox`, `agent-prompts`, `execution-provenance` | 022 (§9), 014, 018, 019 | v18.7-subtask-contract |
| V18.8 | [v18.8-verdict-lab](changes/v18.8-verdict-lab/proposal.md) | `evidence-scoring`, `benchmark` | 025, 015 | — (especificada em 2026-10-18; aguarda aprovação) |
| V18.8 | [v18.8-verdict-calibration](changes/v18.8-verdict-calibration/proposal.md) | `evidence-scoring`, `hypothesis-loop` | 025, 015, 021 | v18.8-verdict-lab (mergeada); implementada em 2026-10-19 |
| V18.8 | [v18.8-verdict-controlled-sessions](changes/v18.8-verdict-controlled-sessions/proposal.md) | `benchmark`, `evidence-scoring` | 025, 015, 021, 023 | v18.8-verdict-lab, v18.8-verdict-calibration (mergeadas); especificada e aprovada em 2026-10-19; encerrada pelo ADR 026 em 2026-10-21 (sem 5.3, 5.4 e 6) |
| V18.9 | [v18.9-result-records](changes/v18.9-result-records/proposal.md) | `evidence-scoring`, `hypothesis-loop`, `knowledge-graph`, `curator`, `claim-verification` | 026, 015, 025, 021 | — (especificada em 2026-10-21; aguarda aprovação) |
| V18.9 | [v18.9-failure-memory](changes/v18.9-failure-memory/proposal.md) | `agent-prompts` | 026 | — (especificada em 2026-10-21; aguarda aprovação) |
| V18.9 | [v18.9-memory-evaluation](changes/v18.9-memory-evaluation/proposal.md) | `benchmark` | 026 | v18.9-result-records |
| V18.9 | [v18.9-cross-project-context](changes/v18.9-cross-project-context/proposal.md) | `knowledge-semantics`, `hypothesis-loop` | 026, 013 | v18.9-result-records, v18.9-memory-evaluation (E0) |
| V18.7 | [v18.7-exploration-metrics](changes/v18.7-exploration-metrics/proposal.md) | `operation-metrics`, `benchmark` | 021, 022 | v18.7-hypothesis-linking, v18.7-subtask-contract |
| V18.7 | [v18.7-agent-system-prompts](changes/v18.7-agent-system-prompts/proposal.md) | `agent-prompts`, `agent-runtime` | 022 | v18.7-subtask-contract, v18.7-hypothesis-linking, v18.7-exploration-limits, v18.7-persistent-human-gate |
| V18.10 | [v18.10-web-skeleton](changes/v18.10-web-skeleton/proposal.md) | `web-interface` | 027 |  — |
| V18.10 | [v18.10-web-dashboard](changes/v18.10-web-dashboard/proposal.md) | `web-interface` | 027, 015 | v18.10-web-skeleton |
| V18.10 | [v18.10-web-artifacts](changes/v18.10-web-artifacts/proposal.md) | `web-interface` | 027, 008, 019 | v18.10-web-skeleton |
| V18.10 | [v18.10-web-graph](changes/v18.10-web-graph/proposal.md) | `web-interface` | 027, 015 | v18.10-web-skeleton |
| V18.10 | [v18.10-web-settings](changes/v18.10-web-settings/proposal.md) | `web-interface` | 027, 011, 017 | v18.10-web-skeleton |
| V18.10 | [v18.10-web-containers](changes/v18.10-web-containers/proposal.md) | `web-interface`, `session-launcher` | 027, 014, 023, 024 | v18.10-web-skeleton |
| V18.10 | [v18.10-web-chat](changes/v18.10-web-chat/proposal.md) | `web-interface`, `researcher-consult` | 027, 023 | v18.10-web-skeleton, ADR 023 implementado |
| V19 | [v19-equipment-control](changes/v19-equipment-control/proposal.md) | `equipment-control` | 019, 014, 015, 010 | V18.5, v18-researcher-consult |
| V20 | [v20-node-identity](changes/v20-node-identity/proposal.md) | `node-identity` | 013 | V16–V19 validadas |
| V20 | [v20-federated-records](changes/v20-federated-records/proposal.md) | `federation-records` | 013, 019, 015 | v20-node-identity, V18.5 |
| V20 | [v20-federation-transport](changes/v20-federation-transport/proposal.md) | `federation-transport` | 013 | v20-node-identity, v20-federated-records |
| V20 | [v20-remote-knowledge-intake](changes/v20-remote-knowledge-intake/proposal.md) | `remote-knowledge` | 013, 015 | v20-federated-records, v20-federation-transport, v17-knowledge-semantic-index |
| V20 | [v20-reproduction-validation](changes/v20-reproduction-validation/proposal.md) | `reproduction-validation` | 013, 014, 019 | v20-remote-knowledge-intake, v18.5-sandbox-phases |

**V19** (controle de equipamentos): `v19-equipment-control` converte a Spec G7
([`roadmaps/specs/G7_equipment_control_mhs.md`](../roadmaps/specs/G7_equipment_control_mhs.md))
para o formato OpenSpec, com o §10 do ADR 019.
**V20** (federação, ADR 013, aprovado em 2026-10-01): cinco mudanças `v20-*`; as questões em
aberto do ADR estão como propostas nos `design.md`, para decisão do pesquisador. Ver os roadmaps
`roadmaps/roadmap_V16.md` a `roadmap_V20.md`.
