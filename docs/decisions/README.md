# Decisões Arquiteturais — GeminiClaw

Este diretório contém os **Architectural Decision Records (ADRs)** do projeto GeminiClaw.

Cada ADR documenta uma decisão técnica significativa com: contexto, decisão tomada, alternativas descartadas e consequências.

---

## Índice

| ADR | Título | Status | Data |
|---|---|---|---|
| [001](adr_001_proposito_harness_pesquisa_cientifica.md) | Propósito: Harness de Execução de Pesquisa Científica | ✅ Aceito (em revisão → 010) | 2026-09-22 |
| [002](adr_002_arquitetura_multi_agent_system.md) | Arquitetura Multi-Agent System com DAG de Execução | ✅ Aceito | 2026-09-22 |
| [003](adr_003_containerizacao_docker_dind.md) | Containerização Docker com Sandbox DinD Resiliente | ✅ Aceito (em revisão → 014) | 2026-09-22 |
| [004](adr_004_protocolo_ipc_unix_sockets.md) | Protocolo IPC via Unix Domain Sockets com Length-Prefix | ✅ Aceito (em revisão → 014) | 2026-09-22 |
| [005](adr_005_estrategia_persistencia.md) | Estratégia de Persistência: PostgreSQL + Qdrant + SQLite | ✅ Aceito | 2026-09-22 |
| [006](adr_006_abstracao_provedores_llm.md) | Abstração de Provedores LLM: Ollama + Google Gemini | ✅ Aceito (em revisão → 011) | 2026-09-22 |
| [007](adr_007_reestruturacao_papeis_agentes.md) | Reestruturação de Papéis de Agentes: 3 Papéis Claros (V14) | 🔵 Proposto | 2026-09-22 |
| [008](adr_008_workspace_manifest_session_scoped.md) | Workspace Manifest e Session-Scoped Volumes (V13) | ✅ Aceito | 2026-09-22 |
| [009](adr_009_camada_conhecimento_experimental.md) | Camada de Conhecimento Experimental: Grafo (Apache AGE) + Vetorial (Qdrant) | 🔵 Proposto | 2026-09-28 |
| [010](adr_010_proposito_assistente_digital_pesquisa.md) | Propósito: Assistente Digital de Pesquisa Científica (substitui 001) | 🔵 Proposto | 2026-09-28 |
| [011](adr_011_provedores_agnosticos.md) | Provedores Agnósticos: Registro de Provedores LLM e de Embeddings (substitui 006) | 🔵 Proposto | 2026-09-28 |
| [012](adr_012_agente_curator_ciclo_exploracao.md) | Agente Curator e Ciclo de Exploração Contínua | 🔵 Proposto | 2026-09-28 |
| [013](adr_013_federacao_rede_publica.md) | Federação: Rede Pública de Conhecimento entre Nós (Princípios) | 🔵 Proposto | 2026-09-28 |
| [014](adr_014_agentes_em_processo_sandbox_codigo.md) | Agentes em Processo no Host; Containers Apenas como Sandbox de Código | 🔵 Proposto | 2026-09-28 |

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
ADR 010 (Propósito: Assistente de Pesquisa) ← define o escopo de tudo (substitui ADR 001)
  ├── ADR 002 (MAS) ← como o sistema executa
  │     ├── ADR 003 (Docker) ← como os agentes são isolados
  │     ├── ADR 004 (IPC) ← como orquestrador e agentes se comunicam
  │     ├── ADR 007 (Papéis V14) ← como os papéis serão reestruturados
  │     └── ADR 014 (Agentes em Processo) ← agentes no host; só o código roda em sandbox (revisa 003/004)
  ├── ADR 005 (Persistência) ← onde o estado é guardado
  │     └── ADR 009 (Conhecimento Experimental) ← como a experiência de pesquisa é acumulada
  │           ├── ADR 012 (Curator) ← quem registra o conhecimento e mantém a exploração
  │           └── ADR 013 (Federação) ← como o conhecimento é compartilhado entre nós (último)
  ├── ADR 011 (Provedores Agnósticos) ← quais modelos e embeddings são usados (substitui ADR 006)
  └── ADR 008 (Manifest V13) ← como o contexto de código é persistido
```
