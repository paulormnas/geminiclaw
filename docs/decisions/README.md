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
| [009](adr_009_camada_conhecimento_experimental.md) | Camada de Conhecimento Experimental: Grafo (Apache AGE) + Vetorial (Qdrant) | ✅ Aceito (V18.6 incluída; validação em AGE/Qdrant reais pendente) | 2026-09-28 |
| [010](adr_010_proposito_assistente_digital_pesquisa.md) | Propósito: Assistente Digital de Pesquisa Científica (substitui 001) | 🟠 Parcialmente implementado (V16–V18.6 concluídas e arquivadas, a V18.6 com pendências; V19 pendente) | 2026-09-28 |
| [011](adr_011_provedores_agnosticos.md) | Provedores Agnósticos: Registro de Provedores LLM e de Embeddings (substitui 006) | ✅ Aceito (2026-10-01) | 2026-09-28 |
| [012](adr_012_agente_curator_ciclo_exploracao.md) | Agente Curator e Ciclo de Exploração Contínua | ✅ Aceito (validação em AGE real pendente) | 2026-09-28 |
| [013](adr_013_federacao_rede_publica.md) | Federação: Rede Pública de Conhecimento entre Nós (Princípios) | 🟢 Aprovado (princípios; implementação não iniciada, V20) | 2026-09-28 |
| [014](adr_014_agentes_em_processo_sandbox_codigo.md) | Agentes em Processo no Host; Containers Apenas como Sandbox de Código | ✅ Aceito | 2026-09-28 |
| [015](adr_015_modelo_dados_grafo_conhecimento.md) | Modelo de Dados do Grafo de Conhecimento e Ligação com Embeddings | 🟠 Parcialmente implementado (V17–V18.6 concluídas e arquivadas; V19–V20 pendentes) | 2026-09-28 |
| [016](adr_016_imagem_postgres_apache_age_colacao.md) | Imagem do PostgreSQL para Apache AGE (musl → glibc) e Colação de Índices | ✅ Aceito (2026-10-13; validação da colação no Pi pendente) | 2026-09-29 |
| [017](adr_017_catalogo_modelos_roteador.md) | Catálogo de Modelos e Roteador de Provedores por Papel | ✅ Aceito | 2026-09-29 |
| [018](adr_018_imagem_sandbox_enxuta_e_imagens_por_plataforma.md) | Imagem Enxuta do Sandbox de Código e Seleção de Imagens por Plataforma (registro de ideias) | ✅ Aceito (2026-10-13; 5.5.1, 5.5.2 e medições no Pi pendentes) | 2026-09-29 |
| [019](adr_019_localidade_dados_proveniencia_resultados.md) | Localidade dos Dados de Pesquisa e Proveniência dos Resultados | 🟠 Parcialmente implementado (8 mudanças V18.5 e 5 da V18.6 concluídas e arquivadas, incluindo as correções do parecer do perfil estrutural; §10 na V19; validação real e revisões de segurança da V18.5 pendentes) | 2026-09-29 |
| [020](adr_020_independencia_validator.md) | Independência do Julgamento: Família de Modelo do Validator Diferente da do Developer | ✅ Aceito (2026-10-13; `v18.6-validator-independence`, `v18.6-benchmark-harness`, `v18.6-remove-unused-agents` e `v18.6-models-gemini4-gpt6` concluídas e arquivadas; matriz com bancos isolados e 3 repetições no Pi 5 e revisão do ADR depois dela ficam como acompanhamento) | 2026-10-13 |
| [021](adr_021_exploracao_rastreavel_por_hipoteses.md) | Exploração Rastreável por Hipóteses: Estrutura dos Nós e Governança por Registro | 🟠 Parcialmente implementado (V18.7: 3 das 4 mudanças mergeadas e validadas na bateria parcial de 2026-10-18; `v18.7-exploration-metrics` pendente) | 2026-10-15 |
| [022](adr_022_contrato_contexto_por_chamada.md) | Contrato de Contexto por Chamada e Regimento da Pesquisa | 🟠 Parcialmente implementado (V18.7: `v18.7-subtask-contract` mergeada; `v18.7-dependency-artifacts`, `v18.7-agent-system-prompts` e `v18.7-exploration-metrics` pendentes) | 2026-10-15 |
| [023](adr_023_pesquisa_em_segundo_plano.md) | Pesquisa em Segundo Plano com Acompanhamento pelo Terminal | 🟠 Parcialmente implementado (V18.7: 3 das 4 mudanças mergeadas; `v18.7-session-events-terminal` pendente) | 2026-10-15 |
| [024](adr_024_organizacao_do_codigo.md) | Organização do Código por Responsabilidade e Regra de Camadas | 🟠 Parcialmente implementado (Etapas 1 e 2 mergeadas; Etapa 3 pendente em duas mudanças) | 2026-10-15 |
| [025](adr_025_calibracao_do_veredito.md) | Calibração do Veredito: Exploração e Teste dos Parâmetros | ⚠️ Deprecado (substituído pelo 026 em 2026-10-21; etapas 1 e 2 e modelo v2 implementados, etapa 3 encerrada sem a bateria) | 2026-10-15 |
| [026](adr_026_memoria_por_registros_de_resultado.md) | Memória por Registros de Resultado e Correlação entre Pesquisas (substitui o veredito) | 🟢 Aprovado (direção; mudanças `v18.9-*` especificadas, aguardam aprovação) | 2026-10-21 |
| [027](adr_027_interface_web.md) | Interface Web do Pesquisador: SPA em TypeScript e API FastAPI Local | 🔵 Proposto (mudanças `v18.10-web-*` especificadas, aguardam aprovação) | 2026-10-24 |


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
  │     └── ADR 020 (Independência do Julgamento) ← juiz de família diferente da do Developer (V18.6)
  └── ADR 008 (Manifest V13) ← como o contexto de código é persistido
