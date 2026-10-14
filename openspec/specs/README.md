# Specs Consolidadas

Verdade atual do sistema, organizada por capacidade (`specs/<capacidade>/spec.md`).

Os requisitos são consolidados aqui quando cada mudança de `openspec/changes/` é implementada,
integrada em `dev` e arquivada. A primeira consolidação (2026-10-13) reuniu as 32 mudanças de V16 a
V18.5: requisitos `ADDED` e `MODIFIED` em ordem cronológica (o último vence) e `REMOVED` listados no
fim de cada arquivo. Cada requisito cita a mudança de origem. A segunda consolidação (2026-10-13)
acrescentou as 4 mudanças da V18.6 (`pipeline-robustness`, `benchmark` (nova), `llm-providers` e
`hypothesis-loop`). A terceira consolidação (2026-10-13) acrescentou
`v18.6-profile-hardening` (`pipeline-robustness`, `data-egress`) e `v18.6-remove-unused-agents`
(`agent-runtime`, `llm-providers`, `communication-eval`); os `MODIFIED`/`REMOVED` desta última foram
aplicados aos requisitos existentes (catálogo versionado, rótulo da revisão de subtarefa, agente
Reviewer).

| Capacidade | Arquivo |
|---|---|
| `agent-prompts` | [`agent-prompts/spec.md`](agent-prompts/spec.md) |
| `agent-runtime` | [`agent-runtime/spec.md`](agent-runtime/spec.md) |
| `benchmark` | [`benchmark/spec.md`](benchmark/spec.md) |
| `claim-verification` | [`claim-verification/spec.md`](claim-verification/spec.md) |
| `code-sandbox` | [`code-sandbox/spec.md`](code-sandbox/spec.md) |
| `communication-eval` | [`communication-eval/spec.md`](communication-eval/spec.md) |
| `curator` | [`curator/spec.md`](curator/spec.md) |
| `data-egress` | [`data-egress/spec.md`](data-egress/spec.md) |
| `domain-search` | [`domain-search/spec.md`](domain-search/spec.md) |
| `embeddings` | [`embeddings/spec.md`](embeddings/spec.md) |
| `evidence-scoring` | [`evidence-scoring/spec.md`](evidence-scoring/spec.md) |
| `execution-provenance` | [`execution-provenance/spec.md`](execution-provenance/spec.md) |
| `graph-cli` | [`graph-cli/spec.md`](graph-cli/spec.md) |
| `hypothesis-loop` | [`hypothesis-loop/spec.md`](hypothesis-loop/spec.md) |
| `input-documents` | [`input-documents/spec.md`](input-documents/spec.md) |
| `knowledge-graph` | [`knowledge-graph/spec.md`](knowledge-graph/spec.md) |
| `knowledge-ingestion` | [`knowledge-ingestion/spec.md`](knowledge-ingestion/spec.md) |
| `knowledge-semantics` | [`knowledge-semantics/spec.md`](knowledge-semantics/spec.md) |
| `llm-providers` | [`llm-providers/spec.md`](llm-providers/spec.md) |
| `numeric-provenance` | [`numeric-provenance/spec.md`](numeric-provenance/spec.md) |
| `operation-metrics` | [`operation-metrics/spec.md`](operation-metrics/spec.md) |
| `pipeline-robustness` | [`pipeline-robustness/spec.md`](pipeline-robustness/spec.md) |
| `platform-images` | [`platform-images/spec.md`](platform-images/spec.md) |
| `research-data` | [`research-data/spec.md`](research-data/spec.md) |
| `research-project` | [`research-project/spec.md`](research-project/spec.md) |
| `researcher-consult` | [`researcher-consult/spec.md`](researcher-consult/spec.md) |
| `session-continuity` | [`session-continuity/spec.md`](session-continuity/spec.md) |
| `usage-limits` | [`usage-limits/spec.md`](usage-limits/spec.md) |
| `vocabulary` | [`vocabulary/spec.md`](vocabulary/spec.md) |
