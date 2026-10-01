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
| [006](adr_006_abstracao_provedores_llm.md) | Abstração de Provedores LLM: Ollama + Google Gemini | ✅ Aceito (em revisão → 011) | 2026-09-22 |
| [007](adr_007_reestruturacao_papeis_agentes.md) | Reestruturação de Papéis de Agentes: 3 Papéis Claros (V14) | 🔵 Proposto | 2026-09-22 |
| [008](adr_008_workspace_manifest_session_scoped.md) | Workspace Manifest e Session-Scoped Volumes (V13) | ✅ Aceito | 2026-09-22 |
| [009](adr_009_camada_conhecimento_experimental.md) | Camada de Conhecimento Experimental: Grafo (Apache AGE) + Vetorial (Qdrant) | 🟢 Aprovado (implementação pendente) | 2026-09-28 |
| [010](adr_010_proposito_assistente_digital_pesquisa.md) | Propósito: Assistente Digital de Pesquisa Científica (substitui 001) | 🟢 Aprovado (implementação pendente) | 2026-09-28 |
| [011](adr_011_provedores_agnosticos.md) | Provedores Agnósticos: Registro de Provedores LLM e de Embeddings (substitui 006) | 🟡 Em revisão (atualizado em 2026-10-01; aguarda aprovação) | 2026-09-28 |
| [012](adr_012_agente_curator_ciclo_exploracao.md) | Agente Curator e Ciclo de Exploração Contínua | 🟢 Aprovado (implementação pendente) | 2026-09-28 |
| [013](adr_013_federacao_rede_publica.md) | Federação: Rede Pública de Conhecimento entre Nós (Princípios) | 🔵 Proposto | 2026-09-28 |
| [014](adr_014_agentes_em_processo_sandbox_codigo.md) | Agentes em Processo no Host; Containers Apenas como Sandbox de Código | ✅ Aceito | 2026-09-28 |
| [015](adr_015_modelo_dados_grafo_conhecimento.md) | Modelo de Dados do Grafo de Conhecimento e Ligação com Embeddings | 🟢 Aprovado (implementação pendente) | 2026-09-28 |
| [016](adr_016_imagem_postgres_apache_age_colacao.md) | Imagem do PostgreSQL para Apache AGE (musl → glibc) e Colação de Índices | 🔵 Proposto | 2026-09-29 |
| [017](adr_017_catalogo_modelos_roteador.md) | Catálogo de Modelos e Roteador de Provedores por Papel | 🔵 Proposto | 2026-09-29 |
| [018](adr_018_imagem_sandbox_enxuta_e_imagens_por_plataforma.md) | Imagem Enxuta do Sandbox de Código e Seleção de Imagens por Plataforma (registro de ideias) | 🔵 Proposto | 2026-09-29 |
| [019](adr_019_localidade_dados_proveniencia_resultados.md) | Localidade dos Dados de Pesquisa e Proveniência dos Resultados | 🟢 Aprovado (implementação pendente) | 2026-09-29 |

---

## Legenda de Status

| Status | Significado |
|---|---|
| 🔵 **Proposto** | Decisão documentada, aguardando aprovação do pesquisador responsável |
| 🟡 **Em revisão** | Texto sendo atualizado; volta a Proposto ou Aprovado depois da revisão |
| 🟢 **Aprovado** | Decisão aprovada pelo pesquisador responsável; implementação pendente (total ou parcial) |
| ✅ **Aceito** | Decisão aprovada, implementada e em vigor |
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

Verificação dos ADRs aprovados contra `openspec/changes/`. As specs abaixo ainda **não existem**
e precisam ser descritas antes de implementar o que dependem delas (a ordem de trabalho está na
memória do projeto e no PR que introduziu esta seção).

| Spec a descrever (nome sugerido) | Origem | Por que falta |
|---|---|---|
| `v16-pipeline-robustness` | Benchmark de 2026-10-01 | Normalizador determinístico de plano, nomes de artefatos tolerantes, revisão do circuit breaker e dos limites, modelo de relatório do Summarizer. Etapa anterior à V17 |
| `v16-agent-communication-eval` | Avaliação do projeto | Veredito do revisor contra verdade determinística, taxa de resolução, laços de reprovação, juiz LLM de outro provedor com calibração humana |
| `v17-input-document-index` | ADR 015 §6 (`Insumo`) | Acionar a indexação dos documentos de `input_context/` e enriquecer o texto com metadados antes do vetor. Hoje a coleção de documentos tem 0 pontos |
| `v18-researcher-consult` | ADR 012 §8, ADR 010 item 9 | `ask_researcher` respondido pelo Researcher com consultas simples na web nos modos `semi` e `auto`; muda o comportamento da Spec G5 |
| `v16-model-catalog-router` | ADR 017 | A base do catálogo e do roteador não tem spec; `v18.5-model-catalog-locality` depende dela. **O ADR 017 ainda não foi aprovado** |
| (sem spec) imagem enxuta do sandbox | ADR 018 | Registro de ideias, a discutir; `v18.5-sandbox-phases` cobre só as fases de rede |
| Revisão da Spec G7 (V19.1) | ADR 019 §10 | Somente leitura por padrão e confirmação humana para escrita em instrumentos; previsto no roadmap V19 |
| Spec da federação (V20) | ADR 013 | Só princípios; última etapa |

Mudanças já descritas, mas que precisam de ajuste de texto quando forem implementadas:
`v17-curator-agent` (o Curator decide quando registrar, ADR 012 §7), `v18-hypothesis-loop` (usar o
Researcher consultor), `v18-usage-limits` (contabilizar as consultas) e a Spec G5.

Mudanças implementadas **sem** spec própria, registradas apenas no ADR 011 (§2, §6 e §7): o
provedor `openai`, a tabela de preços e a contabilidade por chamada, o bloqueio de rede paga nos
testes. Mudanças com código pronto e `tasks.md` desatualizado: `v17-graph-store`
(armazenamento do grafo, #64 e #71) e `v17-evidence-verdict`; marcar as tarefas e arquivar ao
validar.
