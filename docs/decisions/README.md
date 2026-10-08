# Decisões Arquiteturais — GeminiClaw

Este diretório contém os **Architectural Decision Records (ADRs)** do projeto GeminiClaw.

Cada ADR documenta uma decisão técnica significativa com: contexto, decisão tomada, alternativas descartadas e consequências.

---

## Índice

| ADR | Título | Status | Data |
|---|---|---|---|
| [001](adr_001_proposito_harness_pesquisa_cientifica.md) | Propósito: Harness de Execução de Pesquisa Científica | ⚠️ Deprecado (substituído pelo 010 em 2026-10-01) | 2026-09-22 |
| [002](adr_002_arquitetura_multi_agent_system.md) | Arquitetura Multi-Agent System com DAG de Execução | ✅ Aceito | 2026-09-22 |
| [003](adr_003_containerizacao_docker_dind.md) | Containerização Docker com Sandbox DinD Resiliente | ⚠️ Parcialmente substituído pelo 014 (§1 e §3); §2 (sandbox de código) em vigor | 2026-09-22 |
| [004](adr_004_protocolo_ipc_unix_sockets.md) | Protocolo IPC via Unix Domain Sockets com Length-Prefix | ⚠️ Deprecado (substituído pelo 014) | 2026-09-22 |
| [005](adr_005_estrategia_persistencia.md) | Estratégia de Persistência: PostgreSQL + Qdrant + SQLite | ✅ Aceito | 2026-09-22 |
| [006](adr_006_abstracao_provedores_llm.md) | Abstração de Provedores LLM: Ollama + Google Gemini | ⚠️ Deprecado (substituído pelo 011 em 2026-10-01) | 2026-09-22 |
| [007](adr_007_reestruturacao_papeis_agentes.md) | Reestruturação de Papéis de Agentes: 3 Papéis Claros (V14) | ✅ Aceito | 2026-09-22 |
| [008](adr_008_workspace_manifest_session_scoped.md) | Workspace Manifest e Session-Scoped Volumes (V13) | ✅ Aceito | 2026-09-22 |
| [009](adr_009_camada_conhecimento_experimental.md) | Camada de Conhecimento Experimental: Grafo (Apache AGE) + Vetorial (Qdrant) | ✅ Aceito (validação em AGE/Qdrant reais pendente) | 2026-09-28 |
| [010](adr_010_proposito_assistente_digital_pesquisa.md) | Propósito: Assistente Digital de Pesquisa Científica (substitui 001) | 🟠 Parcialmente implementado (V19 e parte da V18.5 pendentes) | 2026-09-28 |
| [011](adr_011_provedores_agnosticos.md) | Provedores Agnósticos: Registro de Provedores LLM e de Embeddings (substitui 006) | ✅ Aceito (2026-10-01) | 2026-09-28 |
| [012](adr_012_agente_curator_ciclo_exploracao.md) | Agente Curator e Ciclo de Exploração Contínua | ✅ Aceito (validação em AGE real pendente) | 2026-09-28 |
| [013](adr_013_federacao_rede_publica.md) | Federação: Rede Pública de Conhecimento entre Nós (Princípios) | 🟢 Aprovado (princípios; implementação não iniciada, V20) | 2026-09-28 |
| [014](adr_014_agentes_em_processo_sandbox_codigo.md) | Agentes em Processo no Host; Containers Apenas como Sandbox de Código | ✅ Aceito | 2026-09-28 |
| [015](adr_015_modelo_dados_grafo_conhecimento.md) | Modelo de Dados do Grafo de Conhecimento e Ligação com Embeddings | 🟠 Parcialmente implementado (V17/V18 prontos; V18.5–V20 pendentes) | 2026-09-28 |
| [016](adr_016_imagem_postgres_apache_age_colacao.md) | Imagem do PostgreSQL para Apache AGE (musl → glibc) e Colação de Índices | 🟢 Aprovado (2026-10-08; implementada, validação da colação no Pi pendente) | 2026-09-29 |
| [017](adr_017_catalogo_modelos_roteador.md) | Catálogo de Modelos e Roteador de Provedores por Papel | ✅ Aceito | 2026-09-29 |
| [018](adr_018_imagem_sandbox_enxuta_e_imagens_por_plataforma.md) | Imagem Enxuta do Sandbox de Código e Seleção de Imagens por Plataforma (registro de ideias) | 🟠 Parcialmente implementado (falta `v16-platform-images`) | 2026-09-29 |
| [019](adr_019_localidade_dados_proveniencia_resultados.md) | Localidade dos Dados de Pesquisa e Proveniência dos Resultados | 🟠 Parcialmente implementado (3 de 8 mudanças V18.5) | 2026-09-29 |

