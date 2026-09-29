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

## Mudanças propostas

| Versão | Mudança | Capacidade | ADRs | Depende de |
|---|---|---|---|---|
| V16 | [v16-provider-registry](changes/v16-provider-registry/proposal.md) | `llm-providers` | 011 | — |
| V16 | [v16-anthropic-provider](changes/v16-anthropic-provider/proposal.md) | `llm-providers` | 011 | v16-provider-registry |
| V16 | [v16-local-embeddings](changes/v16-local-embeddings/proposal.md) | `embeddings` | 011 | — |
| V16 | [v16-in-process-agents](changes/v16-in-process-agents/proposal.md) | `agent-runtime` | 014 | v16-provider-registry |
| V16 | [v16-research-assistant-prompts](changes/v16-research-assistant-prompts/proposal.md) | `agent-prompts` | 010, 011 | v16-in-process-agents |
| V17 | [v17-graph-store](changes/v17-graph-store/proposal.md) | `knowledge-graph` | 009, 015 | V16 |
| V17 | [v17-controlled-vocabulary](changes/v17-controlled-vocabulary/proposal.md) | `vocabulary` | 015 | v17-graph-store |
| V17 | [v17-evidence-verdict](changes/v17-evidence-verdict/proposal.md) | `evidence-scoring` | 015 | — (módulo puro) |
| V17 | [v17-research-project](changes/v17-research-project/proposal.md) | `research-project` | 015 | v17-graph-store, v17-controlled-vocabulary |
| V17 | [v17-structural-fact-ingestion](changes/v17-structural-fact-ingestion/proposal.md) | `knowledge-ingestion` | 009, 015 | v17-research-project |
| V17 | [v17-knowledge-semantic-index](changes/v17-knowledge-semantic-index/proposal.md) | `knowledge-semantics` | 011, 015 | v16-local-embeddings, v17-graph-store |
| V17 | [v17-curator-agent](changes/v17-curator-agent/proposal.md) | `curator` | 012, 015 | todas as anteriores de V17 |
| V17 | [v17-graph-cli](changes/v17-graph-cli/proposal.md) | `graph-cli` | 015 | v17-graph-store, v17-curator-agent |
| V18 | [v18-usage-limits](changes/v18-usage-limits/proposal.md) | `usage-limits` | 010, 012 | V16 |
| V18 | [v18-research-continuity](changes/v18-research-continuity/proposal.md) | `session-continuity` | 010 | v18-usage-limits, v17-structural-fact-ingestion |
| V18 | [v18-hypothesis-loop](changes/v18-hypothesis-loop/proposal.md) | `hypothesis-loop` | 010, 012 | V17, v18-usage-limits, v18-research-continuity |

**V19** (controle de equipamentos) usa a spec já existente
[`roadmaps/specs/G7_equipment_control_mhs.md`](../roadmaps/specs/G7_equipment_control_mhs.md).
**V20** (federação, ADR 013) ainda não tem spec: as questões em aberto do ADR 013 precisam ser
discutidas antes. Ver os roadmaps `roadmaps/roadmap_V16.md` a `roadmap_V20.md`.
