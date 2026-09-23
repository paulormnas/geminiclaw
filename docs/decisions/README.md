# Decisões Arquiteturais — GeminiClaw

Este diretório contém os **Architectural Decision Records (ADRs)** do projeto GeminiClaw.

Cada ADR documenta uma decisão técnica significativa com: contexto, decisão tomada, alternativas descartadas e consequências.

---

## Índice

| ADR | Título | Status | Data |
|---|---|---|---|
| [001](adr_001_proposito_harness_pesquisa_cientifica.md) | Propósito: Harness de Execução de Pesquisa Científica | ✅ Aceito | 2026-09-22 |
| [002](adr_002_arquitetura_multi_agent_system.md) | Arquitetura Multi-Agent System com DAG de Execução | ✅ Aceito | 2026-09-22 |
| [003](adr_003_containerizacao_docker_dind.md) | Containerização Docker com Sandbox DinD Resiliente | ✅ Aceito | 2026-09-22 |
| [004](adr_004_protocolo_ipc_unix_sockets.md) | Protocolo IPC via Unix Domain Sockets com Length-Prefix | ✅ Aceito | 2026-09-22 |
| [005](adr_005_estrategia_persistencia.md) | Estratégia de Persistência: PostgreSQL + Qdrant + SQLite | ✅ Aceito | 2026-09-22 |
| [006](adr_006_abstracao_provedores_llm.md) | Abstração de Provedores LLM: Ollama + Google Gemini | ✅ Aceito | 2026-09-22 |
| [007](adr_007_reestruturacao_papeis_agentes.md) | Reestruturação de Papéis de Agentes: 3 Papéis Claros (V14) | 🔵 Proposto | 2026-09-22 |
| [008](adr_008_workspace_manifest_session_scoped.md) | Workspace Manifest e Session-Scoped Volumes (V13) | ✅ Aceito | 2026-09-22 |

---

## Legenda de Status

| Status | Significado |
|---|---|
| 🔵 **Proposto** | Decisão documentada, aguardando implementação |
| ✅ **Aceito** | Decisão implementada e em vigor |
| ⚠️ **Deprecado** | Decisão substituída por ADR mais recente |
| ❌ **Rejeitado** | Proposta avaliada e descartada (mantido para histórico) |

---

## Como Criar um Novo ADR

1. Copie o template abaixo para `adr_NNN_titulo_descritivo.md`
2. Preencha todos os campos
3. Atualize este README com a nova entrada
4. Abra PR via workflow `do-pull-request.md`

### Template

```markdown
# ADR NNN — Título

**Status:** Proposto | Aceito | Deprecado | Rejeitado
**Data:** YYYY-MM-DD
**Autores:** Papel (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V*.md`

---

## Contexto
[Por que esta decisão foi necessária?]

## Decisão
[O que foi decidido e como funciona?]

## Alternativas Consideradas
[O que foi avaliado e descartado?]

## Consequências
[O que muda? Positivos e trade-offs.]

## Revisão
[Quando este ADR deve ser revisado?]
```

---

## Relacionamentos entre ADRs

```
ADR 001 (Propósito) ← define o escopo de tudo
  ├── ADR 002 (MAS) ← como o sistema executa
  │     ├── ADR 003 (Docker) ← como os agentes são isolados
  │     ├── ADR 004 (IPC) ← como orquestrador e agentes se comunicam
  │     └── ADR 007 (Papéis V14) ← como os papéis serão reestruturados
  ├── ADR 005 (Persistência) ← onde o estado é guardado
  ├── ADR 006 (LLM Providers) ← quais modelos são usados
  └── ADR 008 (Manifest V13) ← como o contexto de código é persistido
```
