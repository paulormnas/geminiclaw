# ADR 026 — Memória por Registros de Resultado e Correlação entre Pesquisas (substitui o veredito)

**Status:** Aprovado (direção aprovada pelo pesquisador em 2026-10-21; mudanças OpenSpec aguardam aprovação)
**Data:** 2026-10-21
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** [`roadmaps/roadmap_V18.9.md`](../../roadmaps/roadmap_V18.9.md)
**ADRs relacionados:** ADR 015 §9 (equação de confiança, substituída), ADR 025 (calibração do veredito, deprecado), ADR 012 (Curator), ADR 013 (oportunidades entre projetos), ADR 021 §4 e §5 (estado das hipóteses e parada pelo objetivo), ADR 020 (independência do Validator)

**O que este ADR muda em outros ADRs:**
- **ADR 015 §9:** substituída. O veredito, os pesos `q·m·d·b`, os parâmetros `VERDICT_*` e os limiares derivados deixam de existir.
- **ADR 025:** passa a Deprecado. A etapa 3 (`v18.8-verdict-controlled-sessions`) é encerrada sem as seções 5.3, 5.4 e 6, e a etapa 4 é cancelada. O gerador sintético e o orquestrador de exploração continuam em uso pelos experimentos E1 e E2.
- **ADR 021 §4:** o estado da hipótese passa a vir da regra do §3 deste ADR, e não de `DECISION_EVAL_MIN_VERDICT`.
- **ADR 012:** o Curator deixa de ser a porta de entrada das ligações `FUNCIONOU_PARA`/`FALHOU_PARA`. Passa a qualificar registros (§4).

---

## Contexto

### Para que servia o veredito

O veredito (ADR 015 §9) foi criado para decidir quando uma exploração confirma uma hipótese e, depois, para ligar descobertas entre projetos quando |V| ≥ 0,3 e a similaridade dos problemas está na faixa de relacionados. Ele também governa o estado da hipótese (`DECISION_EVAL_MIN_VERDICT`), o portão do Curator para `Descoberta` funciona/não funciona (|V| ≥ 0,1), o bloqueio por `FALHOU_PARA` forte e a ordenação das sugestões.

### O que as medições mostraram (2026-10-18 a 2026-10-21)

- **Teto da equação:** com k evidências concordantes de peso cheio, V = (k/(k+2))². Uma evidência dá 0,111; são precisas três para chegar a 0,3 ([`docs/calibracao-veredito/2026-10-21-veredito-perto-de-zero.md`](../calibracao-veredito/2026-10-21-veredito-perto-de-zero.md)).
- **Defeitos do caminho até a evidência:** falha com valor medido vira `ambigua`; `divergence_note` aprova como divergente antes de checar o limiar. Nas duas verificações controladas, nenhuma hipótese passou de |V| = 0,067.
- **Cadeia de correlação inoperante:** `related_experience` só lê `FUNCIONOU_PARA`, `FALHOU_PARA` e `Descoberta`, e essas ligações só existem quando o Curator grava uma descoberta com veredito suficiente. Com o veredito perto de zero, nada passa. Além disso, o primeiro plano de um projeto novo não recebe experiência de outros projetos (`resume_context` só entra na retomada). A fila de similaridade acumulou cerca de 16 mil pares.

### O que a literatura faz

A revisão (notas em `~/Documents/Zotero_attachments/Mestrado/notas_leitura_grafo_conhecimento_2026-10-21.md`, fora do repositório) não encontrou sistema de pesquisa automatizada que use escore sintético de confiança para reaproveitar experimentos:

- **Referências medidas.** O AgentX (arXiv 2609.30001) compara cada experimento com a linha de base, com o pai e com o melhor ancestral (Δbase, Δparent, Δpath).
- **Registros qualificados.** "From Trajectories to Evidence" (arXiv 2608.05235) converte trajetórias em registros com limite de aplicabilidade, qualificados como reparo, restrição ou retido. A aplicação a um problema novo é hipótese a executar: o controlador LLM acertou 25% dos "aplicar".
- **Registro global de falhas.** "Recovering Wasted Compute" (COLM 2026) mostra o maior efeito controlado: medalhas de ouro de 22 para 38, execuções válidas de 81% para 100%, bugs repetidos de 46% para 7,8%.
- **Memória por tarefa.** No MLEvolve (arXiv 2606.06473), a ablação sem memória derrubou a taxa de medalhas de 81,8% para 68,2% no MLE-bench Lite.
- **Grafo como gerador de candidatos.** HyGRAIL, Krenn et al. e o KGpip usam o grafo para gerar candidatos (aresta ausente, atributos simples de rede, similaridade pelo conteúdo dos dados), não para despejar contexto.
- **Limites da transferência.** O EvoMemBench mostra que a memória pode prejudicar tarefas fáceis e que só transfere entre ambientes com processo de decisão semelhante.

