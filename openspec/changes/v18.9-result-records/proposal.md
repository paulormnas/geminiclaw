# Proposta: Registros de resultado e estado da hipótese por regra (remove o veredito)

**ID:** `v18.9-result-records` · **Versão:** V18.9

**Capacidades:** `evidence-scoring`, `hypothesis-loop`, `knowledge-graph`, `curator`, `claim-verification`

**ADRs de origem:** [ADR 026](../../../docs/decisions/adr_026_memoria_por_registros_de_resultado.md) §1 a §4 e "Consequências"; substitui o [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9 e o [ADR 025](../../../docs/decisions/adr_025_calibracao_do_veredito.md).

**Depende de:** nada em aberto (`v18.8-verdict-controlled-sessions` é encerrada por esta etapa).

**Nota de data:** escrita em 2026-10-21, a partir da decisão do pesquisador da mesma data.

## Por quê

O veredito não consegue concluir com os dados que o sistema produz. Uma evidência dá V = 0,111 e três dão 0,36, e nas verificações controladas nenhuma hipótese passou de 0,067. Como o portão do Curator, os atalhos `FUNCIONOU_PARA`/`FALHOU_PARA` e a experiência relacionada dependem dele, a memória entre projetos fica vazia. Os sistemas de referência (AgentX, "From Trajectories to Evidence") comparam resultados medidos com referências explícitas, em vez de calcular um escore de confiança (ADR 026, Contexto).

## O que muda

### Novo
- Nó `RegistroResultado`, um por par (Problema, Abordagem com configuração), mantido só pelo orquestrador. Guarda o melhor valor, `delta_base`, `delta_pai`, as réplicas independentes, `atingiu_alvo`, as condições e os experimentos (design §2).
- Regra de estado da hipótese, com `HYPOTHESIS_MIN_REPLICAS` e `HYPOTHESIS_MIN_REFUTATIONS` (padrão 2 e 2) (design §3).
- Tentativa válida inclui `falha` com `criterio_nao_atendido` e `divergente_documentado` que tenham valor da métrica do critério (design §3.1).
- Ferramenta do Curator `qualify_record` (reparo, restrição ou retido, com limite de aplicabilidade) e leitura `result_records` (design §4).

### Modificado
- `FUNCIONOU_PARA`/`FALHOU_PARA` passam a ser derivadas dos registros pelo orquestrador, e não das descobertas (design §5).
- Transições de status ao fim do ciclo seguem a regra, e o evento `hipotese_transicao` troca `veredito_*` por `regra` e pelas contagens (design §3.3).
- Avaliação de decisões (`acertada`/`nao_acertada`) pelo estado da hipótese.
- Ordenação de hipóteses (`_prior_support`) e sugestões (`_variation_candidates`) leem registros em vez de veredito.
- Evento `veredito_indisponivel` renomeado para `metrica_indisponivel`.

### Removido
- `src/knowledge/verdict.py`, `verdict_for_hypothesis`, `verdict_for_scope` e a ferramenta `verdict_breakdown`.
- Variáveis `VERDICT_*` (24), `KNOWLEDGE_SHORTCUT_MIN_VERDICT` e `DECISION_EVAL_MIN_VERDICT`. Passam a dar `ConfigurationError` com mensagem de remoção, como `SOLUTION_MIN_VERDICT`.
- Propriedades `suporte`, `certeza`, `veredito` e `modelo_veredito` de `Hipotese`, e `veredito`, `modelo_veredito` e `confianca` de `Descoberta`.
- Peso das arestas `SUSTENTA`/`REFUTA`. As arestas continuam, agora sem `peso`.
- `scripts/verdict_lab/` (exceto `controlled/`, usado por E1 e E2) e a CLI de veredito em `terminal_consult`.

### Fora do escopo
- Memória de falhas (`v18.9-failure-memory`), recorte entre projetos (`v18.9-cross-project-context`) e avaliação (`v18.9-memory-evaluation`).

## Impacto

- **Código:** `src/knowledge/` (verdict, service, hypothesis_cycle, ingestion, suggestions, semantic_index, curator_tools, curator_reads, schema), `src/agents/curator/`, `src/cli/terminal_consult.py`, `src/config.py`, `scripts/verdict_lab/` e testes.
- **Schema:** novo nó, propriedades removidas e migração dos grafos existentes (design §6).
- **Custo:** nenhuma chamada de LLM nova.

## Aprovações necessárias

- **Alteração de schema do grafo:** nó `RegistroResultado` com as arestas `REGISTRA`, `SOBRE` e `BASEADO_EM`, e remoção de propriedades.
- **Migração dos grafos existentes:** os registros são recalculados a partir dos `Resultado`, e as propriedades de veredito são removidas.
- **Exclusão de arquivos:** `src/knowledge/verdict.py` e `scripts/verdict_lab/` (exceto `controlled/`).
