# ADR 010 — Propósito: Assistente Digital de Pesquisa Científica

**Status:** Parcialmente implementado — V16, V17 e V18 mergeadas; V18.5 (parcial) e V19 pendentes (aprovado em 2026-10-01 pelo pesquisador responsável; atualizado em 2026-10-08)
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Substitui:** ADR 001 (a partir da aprovação, 2026-10-01)
**ADRs relacionados:** ADR 009 (conhecimento experimental), ADR 011 (provedores), ADR 012 (Curator), ADR 013 (federação)


## Estado da implementação (2026-10-08)

| Mudança OpenSpec | Estado | PR |
|---|---|---|
| [`v16-research-assistant-prompts`](../../openspec/changes/v16-research-assistant-prompts/proposal.md) | Implementada, com pendências | #63 |
| [`v16-pipeline-robustness`](../../openspec/changes/v16-pipeline-robustness/proposal.md) | Implementada, com pendências | #95 |
| [`v18-usage-limits`](../../openspec/changes/v18-usage-limits/proposal.md) | Implementada, com pendências | #68 |
| [`v18-research-continuity`](../../openspec/changes/v18-research-continuity/proposal.md) | Implementada, com pendências | #108 |
| [`v18-hypothesis-loop`](../../openspec/changes/v18-hypothesis-loop/proposal.md) | Implementada, com pendências | #109, #115 |
| [`v19-equipment-control`](../../openspec/changes/v19-equipment-control/proposal.md) | Não iniciada | — |

---

## Contexto

O ADR 001 definiu o GeminiClaw como um **harness de execução**: o sistema recebia contexto
pré-curado e executava tarefas, sendo explicitamente proibido de gerar hipóteses sem
orientação humana. Com a V15 concluída (modos de sessão, pipeline `input_context/`,
epistemologia científica do Researcher, contratos de código reproduzível, human-in-the-loop e
relatório científico), o sistema já executa experimentos com rigor.

O pesquisador responsável redefiniu o caso de uso principal — gatilho de revisão previsto no
próprio ADR 001. O objetivo passa a ser um **assistente digital de pesquisa**: um sistema que
não apenas executa, mas conduz a investigação.

---

## Decisão

O GeminiClaw é um **assistente digital de pesquisa científica** capaz de conduzir
experimentos, formular hipóteses, validar suposições e relatar resultados.

### O que o sistema FAZ

1. **Parte de insumos fornecidos pelo pesquisador responsável:** artigos, dados e demais
   materiais que dão início a uma pesquisa (via `input_context/`, Spec G9).
2. **Formula hipóteses** a partir desses insumos, dos resultados de seus próprios experimentos
   e do conhecimento experimental acumulado (ADR 009) — inclusive por transferência: o que
   funcionou no problema X como candidato para o problema Y.
3. **Conduz experimentos** decompostos em DAG, com contratos de reprodutibilidade (Spec G2).
   Todo código gerado executa em sandbox isolado, nunca no computador principal (ADR 014).
4. **Valida suposições e resultados** contra evidências em disco (`metrics.json`), nunca contra
   texto otimista gerado por LLM.
5. **Registra o que aprendeu:** o que funcionou, o que não funcionou, oportunidades a explorar
   e o porquê das decisões de caminho (ADR 012).
6. **Continua explorando** de forma iterativa até encontrar uma solução ou atingir um limite
   de uso definido pelo pesquisador responsável (ADR 012).