### Decisão do pesquisador (2026-10-21)

- **Direção:** remover o veredito e adotar registros de resultado, com estado da hipótese por regra e correlação pela estrutura do grafo.
- **Métricas:** comparáveis às de outros estudos, com origem declarada, para permitir um benchmark público depois.
- **Dissertação:** a seção 4.3.1 é reescrita com essa proposta.

## Decisão

### 1. Princípio

O que foi medido é fato gravado pelo orquestrador. O que o LLM interpreta não decide se algo funcionou. Nenhum escore numérico de confiança é calculado nem apresentado aos agentes.

### 2. Registro de resultado

Para cada par (Problema, Abordagem com configuração), o orquestrador mantém um registro determinístico com:

- **Melhor valor:** o melhor valor medido da métrica do critério de sucesso, só em conjunto de teste ou validação cruzada;
- **Diferenças:** `delta_base` (para a linha de base do Problema) e `delta_pai` (para o experimento de origem, quando houver `DERIVADA_DE`);
- **Réplicas:** `n_replicas_independentes` (sementes ou conjuntos de dados distintos);
- **Alvo:** `atingiu_alvo`;
- **Condições:** conjunto de dados, métrica, qualificador e configuração;
- **Experimentos:** os identificadores dos experimentos que o sustentam.

O registro é recalculado a cada novo `Resultado` e nunca é escrito por agente.

### 3. Estado da hipótese por regra

Uma tentativa é **válida** quando o experimento produziu valor da métrica do critério, inclusive em `falha` com `criterio_nao_atendido` e em `divergente_documentado`. Tentativas sem métrica utilizável não mudam o estado e ficam com a causa registrada.

- **Validada:** o alvo é atingido em pelo menos `HYPOTHESIS_MIN_REPLICAS` tentativas válidas e independentes.
- **Refutada:** pelo menos `HYPOTHESIS_MIN_REFUTATIONS` tentativas válidas e independentes ficam abaixo do alvo e nenhuma o atinge.

O alvo é o do critério de sucesso do Problema, fixado antes dos experimentos, e `delta_base` usa o resultado do experimento de referência. Os dois valores começam em 2 e são configuráveis.

### 4. Qualificação pelo Curator

O Curator lê os registros e grava, sem alterar os fatos:

- a qualificação (`reparo`, `restricao` ou `retido`);
- o limite de aplicabilidade, em texto;
- a lição, quando houver.

A qualificação não muda o estado da hipótese. As ligações `FUNCIONOU_PARA`/`FALHOU_PARA` passam a derivar dos registros: `atingiu_alvo` com réplica, ou refutação pela regra do §3. Assim, deixam de depender de `Descoberta`.

### 5. Memória de falhas

Falhas com causa `abordagem` ou `infraestrutura` e assinatura conhecida formam um registro de falhas, separado em duas partes:

- **Global:** fatos do ambiente, como pacotes, dados e limites de memória;
- **Por abordagem.**

O registro é injetado no prompt do Developer como texto curto no formato "NÃO / USE", com teto de caracteres. Ele não se confunde com `Restricao`, que é decisão do pesquisador (ADR 021 §5.5).

### 6. Correlação entre pesquisas

- **Recorte no primeiro plano.** O Researcher recebe, já no primeiro plano, um recorte de até `RELATED_RECORDS_K` registros de Problemas semelhantes, com reparos e falhas. O texto segue um modelo fixo, sem resumo por LLM, e vai marcado como dado não confiável. A semelhança combina o texto do Problema com `caracteristicas_dados`.
- **Candidatos estruturais.** O grafo propõe candidatos sem LLM, ordenados por atributos simples (semelhança, margem, réplicas, diversidade):
  - **transferência:** abordagem com registro de sucesso em Problema semelhante e sem tentativa no atual;
  - **composição:** duas variações que melhoraram o mesmo pai;
  - **ramo pouco explorado.**
- **Candidatos de outro projeto** viram `Oportunidade` à espera do pesquisador (ADR 013) e, se aprovados, hipóteses a executar.
- **Fila de similaridade.** A fila deixa de receber a faixa de relacionados: a relação passa a ser calculada sob demanda. A fusão de duplicatas (≥ 0,90) continua.

### 7. Avaliação