```

---

## Lacunas de especificação (2026-10-01)

**Atualização 2026-10-24 (V18.10):** o ADR 027 (interface web) está Proposto, com as cinco mudanças `v18.10-web-*` especificadas ([`roadmap_V18.10.md`](../../roadmaps/roadmap_V18.10.md)); nada implementado.

**Atualização 2026-10-21 (V18.9):** o ADR 026 substitui o ADR 015 §9 e o ADR 025 (Deprecado): o veredito dá lugar a registros de resultado com estado da hipótese por regra de réplicas, memória de falhas e experiência de problemas semelhantes no planejamento. As quatro mudanças `v18.9-*` estão especificadas e aguardam aprovação ([`roadmap_V18.9.md`](../../roadmaps/roadmap_V18.9.md)). `v18.8-verdict-controlled-sessions` foi encerrada sem 5.3, 5.4 e 6.

**Atualização 2026-10-19 (V18.8, etapa 3):** `v18.8-verdict-controlled-sessions` (explorações controladas com efeito conhecido, tratamento do N-abordagem-4, orçamento e relatório em `docs/calibracao-veredito/`) está especificada e aprovada pelo pesquisador; nada implementado. O ADR 025 segue `Parcialmente implementado`.

**Atualização 2026-10-19 (V18.8):** `v18.8-verdict-calibration` implementada (modelo v2 da equação do veredito e `KNOWLEDGE_SHORTCUT_MIN_VERDICT` em 0,3); o ADR 015 §9 foi revisado (§9.9) e o ADR 025 passa a `Parcialmente implementado`. Pendentes: etapas 3 e 4 do ADR 025.

**Atualização 2026-10-18 (V18.8):** o ADR 025 passa a `Aprovado` (plano de exploração). Etapa 1 concluída ([`docs/calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md`](../calibracao-veredito/2026-10-18-etapa-1-repeticao-offline.md)); a etapa 2 está especificada em `v18.8-verdict-lab` (aguarda aprovação), com o roadmap `roadmaps/roadmap_V18.8.md`. `v18.8-verdict-calibration` e `v18.8-verdict-direction` seguem sem spec (dependem dos resultados).

**Atualização 2026-10-18 (V18.7):** `v18.7-subtask-contract` (ADR 022 §1 a §3, §6 e §8) está implementada e mergeada (#203 a #210); o ADR 022 passa a `Parcialmente implementado` (faltam `v18.7-agent-system-prompts` e `v18.7-exploration-metrics`, e a bateria real, que aguarda confirmação do pesquisador). Reprocessamento offline da V18.6: `docs/benchmarks/2026-10-18-reprocessamento-v18-6-subtask-contract.md`. Achado novo: o contrato não entrega os artefatos das dependências ao consumidor; decisão do pesquisador registrada no ADR 022 §9 e especificada em `v18.7-dependency-artifacts` (aguarda aprovação).

**Atualização 2026-10-17 (V18.7):** `v18.7-exploration-limits` (#187 a #199), `v18.7-hypothesis-linking` e `v18.7-graph-exploration-relations` estão implementadas e mergeadas; o ADR 021 passa a `Parcialmente implementado` (faltam `v18.7-exploration-metrics` e a bateria da V18.7 no Raspberry Pi, com confirmação do pesquisador). Os ADRs 023 e 024 passam a `Parcialmente implementado` e o 022 segue `Aprovado` (nenhuma das duas mudanças dele foi iniciada); ver a tabela "Estado da implementação" em cada ADR.

**Atualização 2026-10-15 (V18.7):** os ADRs 021 a 024 (aprovados) têm as 13 mudanças OpenSpec `v18.7-*` em `openspec/changes/`, com o roadmap `roadmaps/roadmap_V18.7.md`; nenhuma implementada. O ADR 025 (rascunho) explora a calibração do veredito.

**Atualização 2026-10-14 (V18.6, fechamento 3):** `v18.6-auto-metrics-and-stop-reasons` (#157: métricas definidas pelo
Researcher e validadas pelo Validator no modo `auto`, motivo de parada `hipoteses_nao_testadas` e motivo de reprovação
`sem_hipotese`) foi arquivada e os requisitos consolidados em `openspec/specs/`. Notas e tabelas de estado nos ADRs 010, 012,
015 e 020. Os status não mudam (010 e 015 Parcialmente implementados; 012 e 020 como estavam). A sessão `auto` real e a
ratificação das métricas pelo pesquisador entram na bateria do Pi 5 (`PENDENCIAS.md`).

**Atualização 2026-10-13 (V18.6, fechamento 2):** `v18.6-profile-hardening` (#154, NC-PERFIL-1 a 6 do parecer de segurança
do perfil estrutural) e `v18.6-remove-unused-agents` (#155, remoção do papel e agente `reviewer`) foram arquivadas e os
requisitos consolidados em `openspec/specs/`. Notas e tabelas de estado atualizadas nos ADRs 007 (papel `reviewer` removido),
017 (catálogo versão 4, cinco papéis), 019 (§3: perfil estrutural endurecido) e 020 (juiz = `validator`, julgado = `developer`).
Os status não mudam: ADR 019 segue Parcialmente implementado e o ADR 020 segue Aceito, com a matriz de 3 repetições no Pi 5
(e a composição da matriz) como acompanhamento. O `cached_input` OpenAI (#150), as matrizes antigas (#152) e a falha da fila de
similaridade (#151) deixaram de ser pendências.

**Atualização 2026-10-13 (V18.6):** as 4 mudanças da V18.6 (`v18.6-review-evidence`, `v18.6-benchmark-harness`,
`v18.6-validator-independence`, `v18.6-hypothesis-closure`) foram arquivadas e o status dos ADRs 002, 005, 009, 010, 012, 015,
019 e 020 foi atualizado (notas nos ADRs 007, 017 e 019 apontam para o ADR 020). O ADR 020 foi aceito pelo pesquisador em 2026-10-13; a
matriz com 3 repetições (só com confirmação do pesquisador) e a revisão posterior do ADR ficam como acompanhamento, sem bloquear o aceite.

**Atualização 2026-10-13:** as 32 mudanças de V16 a V18.5 foram concluídas e arquivadas em
`openspec/changes/archive/`, com os requisitos consolidados em `openspec/specs/`. Os itens que estavam
abertos nos `tasks.md` (validação no Pi 5, revisões de segurança e débitos) estão em
[`openspec/changes/archive/PENDENCIAS.md`](../../openspec/changes/archive/PENDENCIAS.md).

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
