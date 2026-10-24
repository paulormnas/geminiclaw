# Proposta: Experiência de outros projetos no primeiro plano e candidatos estruturais no ciclo

**ID:** `v18.9-cross-project-context` · **Versão:** V18.9

**Capacidades:** `knowledge-semantics`, `hypothesis-loop`

**ADRs de origem:** [ADR 026](../../../docs/decisions/adr_026_memoria_por_registros_de_resultado.md) §6; [ADR 013](../../../docs/decisions/adr_013_federacao_rede_publica.md) (oportunidades entre projetos).

**Depende de:** `v18.9-result-records` e `v18.9-memory-evaluation` (o gerador de candidatos). A ativação dos candidatos entre projetos depende da regra de decisão do E0.

## Por quê

Hoje o primeiro plano de um projeto novo não recebe nada de outros projetos: `resume_context` só entra na retomada. A experiência relacionada depende dos atalhos do veredito, e a fila de similaridade chegou a cerca de 16 mil pares. Os trabalhos de referência apresentam ao planejamento um recorte pequeno de evidência de problemas parecidos:
- o MLEvolve, por recuperação de sucessos e falhas;
- o KGpip, por semelhança do conteúdo dos dados;
- o HyGRAIL, com evidência das duas extremidades em texto de modelo fixo.

## O que muda

### Novo
- **Bloco `experiencia_de_problemas_semelhantes` no prompt do primeiro plano e de cada ciclo.** Traz até `RELATED_RECORDS_K` registros (padrão 5) de Problemas de outros projetos visíveis, com fatos, qualificação e limite de aplicabilidade, em texto de modelo fixo, via `wrap_data` (design §2).
- **Semelhança de Problemas:** combina o cosseno do texto com a semelhança de `caracteristicas_dados` (design §3).
- **Candidatos no ciclo:**
  - os candidatos de `src/knowledge/structural_candidates.py` do próprio projeto entram como sugestões ao Researcher;
  - os candidatos de outro projeto viram `Oportunidade` com `origem = "grafo"`, à espera do pesquisador;
  - controle por `CROSS_PROJECT_CANDIDATES` (padrão `false` até a regra de decisão do E0) (design §4).

### Modificado
- `related_experience` lê `RegistroResultado` em vez de atalhos ponderados por veredito, com ranking por semelhança × margem × réplicas × recência.
- A varredura de similaridade deixa de enfileirar a faixa de relacionados. Só duplicatas (≥ 0,90) vão para a fila. A relação entre Problemas é calculada sob demanda.

### Removido
- O requisito "Oportunidades entre projetos exigem evidência" baseado em |veredito|, substituído pela regra de registros.

## Impacto
- **Código:** `src/knowledge/semantic_index.py`, `src/knowledge/resume_context.py`, `src/orchestration/exploration.py`, `src/knowledge/suggestions.py` e `src/knowledge/similarity_queue.py`.
- **Dados:**
  - os pares `relacionado` pendentes na `similarity_queue` passam a `descartado` com o motivo `ADR 026` (sem `DROP`);
  - `Oportunidade` ganha a propriedade opcional `origem` (`curator` ou `grafo`; ausente = `curator`).
- **Custo:** o prompt de planejamento cresce até `RELATED_RECORDS_MAX_CHARS` (padrão 2500).

## Aprovações necessárias
- **Schema:** propriedade nova `Oportunidade.origem` (enum `curator`, `grafo`) e `registro_origem_id`.
- **Dados:** atualização em massa dos pares `relacionado` pendentes na `similarity_queue`.