| Métrica | Origem |
|---|---|
| Taxa de sucesso | MLE-bench, MLEvolve, Wasted Compute |
| Taxa de execuções válidas | MLE-bench, Wasted Compute |
| Ganho sobre a linha de base | AgentX |
| Falhas repetidas | Wasted Compute |
| AUC com corte temporal | Krenn et al., HyGRAIL |

Todos os experimentos rodam com orçamento fixo por tarefa.

| Experimento | O que mede |
|---|---|
| **E0, replay offline** | AUC dos candidatos estruturais contra ordenação aleatória e só por semelhança |
| **E1** | Memória de falhas, com e sem |
| **E2** | Transferência: sem memória, memória plana, recorte do grafo e recorte de Problema diferente |
| **E3** | Estudo de caso qualitativo, fora do repositório |

O relato segue a lista de verificação de Ding et al. (2026): tentativas, regra de seleção, linha de base e independência do avaliador.

**Suficiência dos dados atuais para o E0 (verificado em 2026-10-21).** Os 13 grafos arquivados em `~/bench/` não bastam:

- cinco estão vazios, porque o crédito acabou;
- os oito restantes têm um único Problema cada, todos do mesmo gerador;
- somam 11 eventos de melhoria da métrica principal, e só 2 arestas `DERIVADA_DE`.

Não há pares entre problemas nem positivos suficientes para estimar a AUC. O E0 depende de um corpus com problemas relacionados (questão em aberto 1).

## Consideradas e Rejeitadas

### A. Corrigir o veredito (prior 0,5 na refutação, `divergence_note`, falha com valor)
A simulação mostrou ganho na refutação, mas as correções mantêm um escore que os agentes não usam e que nenhum trabalho de referência adota. Cada uso continuaria dependendo de calibrar 24 parâmetros. As correções de pipeline (falha com valor e divergência abaixo do limiar) são aproveitadas no §3.

### B. Julgamento do LLM sobre a aplicabilidade como critério
Teve 25% de precisão afirmativa em "From Trajectories to Evidence". A aplicação vira hipótese a executar.

### C. Rede neural de grafos para prever ligações
Na nossa escala, os atributos simples ficam perto dos melhores métodos (Krenn et al.), e uma rede neural exigiria dados de treino que não existem.

### D. Resumos gerados por LLM como memória
No AgentX, os resumos não superaram a evidência bruta, e o HyGRAIL obteve melhor resultado com texto de modelo fixo.

## Consequências

- **Remoções:**
  - `src/knowledge/verdict.py`, `verdict_for_hypothesis`, `verdict_for_scope` e a ferramenta `verdict_breakdown`;
  - as variáveis `VERDICT_*`, `KNOWLEDGE_SHORTCUT_MIN_VERDICT` e `DECISION_EVAL_MIN_VERDICT`, que passam a dar erro de configuração com mensagem de remoção;
  - as propriedades `suporte`, `certeza`, `veredito` e `modelo_veredito` de `Hipotese`, e `veredito`, `modelo_veredito` e `confianca` de `Descoberta`.
  - Isso **muda o schema e exige aprovação**.
- **Laboratório do veredito:** `scripts/verdict_lab/` deixa de ter função. O gerador `controlled/` e o orquestrador de exploração permanecem.
- **Dissertação:** a seção 4.3.1 deixa de descrever a equação (reescrita em 2026-10-21, fora do repositório).
- **Risco:** a regra do §3 é mais simples e pode validar por sorte com duas réplicas em ruído. Mitigação: as réplicas exigem sementes ou conjuntos de dados distintos, e o E2 mede a falsa validação no regime N do gerador.

## Mudanças OpenSpec

1. `v18.9-result-records`: §1 a §4 e as remoções.
2. `v18.9-failure-memory`: §5.
3. `v18.9-memory-evaluation`: §7, com o gerador de candidatos como módulo puro, o replay com AUC, as métricas e o pré-registro.
4. `v18.9-cross-project-context`: §6 (recorte no primeiro plano, candidatos no ciclo, fila).

## Questões em aberto

1. **Corpus do E0.** Há duas opções, que podem ser combinadas:
   - **(a)** famílias de Problemas relacionados geradas pelo gerador controlado, o que exige sessões e, portanto, custo de LLM;
   - **(b)** um histórico público de experimentos com muitos conjuntos de dados, como o OpenML. Ainda não lido; precisa ser avaliado antes.
2. **Crédito para E1 e E2,** que define o número de réplicas.
3. **Valores iniciais de `HYPOTHESIS_MIN_REPLICAS` e `HYPOTHESIS_MIN_REFUTATIONS`** (proposta: 2 e 2).