---

## Legenda de Status

| Status | Significado |
|---|---|
| 🔵 **Proposto** | Decisão documentada, aguardando aprovação do pesquisador responsável |
| 🟡 **Em revisão** | Texto sendo atualizado; volta a Proposto ou Aprovado depois da revisão |
| 🟢 **Aprovado** | Decisão aprovada pelo pesquisador responsável; implementação não iniciada (ou sem mudança mergeada) |
| 🟠 **Parcialmente implementado** | Decisão aprovada; parte das mudanças OpenSpec do ADR está mergeada e parte pendente |
| ✅ **Aceito** | Decisão aprovada, com todas as mudanças OpenSpec do ADR mergeadas e em vigor (a validação em ambiente real pode seguir pendente e fica registrada no ADR) |
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
  │           └── ADR 018 (Imagem do Sandbox) ← sandbox enxuto, pacotes sob demanda, imagens por plataforma
  ├── ADR 005 (Persistência) ← onde o estado é guardado
  │     └── ADR 009 (Conhecimento Experimental) ← como a experiência de pesquisa é acumulada
  │           ├── ADR 015 (Modelo do Grafo) ← nós, relações, propriedades e embeddings
  │           ├── ADR 012 (Curator) ← quem registra o conhecimento e mantém a exploração
  │           └── ADR 013 (Federação) ← como o conhecimento é compartilhado entre nós (último)
  ├── ADR 011 (Provedores Agnósticos) ← quais modelos e embeddings são usados (substitui ADR 006)
  ├── ADR 019 (Localidade e Proveniência) ← o que sai do nó e de onde vem cada número (após a V18, antes da V19)
  └── ADR 008 (Manifest V13) ← como o contexto de código é persistido
```

---

## Lacunas de especificação (2026-10-01)

Verificação dos ADRs aprovados contra `openspec/changes/`. Não há mais specs faltando para os
ADRs aprovados, exceto o ADR 016 (Proposto). A ordem de trabalho está na memória do projeto e no
PR que introduziu esta seção.

Descritas em 2026-10-05 (aguardando aprovação do pesquisador), etapa de robustez do pipeline
que antecede a V17: `v16-pipeline-robustness` (normalizador de plano, artefatos tolerantes,
disjuntor e limites, relatório estruturado) e `v16-agent-communication-eval` (veredito do
revisor contra verdade determinística, taxa de resolução, laços, juiz LLM calibrado). Não
dependem de ADR novo.

Descritas em 2026-10-01 (aguardando aprovação do pesquisador): `v16-model-catalog-router`
(ADR 017), `v16-sandbox-slim-image` (ADR 018 §1 a §3), `v16-platform-images` (ADR 018 §5),
`v17-input-document-index` (ADR 015 §6), `v18-researcher-consult` (ADR 012 §8, ADR 010 item 9)
e `v19-equipment-control` (conversão da Spec G7 com o ADR 019 §10). Com a aprovação do ADR 013
(2026-10-01), a V20 ganhou cinco mudanças `v20-*` com propostas para as questões em aberto do
ADR. O ADR 016 continua Proposto e não tem spec.

Mudanças já descritas, mas que precisam de ajuste de texto quando forem implementadas:
`v17-curator-agent` (o Curator decide quando registrar, ADR 012 §7). Os ajustes de
`v18-hypothesis-loop`, `v18-usage-limits` e da Spec G5 decorrentes da consulta ao Researcher
estão na própria `v18-researcher-consult` e em notas datadas nessas mudanças.

Mudanças implementadas **sem** spec própria, registradas apenas no ADR 011 (§2, §6 e §7): o
provedor `openai`, a tabela de preços e a contabilidade por chamada, o bloqueio de rede paga nos
testes. Mudanças com código pronto e `tasks.md` desatualizado: `v17-graph-store`
(armazenamento do grafo, #64 e #71) e `v17-evidence-verdict`; marcar as tarefas e arquivar ao
validar.