7. **Nunca perde o avanço da pesquisa** ao parar: ver "Continuidade entre execuções" abaixo.
8. **Relata resultados** em relatório científico estruturado e rastreável (Spec G8).
9. **Busca na web para suporte técnico e para enriquecer o contexto das decisões:**
   documentação de bibliotecas, APIs e erros (como no ADR 001) e consultas simples que ajudem
   o Researcher a responder perguntas dos outros agentes, sobretudo nos modos `semi` e `auto`
   (ADR 012 §8). **Não** são buscas bibliográficas nem de artigos (ver "O que o sistema NÃO
   FAZ"). Toda consulta respeita o ADR 019 §3: o texto enviado a um buscador não contém
   dados brutos de pesquisa.
   *(Redação ampliada em 2026-10-01 por decisão do pesquisador responsável.)*

### O que o sistema NÃO FAZ

- ❌ **Busca bibliográfica / revisão de literatura.** Continua fora do escopo. Os insumos
  bibliográficos são responsabilidade do pesquisador responsável ou de um agente externo
  especializado, que opera separadamente e alimenta o GeminiClaw via `input_context/`.
- ❌ **Inventar dados ou conclusões.** Toda conclusão precisa de evidência rastreável.
- ❌ **Agir sem limites.** A exploração é sempre limitada por orçamento definido pelo
  pesquisador responsável (tokens, tempo, retentativas, etc.).
- ❌ **Recomeçar do zero após uma parada.** Atingir um limite interrompe a execução, não a
  pesquisa.

### Autonomia governada pelo modo de sessão

A formulação e execução de hipóteses respeita o `SessionMode` (Spec G10):

- **`assisted`**: hipóteses geradas pelo sistema passam pela aprovação do pesquisador
  responsável antes de serem executadas.
- **`semi` / `auto`**: o sistema executa as hipóteses mais promissoras dentro do orçamento,
  documentando cada decisão.

### Continuidade entre execuções

O sistema sempre roda dentro dos limites definidos pelo pesquisador responsável (tokens,
tempo, retentativas — ADR 012). Ao atingir um limite, ele **não descarta o trabalho feito**:
antes de parar, registra todo o avanço da pesquisa, incluindo no mínimo:

- o estado do plano e das subtarefas (concluídas, em andamento, pendentes);
- os resultados e artefatos já produzidos;
- as hipóteses em aberto, validadas e refutadas;
- as decisões de caminho e suas justificativas;
- as descobertas registradas pelo Curator (ADR 012) e o motivo da parada.

Na execução seguinte, o sistema **retoma a partir desse registro** e usa toda a informação da
sessão ou execução anterior, sem recomeçar do zero. O `geminiclaw resume` da Spec G5 é o
ponto de partida; o formato e o conteúdo do registro serão definidos na spec. O mesmo vale
para paradas inesperadas (queda de energia, erro fatal): o avanço deve ser registrado de forma
incremental, não apenas no encerramento.

### Visão de longo prazo

Nós do GeminiClaw em diferentes instituições poderão compartilhar descobertas e
oportunidades de pesquisa em uma rede pública (ADR 013). Oportunidades vindas da rede são
apenas documentadas e apresentadas: cabe ao pesquisador responsável decidir se serão
investigadas. Essa capacidade é a **última** a ser
implementada, após todas as funcionalidades de pesquisa estarem completas e validadas.

### Sequência de implementação

> Estado em 2026-10-01: V16 concluída. V17 parcial (armazenamento do grafo e veredito de
> evidência). A V18.5 (ADR 019) entra depois da V18 e antes da V19. Antes da V17 completa,
> uma etapa de robustez do pipeline (revisão e validação menos frágeis, normalização do plano)
> foi decidida em 2026-10-01 para que todos os modelos completem a tarefa de referência.

```
V16  Fundações: provedores agnósticos (ADR 011), agentes em processo (ADR 014), revisão de prompts
V17  Camada de conhecimento experimental (ADR 009) + agente Curator (ADR 012)
V18  Ciclo de hipóteses: formulação, exploração iterativa, validação de suposições
V19  Controle de equipamentos físicos (Spec G7, antes prevista como V16)
V20  Federação entre nós (ADR 013)
```

---

## Alternativas Consideradas

### Alternativa A: Manter o ADR 001 (harness de execução)

**Descartado porque:** limita o sistema a executar o que lhe é pedido, desperdiçando a
experiência acumulada entre sessões e impedindo que ele contribua com a formulação de
hipóteses — exatamente o que o pesquisador responsável deseja.

### Alternativa B: Incluir busca bibliográfica autônoma

**Descartado porque:** os motivos do ADR 001 (dependências externas, credenciais de bases
pagas, requisitos próprios como PRISMA) continuam válidos. A busca bibliográfica deve ser uma
tarefa de outro agente que opera separadamente.

---

## Consequências

### Positivas

- O sistema passa a contribuir com a investigação, não apenas com a execução.
- A experiência acumulada torna cada nova pesquisa mais eficiente.
- Limites de uso não desperdiçam trabalho: uma pesquisa longa pode avançar ao longo de várias
  execuções.
- O escopo permanece claro: a entrada de literatura continua sendo responsabilidade externa.

### Negativas / Trade-offs

- **Prompts de todos os agentes precisam ser revisados** — hoje eles refletem o ADR 001
  (ex.: proibição de gerar hipóteses). Isso é trabalho da V16.
- **Maior risco de gasto de recursos:** exploração iterativa exige limites de uso bem
  definidos e respeitados (ADR 012).
- **Registro incremental do avanço** acrescenta escrita frequente em disco e banco, e o
  registro precisa ser consistente mesmo se a parada ocorrer no meio de uma subtarefa.
- **Hipóteses de baixa qualidade** podem consumir orçamento; a pontuação e priorização de
  hipóteses serão definidas na spec da V18.
- **A Spec G7** (`roadmaps/specs/G7_equipment_control_mhs.md`) deve ser renumerada de V16
  para V19 ao criar os roadmaps.

---

## Revisão

Este ADR deve ser revisado quando:
- A busca bibliográfica for reconsiderada como parte do sistema.
- A federação entre nós (ADR 013) for implementada.
- O caso de uso principal for novamente redefinido pelo pesquisador responsável.
