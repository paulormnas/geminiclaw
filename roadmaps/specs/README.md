# Specs V15 — GeminiClaw como Harness de Pesquisa Científica

**Status:** Propostas aprovadas — aguardando implementação de V14
**Criado em:** 2026-09-23
**ADR de referência:** [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md)

---

## Premissas desta versão

- O agente **recebe contexto pré-curado** via `input_context/` — busca bibliográfica é responsabilidade de agente externo
- Web search é **restrita a dúvidas técnicas operacionais** (biblioteca, API, protocolo de equipamento)
- O sistema é **primariamente autônomo**: investiga divergências por conta própria antes de qualquer consulta ao pesquisador
- O pesquisador é consultado apenas em **pontos verdadeiramente bloqueantes** (contexto genuinamente ausente)
- Toda sessão produz obrigatoriamente um **relatório científico estruturado** em Markdown com rastreabilidade

---

## Grafo de Dependências

```
V14 (fundação — concluir primeiro)
│
├──► G10: CLI Session Profile (V15.6) ← PRIMEIRO — pré-requisito de G5
│
├──► G9:  input_context Pipeline (V15.5) ← pode ser feito em paralelo com G10
│
├──► G1:  Researcher Agent Científico (V15.1) ← depende de V14.3
│         (pode ser feito junto com V14.3 — apenas prompts)
│
├──► G2:  Código Reproduzível (V15.2) ← depende de V14.4 e G1
│
├──► G5:  Human Feedback Loop (V15.3) ← depende de G9 e G10
│
├──► G8:  Relatório Científico (V15.4) ← depende de G2 e G5
│
└──► G7:  Controle de Equipamentos (V16.1) ← V16, após V15 completo
```

---

## Specs por Gap

| Gap | Spec | Versão | Complexidade | Pré-requisitos |
|---|---|---|---|---|
| **G1** | [Researcher Agent: Contexto Científico](./G1_researcher_scientific_context.md) | V15.1 | Baixa | V14.3 |
| **G2** | [Código Reproduzível](./G2_reproducible_code_contracts.md) | V15.2 | Média | V14.4, G1 |
| **G5** | [Human Feedback Loop](./G5_human_feedback_loop.md) | V15.3 | Alta | G9, G10 |
| **G7** | [Controle de Equipamentos + MHS](./G7_equipment_control_mhs.md) | V16.1 | Alta | V15 completo |
| **G8** | [Relatório Científico](./G8_scientific_report.md) | V15.4 | Alta | G2, G5 |
| **G9** | [Pipeline input_context](./G9_input_context_pipeline.md) | V15.5 | Alta | V14 |
| **G10** | [CLI Session Profile](./G10_cli_session_profile.md) | V15.6 | Baixa-Média | V14 |

---

## Ordem de implementação sugerida

```
Iteração 1 (Fundação CLI e Contexto):
  G10 → G9

Iteração 2 (Perfil Científico dos Agentes):
  G1 → G2 (pode ser feito em paralelo com V14.3 e V14.4)

Iteração 3 (Interação Humana e Relatório):
  G5 → G8

Iteração 4 (Hardware — V16):
  G7
```

---

## O que está fora do escopo de V15

- **Busca bibliográfica:** responsabilidade de agente externo (ADR 001)
- **Controle de equipamentos:** specs em G7, mas implementação em V16
- **Interface visual / dashboard:** roadmap futuro (V17+)
