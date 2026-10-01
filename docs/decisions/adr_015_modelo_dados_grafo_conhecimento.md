# ADR 015 — Modelo de Dados do Grafo de Conhecimento e Ligação com Embeddings

**Status:** Aprovado em 2026-10-01 pelo pesquisador responsável — questões discutidas e decididas; valores iniciais a calibrar com dados reais; implementação pendente (armazenamento e veredito prontos)
**Data:** 2026-09-28
**Autores:** Arquiteto de Soluções (GeminiClaw), com revisão do pesquisador responsável
**ADRs relacionados:** ADR 009 (camada de conhecimento), ADR 010 (propósito), ADR 011 (embeddings locais), ADR 012 (Curator), ADR 013 (federação), ADR 014 (execução no host)

---

## Contexto

O ADR 009 decidiu que os agentes constroem um grafo de conhecimento experimental (Apache AGE)
complementado por similaridade semântica (Qdrant), mas deixou em aberto os tipos de nós, as
relações, as propriedades e quem escreve cada parte. Este ADR propõe esse modelo.

Perguntas que o grafo precisa responder (critério de sucesso do modelo):

1. "Para um problema parecido com Y, o que já funcionou, com qual configuração, e o que
   falhou?"
2. "Por que, na sessão S, o caminho A foi escolhido e não o B — e o que aconteceu depois?"
3. "Quais hipóteses estão em aberto, validadas ou refutadas, e com base em quais evidências?"
4. "Qual descoberta em um projeto pode abrir uma oportunidade em outro?"
5. "Onde a pesquisa parou e o que falta?" (continuidade entre execuções, ADR 010)

---

## Decisão (proposta)

### 1. Princípios do modelo

- **Fatos vs. conhecimento.** O grafo separa dois tipos de informação:
  - **Fatos estruturais** — o que aconteceu (sessões, experimentos, resultados, abordagens
    aplicadas). São escritos **pelo orquestrador de forma determinística**, a partir dos
    artefatos em disco (`params.json`, `metrics.json`, estado do DAG). Nenhum LLM os inventa.
  - **Conhecimento interpretado** — o que se aprendeu (descobertas, decisões de caminho,
    oportunidades). É escrito **por agentes**, sempre ligado aos fatos que o sustentam.
- **Afirmações são nós, não só arestas.** Uma descoberta como "a abordagem A funciona para o
  problema X" é um nó `Descoberta` com proveniência, confiança e status — pode ser contestada,
  substituída ou reforçada. Arestas de atalho (`FUNCIONOU_PARA`) existem para consulta rápida,
  mas sempre apontam para a `Descoberta` que as justifica.
- **Agnóstico à ferramenta.** Nenhum tipo de nó é específico de redes neurais. "Abordagem"
  cobre arquiteturas, algoritmos, testes estatísticos, pipelines, protocolos, instrumentos.
- **Similaridade é pista, nunca evidência.** Relações vindas de embeddings são marcadas como
  derivadas e só viram conhecimento após análise do Curator com justificativa.
- **Menos nós, mais significado.** Um nó só existe se aponta um novo caminho de pesquisa ou
  documenta um caminho explorado — inclusive os que não chegaram a uma conclusão (§10).
- **Vocabulário controlado.** Domínios e métricas vêm de catálogos, não de texto livre (§4).
- **Pronto para federação desde já** (ADR 013 §6): ID estável, proveniência, visibilidade
  e origem em todo nó.

### 2. Tipos de nós

| Nó | O que representa | Quem escreve |
|---|---|---|
| `Projeto` | Uma linha de pesquisa, que atravessa várias sessões | Orquestrador (a partir do pesquisador) |
| `Sessao` | Uma execução, com seus limites e motivo de parada | Orquestrador |
| `Insumo` | Artigo, dataset ou material fornecido pelo pesquisador | Orquestrador (a partir de `input_context/`) |
| `Problema` | O problema de pesquisa em **alto nível**, descrito como o resumo de um artigo que ainda não tem resultados; independente do projeto, é a unidade que permite transferir conhecimento de X para Y | Researcher (rascunho a partir dos insumos) + pesquisador (confirmação) + Curator (deduplicação) |
| `Hipotese` | Uma afirmação testável — é onde fica a especificidade que o `Problema` não tem | Researcher (ou pesquisador) |
| `Abordagem` | Um método ou ferramenta, de qualquer tipo — inclusive uma configuração promovida (§5) | Researcher / Curator (deduplicação) |
| `Experimento` | Uma execução concreta (subtarefa do DAG) que testa algo | Orquestrador |
| `Resultado` | Uma métrica medida por um experimento | Orquestrador (de `metrics.json`) |
| `Decisao` | Uma decisão de caminho no DAG: o que foi escolhido, o que foi descartado e por quê | Researcher |
| `Descoberta` | Memória consolidada: o que funciona, o que não funciona, sob quais condições, e caminhos que ficaram sem conclusão | Curator |
| `Oportunidade` | Um caminho promissor documentado, aguardando decisão humana | Curator |
| `Dominio` | Termo do vocabulário controlado de áreas do conhecimento | Curator (proposta) + pesquisador (aprovação) |
| `Metrica` | Entrada do catálogo de métricas, com nome canônico | Curator (proposta) + pesquisador (aprovação) |

### 3. Propriedades comuns a todos os nós

| Propriedade | Descrição |
|---|---|
| `id` | Identificador estável e global (ex.: UUIDv7). É o mesmo ID usado no Qdrant. |
| `criado_em`, `atualizado_em` | Datas ISO-8601 |
| `criado_por` | Papel do agente + modelo LLM (ex.: `curator/qwen2.5:7b`), `orquestrador`, ou `pesquisador` (pedido feito via Curator, §11) |
| `projeto_id` | Projeto de origem |
| `sessao_id` | Sessão de origem |
| `visibilidade` | `privado` (padrão) ou `compartilhavel` (ADR 013) |
| `origem_no` | `local` ou identificador do nó remoto (federação; hoje sempre `local`) |
| `versao_schema` | Versão deste modelo de dados |

Nós criados pelo Curator têm ainda `justificativa_criacao` (por que o nó é significativo) e
`nos_consultados` (IDs verificados na deduplicação) — ver §10.

### 4. Propriedades específicas (proposta inicial)

**`Projeto`** — `titulo`, `objetivo`, `status` (`ativo` / `pausado` / `concluido`). Domínios
via aresta `NO_DOMINIO` (um projeto interdisciplinar pode ter vários).

**`Sessao`** — `modo` (`assisted` / `semi` / `auto`), `inicio`, `fim`, `motivo_parada`
(`solucao_encontrada` / `limite_tokens` / `limite_tempo` / `limite_retentativas` /
`limite_conexao` / `erro` / `interrompida`), `consumo` (tokens, tempo, retentativas).

**`Insumo`** — `tipo` (`artigo` / `dataset` / `protocolo` / `outro`), `titulo`, `hash_conteudo`,
`caminho` (em `input_snapshot/`).

**`Problema`** — `titulo`, `resumo` (descrição abrangente, no estilo de resumo de artigo sem
resultados: contexto, lacuna, objetivo, o que seria um avanço), `classe` (ex.: classificação,
regressão, otimização, síntese, datação, inferência causal), `caracteristicas_dados`
(tamanho, modalidade, ruído…), `criterio_sucesso` (métrica do catálogo, alvo e menor efeito
relevante `delta_min`). Domínios via `NO_DOMINIO`.

**`Hipotese`** — `enunciado`, `justificativa`, `status` (`proposta` / `em_teste` / `validada` /
`refutada` / `inconclusiva` / `abandonada`), `origem` (`pesquisador` / `researcher` / `curator` /
`oportunidade`), `suporte` e `certeza` (0–1) e `veredito` (−1 a +1), calculados das
evidências (§9), e `n_tentativas` (inclusive as sem resultado).

**`Abordagem`** — `nome` canônico, `tipo` (`arquitetura` / `algoritmo` / `teste_estatistico` /
`pipeline` / `protocolo` / `instrumento` / `biblioteca` / `configuracao` / `outro`),
`descricao`, `versao` (quando aplicável), `config_normalizada` (só para `tipo: configuracao`).

**`Experimento`** — `subtarefa_id`, `status` (`sucesso` / `falha` / `divergente_documentado`),
`hash_params`, `seed`, `hash_codigo`, `ambiente` (hardware, versões principais), `caminho_artefatos`.

**`Resultado`** — `nome_original` (como veio no `metrics.json`), `valor`, `unidade`,
`baseline` (quando houver), `status_validacao` (do Validator), `caminho_metrics`. A métrica
canônica vem da aresta `MEDE`.

**`Decisao`** — `contexto` (o que estava em jogo), `justificativa`, `criterio` (ex.: custo,
evidência prévia, restrição de hardware), `resultado_posterior` (preenchido depois: a escolha
se mostrou boa?).

**`Descoberta`** — `tipo` (`funciona` / `nao_funciona` / `condicional` / `licao_de_caminho` /
`caminho_sem_conclusao`), `enunciado`, `condicoes` (em que contexto vale), `veredito`
(−1 a +1, §9) e `confianca` (= |veredito|),
`n_evidencias`, `status` (`ativa` / `contestada` / `substituida`). Para
`caminho_sem_conclusao`: `ponto_de_parada`, `motivo` (limite de uso, abandono, falta de
recursos, bloqueio técnico) e `proximo_passo_sugerido`.

**`Oportunidade`** — `enunciado`, `justificativa`, `status` (`documentada` / `aprovada` /
`rejeitada` / `em_investigacao` / `concluida`), `decidido_por`, `decidido_em`,
`motivo_decisao`. Nenhuma oportunidade passa de `documentada` sem decisão humana.

**`Dominio`** — `termo` canônico, `nivel` (grande área / área / subárea / especialidade),
`sinonimos`, `codigo_cnpq` (quando vier da tabela do CNPq; vazio para termos criados no
projeto), `status` (`candidato` / `aprovado`).

**`Metrica`** — `nome` canônico, `sinonimos` (ex.: `acc`, `accuracy`, `acuracia`), `sentido`
(`maior_melhor` / `menor_melhor`), `unidade`, `faixa` (ex.: 0–1), `familia` (ex.: erro de
regressão, classificação, rendimento de síntese), `status` (`candidato` / `aprovado`).

### 5. Relações

```
Estrutura (orquestrador)
  (Sessao)-[:PERTENCE_A]->(Projeto)
  (Sessao)-[:CONTINUA]->(Sessao)                      continuidade entre execuções
  (Projeto)-[:INVESTIGA]->(Problema)
  (Projeto)-[:RECEBEU]->(Insumo)
  (Experimento)-[:EXECUTADO_EM]->(Sessao)
  (Experimento)-[:APLICOU {config, hash_params}]->(Abordagem)
  (Experimento)-[:USOU]->(Insumo)
  (Experimento)-[:PRODUZIU]->(Resultado)
  (Resultado)-[:MEDE]->(Metrica)

Raciocínio (Researcher)
  (Hipotese)-[:SOBRE]->(Problema)
  (Hipotese)-[:PROPOE]->(Abordagem)
  (Hipotese)-[:DERIVADA_DE]->(Insumo | Descoberta | Oportunidade)
  (Experimento)-[:TESTA]->(Hipotese)
  (Decisao)-[:TOMADA_EM]->(Sessao)
  (Decisao)-[:ESCOLHEU]->(Abordagem | Hipotese)
  (Decisao)-[:DESCARTOU {motivo}]->(Abordagem | Hipotese)
  (Decisao)-[:INFORMADA_POR]->(Descoberta)            a memória influenciou a escolha

Avaliação (Validator / orquestrador)
  (Resultado)-[:SUSTENTA {peso}]->(Hipotese)
  (Resultado)-[:REFUTA {peso}]->(Hipotese)

Conhecimento (Curator)
  (Descoberta)-[:BASEADA_EM]->(Resultado | Experimento | Decisao)   evidência obrigatória
  (Descoberta)-[:SOBRE]->(Abordagem | Problema | Hipotese)
  (Descoberta)-[:CONTRADIZ]->(Descoberta)
  (Descoberta)-[:SUBSTITUI]->(Descoberta)
  (Abordagem)-[:FUNCIONOU_PARA {metrica, melhor_valor, config, n_exp, descoberta_id}]->(Problema)
  (Abordagem)-[:FALHOU_PARA {motivo, n_exp, descoberta_id}]->(Problema)
  (Abordagem)-[:VARIANTE_DE]->(Abordagem)
  (Abordagem)-[:COMPONENTE_DE]->(Abordagem)           pipelines
  (Oportunidade)-[:ORIGINADA_DE]->(Descoberta)
  (Oportunidade)-[:SUGERE]->(Abordagem | Hipotese)
  (Oportunidade)-[:PARA]->(Problema)
  (Oportunidade)-[:GEROU]->(Hipotese)                 só após aprovação humana

Vocabulário (Curator + aprovação do pesquisador)
  (Projeto | Problema)-[:NO_DOMINIO]->(Dominio)
  (Dominio)-[:SUBAREA_DE]->(Dominio)
  (Metrica)-[:RELACIONADA_A]->(Metrica)               mesma família, não intercambiáveis

Semântica (derivada de embeddings — ver §6)
  (a)-[:SEMELHANTE_A {score, modelo, versao, status}]->(b)
```

**Propriedades comuns a todas as arestas:** `criado_em`, `criado_por`, `origem`
(`fato` / `afirmado` / `derivado`), `evidencias` (lista de IDs), `status`
(`candidata` / `confirmada` / `contestada`).

**Configuração.** Por padrão, a configuração é propriedade da aresta `APLICOU`. Quando uma
mesma configuração é aplicada repetidamente em projetos diferentes — sobretudo com resultado
positivo — ela passa a ser uma abordagem em si: o Curator a **promove** a `Abordagem` com
`tipo: configuracao`, ligada por `VARIANTE_DE` à abordagem base. A comparação usa a
`config_normalizada` (apenas os hiperparâmetros do método — sem caminhos, sementes ou
parâmetros de ambiente), já que o `hash_params` bruto quase nunca coincide entre projetos.
Critério de promoção (decidido pelo pesquisador): **validada em ≥ 2 projetos, com ≥ 3
resultados positivos validados.**

### 6. Ligação com embeddings

**Quais nós são vetorizados:** os que têm conteúdo textual com significado — `Projeto`,
`Problema`, `Hipotese`, `Abordagem`, `Descoberta`, `Decisao` (justificativa) e `Oportunidade`.
`Experimento` e `Resultado` são estruturados e numéricos; não são vetorizados. `Dominio` e
`Metrica` são vetorizados apenas para sugerir o termo canônico. Os `Insumo`s continuam
indexados em trechos na coleção de documentos existente.

**Chave compartilhada:** o ponto no Qdrant usa **o mesmo `id` do nó** no grafo. Não há vetor
dentro do AGE, e não há relação duplicada no Qdrant.

**Payload no Qdrant** (para filtrar antes da busca): `tipo_no`, `projeto_id`, `dominios`,
`status`, `visibilidade`, `modelo_embedding`, `versao_embedding`, `dimensao`, `hash_texto`.

**Documentos de entrada (`Insumo`):** artigos, relatórios, conjuntos de dados e similares são
vetorizados em trechos na coleção de documentos. Antes de gerar o vetor, o texto do trecho é
**enriquecido com metadados** do documento (título, tipo, origem, domínio, contexto do
projeto), para que a busca semântica encontre o trecho pelo que ele significa no projeto, não
só pelas palavras. *(Decisão de princípio do pesquisador responsável em 2026-10-01; a escolha
dos metadados, o formato do texto enriquecido e o momento da indexação ficam para spec e
discussão posterior.)*

**Texto canônico por tipo:** cada tipo tem um modelo de texto usado para gerar o vetor
(ex.: `Problema` = título + resumo + classe + características dos dados + critério de sucesso).
O `hash_texto` permite detectar quando o nó mudou e precisa ser revetorizado.

**Fluxo de escrita:**

```
1. Nó gravado no AGE (fonte da verdade), com estado de vetorização "pendente"
2. Texto canônico montado → embedding local (ADR 011) → upsert no Qdrant
3. Estado de vetorização marcado como "ok" (com modelo e versão)
```

Se o passo 2 falhar, o nó continua válido e é revetorizado depois. Uma rotina de
reconciliação corrige divergências — inclusive ao trocar o modelo de embedding.

**Consulta híbrida** (o núcleo das conexões semânticas) — exemplo para a pergunta 1:

```
1. Qdrant: Problemas semanticamente próximos do novo Problema Y  (top-k, filtrado por status)
2. AGE:    a partir deles, percorrer FUNCIONOU_PARA / FALHOU_PARA / Descoberta / Decisao
3. Ranking: similaridade × confiança (|veredito|, §9) × recência
```

**Arestas `SEMELHANTE_A` — pares de tipos:** `Projeto↔Projeto`, `Problema↔Problema`,
`Abordagem↔Abordagem`, `Descoberta↔Descoberta` e `Oportunidade↔Oportunidade`; e, para
conectar áreas diferentes, `Descoberta↔Problema` de outro projeto — neste par, só entram
descobertas com evidência ao menos **moderada** (`|veredito| ≥ 0,3`, §9), sejam elas positivas
ou negativas. `Hipotese` e `Decisao` são vetorizadas para busca, mas não geram `SEMELHANTE_A`.

**Três faixas de similaridade**, que refletem o objetivo de não repetir, mas explorar
variações e conectar ideias diferentes:

| Faixa | Similaridade (cosseno, valores iniciais) | Ação |
|---|---|---|
| Duplicata provável | ≥ 0,90 | **Não criar nó novo** — reforçar o existente (§10) |
| Relacionado | 0,60 – 0,90 | Faixa útil: variações e conexões. Par entra na fila de revisão do Curator |
| Distante | < 0,60 | Ignorar |

Os limiares dependem do modelo de embedding: ficam em configuração **por versão do modelo** e
são calibrados com uma amostra de pares rotulados pelo pesquisador. Ao trocar o modelo, as
arestas da versão antiga são recalculadas.

**Equilíbrio entre não perder oportunidades e não poluir o grafo:** **não há limite de
conexões** — nem por nó, nem por domínio. A proteção contra poluição não é cortar conexões, e
sim **só gravar no grafo o que foi confirmado**:

1. **Buscar não é gravar.** A busca semântica em tempo de consulta não tem limite e não
   grava nada.
2. **Fila de candidatos fora do grafo.** Todo par na faixa "relacionado" entra numa **fila de
   revisão** (tabela auxiliar no PostgreSQL, não no grafo), com a similaridade e os domínios
   envolvidos. Nada se perde: o par fica na fila até ser revisado.
3. **Só pares confirmados viram aresta.** O Curator revisa a fila e grava `SEMELHANTE_A`
   (`status: confirmada`) apenas quando há justificativa — podendo também originar uma
   `Descoberta` ou `Oportunidade`. O grafo contém somente conexões com significado.
4. **Ordem de revisão, não corte.** Como o Curator tem orçamento (ADR 012), a fila é revisada
   por prioridade: similaridade × evidência do nó (§9), com **prioridade extra para pares
   entre domínios diferentes**, que são os mais raros e os mais propensos a revelar
   oportunidades. O que não couber no orçamento de uma sessão continua na fila para a
   próxima.
5. **A faixa baixa (0,60 – 0,70) vale apenas entre domínios diferentes.** Dentro do mesmo
   domínio, a faixa "relacionado" começa em 0,70. Entre áreas diferentes, em que o
   vocabulário difere, uma similaridade de 0,60 já é um sinal relevante.
6. **Pares descartados** saem da fila e ficam registrados como avaliados, para não voltarem
   enquanto nenhum dos dois nós mudar (`hash_texto`).
7. **Calibração pelo uso.** O sistema acompanha a **taxa de confirmação** da fila. Se for
   muito baixa (ex.: < 10%), a faixa está frouxa demais e o limite inferior sobe; se for
   muito alta (ex.: > 60%), provavelmente há oportunidades sendo perdidas e o limite desce.

### 7. Regras de evidência

- `FUNCIONOU_PARA` e `FALHOU_PARA` exigem ao menos um `Resultado` com validação do Validator.
- Resultados `divergente_documentado` entram como evidência fraca, nunca forte.
- Resultados só são comparados numericamente **dentro do mesmo `Problema` e da mesma
  `Metrica` canônica**. Entre problemas diferentes, compara-se o ganho relativo ao baseline,
  não o valor bruto.
- Nada é apagado: descobertas superadas recebem `status: substituida` e a aresta `SUBSTITUI`.
- O pesquisador responsável pode contestar ou corrigir qualquer nó (§11); a correção é
  registrada como novo nó ou mudança de status, preservando o histórico.

### 8. Vocabulário controlado (domínios e métricas)

- **Domínios:** o vocabulário inicial é a **Tabela de Áreas do Conhecimento do CNPq**, como
  **ponto de partida, não restrição**. Termos novos podem ser criados pelo processo abaixo
  sempre que a tabela não cobrir uma área (ex.: áreas emergentes ou interdisciplinares). Um
  mapeamento opcional para a classificação da OCDE pode ser acrescentado na federação, para
  nós de outros países.
- **Métricas:** catálogo inicial com as métricas mais comuns (erro, acurácia, F1, R²,
  rendimento etc.), com sinônimos e sentido.
- **Processo intermediário** para termos novos:
  1. O Curator busca o termo no catálogo (nome, sinônimos e similaridade semântica).
  2. Se encontrar, usa o termo canônico e, se for o caso, acrescenta o sinônimo.
  3. Se não encontrar, cria o termo com `status: candidato` e o apresenta ao pesquisador.
  4. O pesquisador aprova, rejeita ou mapeia para um termo existente. Enquanto candidato, o
     termo pode ser usado, mas fica sinalizado.

### 9. Confiança

Modelo Beta-Bernoulli: a evidência positiva e a negativa são acumuladas separadamente,
ponderadas pela qualidade e pela independência de cada evidência. Isso separa **para onde a
evidência aponta** (`suporte`) de **quanta evidência existe** (`certeza`).

#### 9.1 Princípio: nenhum peso é subjetivo

Cada atributo vira número por uma **tabela fixa ou uma conta**, a partir de dados que já
existem nos artefatos e no grafo. Nenhum peso é atribuído pelo LLM. A única escolha humana é
o `delta_min` (menor efeito relevante), definido pelo pesquisador **antes** dos experimentos,
no `criterio_sucesso` do `Problema` — o que evita ajustar o critério depois de ver o resultado.

#### 9.2 Direção de cada evidência (`o`)

Para uma hipótese do tipo "a abordagem melhora a métrica", com `Δ` = diferença para o
baseline no sentido favorável da métrica (`sentido` do catálogo) e `δ` = `delta_min`:

| Situação | `o` |
|---|---|
| `Δ ≥ δ` — atingiu o efeito relevante | +1 (sustenta) |
| `Δ < δ` — não atingiu (inclusive piorou) | −1 (refuta) |
| Sem baseline: usa o alvo do `criterio_sucesso` | +1 se atingiu o alvo, −1 se não |
| Não chegou a um resultado | depende da causa — ver §9.3 |

#### 9.3 Tentativas sem resultado (inconclusivas)

Uma tentativa sem resultado pode significar coisas muito diferentes. A proposta é classificar
pela **causa**, que o orquestrador identifica objetivamente (códigos de saída, erros
registrados, estado da sessão):

| Causa | Exemplos | Como entra na conta |
|---|---|---|
| **Infraestrutura** | Queda de energia, falha de equipamento, perda de conexão, sessão interrompida por limite de uso | **Não afeta o veredito** — não diz nada sobre a hipótese. Conta em `n_tentativas` e fica visível ao lado da confiança |
| **Falha da própria abordagem, reproduzida** (≥ 2 tentativas independentes com o mesmo erro) | Não converge, estouro de memória, instabilidade numérica | **Evidência negativa**, com `q = 0,3` (como divergente) e `m = 1`. É um resultado real: "não funciona nestas condições" — a condição (ex.: memória disponível) é registrada |
| **Ambígua** | Executou até o fim, mas sem métrica utilizável, ou o Validator não conseguiu decidir | **Reduz a confiança** pelo fator de conclusão abaixo: muitas tentativas ambíguas sugerem problema no desenho do experimento |

**Fator de conclusão:** `f = 1 − λ · (n_ambiguas / n_tentativas_validas)`, com `λ = 0,5` e
`n_tentativas_validas` = todas as tentativas, exceto as de infraestrutura. Ex.: 6 tentativas
conclusivas e 2 ambíguas → `f = 1 − 0,5 · 2/8 = 0,875`.

Assim, toda tentativa fica registrada (é um esforço de pesquisa), mas só pesa no veredito na
medida em que informa algo sobre a hipótese.

#### 9.4 Tabelas de pesos

**`q` — qualidade da validação** (vem do status do Validator e da existência dos arquivos do
contrato de reprodutibilidade, Spec G2):

| Condição objetiva | `q` |
|---|---|
| Validado pelo Validator **e** contrato completo (`params.json`, semente e `metrics.json` presentes) | 1,0 |
| Validado, mas contrato incompleto (ex.: semente não registrada) | 0,7 |
| `divergente_documentado` | 0,3 |
| Falha de execução | 0 (não é evidência) |

**`m` — magnitude do efeito** (conta sobre o `metrics.json`):

| Direção | Fórmula | Leitura |
|---|---|---|
| Positiva | `m = min(1, Δ / (2δ))` | Atingir exatamente `δ` vale 0,5; o dobro de `δ` ou mais vale 1,0 |
| Negativa | `m = min(1, (δ − Δ) / δ)` | Ficar logo abaixo de `δ` vale perto de 0 (quase empate); não melhorar nada (`Δ ≤ 0`) vale 1,0 |
| Sem baseline | `m = 0,5` | Valor fixo |

**`d` — independência** (vem do grafo: nó, sessão, semente e dataset de cada experimento):

| A evidência vem de… | `d` |
|---|---|
| Um nó (computador) ou dataset ainda não usado para esta hipótese | 1,0 |
| Uma nova sessão num nó já usado | 0,5 |
| Uma nova semente numa sessão já usada | 0,2 |

**`b` — penalidade de busca** (só para evidências positivas cuja configuração ainda **não foi
replicada** em outra sessão ou nó; depois de replicada, `b = 1`):

`b = 1 / (1 + 0,5 · ln(n_config))`, com `n_config` = número de configurações tentadas para a
hipótese (contado pelas arestas `APLICOU`).

| `n_config` | 1 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|
| `b` | 1,00 | 0,74 | 0,55 | 0,46 | 0,40 |

#### 9.5 Equação: veredito de −1 a +1

Um único número, o **veredito**, resume a evidência: **positivo = funciona, negativo = não
funciona, perto de zero = não se sabe**. Quanto mais longe de zero, mais confiável.

```
w = q · m · d · b                         peso de cada evidência

α = 1 + Σ w  das evidências positivas
β = 1 + Σ w  das evidências negativas     (o "1 + " é o ponto de partida neutro)

suporte  = α / (α + β)                    0,5 = equilíbrio
certeza  = (α + β − 2) / (α + β)          0 = nenhuma evidência; → 1 com muita evidência

veredito = certeza · (2 · suporte − 1) · f          f = fator de conclusão (§9.3)
         = f · (α + β − 2)(α − β) / (α + β)²

confianca = |veredito|
```

| Veredito | Leitura |
|---|---|
| +0,5 a +1 | Funciona — evidência **forte** |
| +0,3 a +0,5 | Funciona — evidência **moderada** |
| +0,1 a +0,3 | Funciona — evidência **fraca** |
| −0,1 a +0,1 | **Insuficiente** — não há evidência para concluir |
| −0,3 a −0,1 | Não funciona — evidência **fraca** |
| −0,5 a −0,3 | Não funciona — evidência **moderada** |
| −1 a −0,5 | Não funciona — evidência **forte** |

A `Hipotese` guarda `suporte`, `certeza` e `veredito`. A `Descoberta` herda o `veredito`, e
o tipo segue o sinal: `funciona` (> 0,1), `nao_funciona` (< −0,1); na faixa insuficiente, não
se registra descoberta de "funciona" ou "não funciona".

A escala é propositalmente exigente: com evidências perfeitas e independentes, o veredito
é `(n / (n + 2))²` — 1 evidência dá 0,11, 3 dão 0,36, **5 dão 0,51 (forte)**. Ou seja,
evidência forte exige cerca de cinco réplicas independentes, como se espera na ciência.

#### 9.6 Exemplo completo

**Problema:** prever o rendimento de uma síntese química. **Métrica:** R² (maior é melhor).
**Baseline:** regressão linear, R² = 0,70. **`δ` definido pelo pesquisador:** 0,05.
**Hipótese H:** "gradient boosting melhora a previsão em pelo menos 0,05 de R²".
Na sessão 1 foram tentadas 4 configurações; a melhor foi replicada depois.

| Evidência | Origem | R² | Δ | `o` | `q` | `m` | `d` | `b` | `w` |
|---|---|---|---|---|---|---|---|---|---|
| E1 | Nó A, sessão 1, semente 1 | 0,80 | 0,10 | +1 | 1,0 | 1,0 | 1,0 | 1,0¹ | **1,000** |
| E2 | Nó A, sessão 1, semente 2 | 0,78 | 0,08 | +1 | 1,0 | 0,8 | 0,2 | 1,0¹ | **0,160** |
| E3 | Nó A, sessão 2 (semente não registrada) | 0,79 | 0,09 | +1 | 0,7 | 0,9 | 0,5 | 1,0 | **0,315** |
| E4 | Nó B, sessão 1 | 0,76 | 0,06 | +1 | 1,0 | 0,6 | 1,0 | 1,0 | **0,600** |
| E5 | Nó B, outro dataset | 0,71 | 0,01 | −1 | 1,0 | 0,8 | 1,0 | — | **0,800** |
| E6 | Nó A, sessão 3, `divergente_documentado` | 0,82 | 0,12 | +1 | 0,3 | 1,0 | 0,5 | 1,0 | **0,150** |

¹ A configuração de E1/E2 foi replicada em E3 e E4, então `b = 1`. Antes da réplica, seria
`b = 1 / (1 + 0,5 · ln 4) = 0,59`.

```
α = 1 + (1,000 + 0,160 + 0,315 + 0,600 + 0,150) = 3,225
β = 1 + 0,800                                    = 1,800

suporte   = 3,225 / 5,025                  = 0,64
certeza   = (5,025 − 2) / 5,025            = 0,60
veredito  = 0,60 × (2 × 0,64 − 1) × 1,0    = +0,17   (funciona — evidência fraca)
```

(Sem tentativas ambíguas, `f = 1`.)

**Comparação — só E1, antes de qualquer réplica** (`b = 0,59`, `w = 0,59`):
`α = 1,59`, `β = 1` → **veredito +0,05 (insuficiente)**.

**Leitura para o Curator:** as réplicas levaram a hipótese de "insuficiente" para "funciona",
mas o negativo de E5 a segura em "fraca" — e ele está concentrado em outro dataset. Em vez de
manter uma única descoberta com veredito fraco, o Curator deve dividi-la em descobertas
`condicionais`. Só no dataset 1 (E1–E4 e E6): `α = 3,225`, `β = 1` → **+0,28**; no dataset 2
(E5): **−0,08**, ainda insuficiente — vale sugerir novas tentativas nesse dataset. A fórmula
mede a evidência; o Curator interpreta as condições.

#### 9.7 Referência rápida (evidências com `q = m = 1`, sem ambíguas)

| Cenário | α | β | suporte | certeza | veredito |
|---|---|---|---|---|---|
| 1 positivo, 1 sessão | 2,0 | 1 | 0,67 | 0,33 | +0,11 (fraca) |
| 5 sementes positivas na mesma sessão | 2,8 | 1 | 0,74 | 0,47 | +0,22 (fraca) |
| 3 nós diferentes, todos positivos | 4,0 | 1 | 0,80 | 0,60 | +0,36 (moderada) |
| 5 nós ou datasets diferentes, todos positivos | 6,0 | 1 | 0,86 | 0,71 | +0,51 (forte) |
| 6 positivos e 1 negativo, independentes | 7,0 | 2 | 0,78 | 0,78 | +0,43 (moderada) |
| 4 negativos independentes | 1,0 | 5 | 0,17 | 0,67 | **−0,44 (não funciona, moderada)** |
| 1 positivo entre 20 configurações, sem réplica | 1,4 | 1 | 0,58 | 0,17 | +0,03 (insuficiente) |

#### 9.8 Parâmetros calibráveis

Todos os valores ficam em configuração, num só lugar:

| Parâmetro | Valor inicial |
|---|---|
| `q` validado + contrato completo / incompleto / divergente | 1,0 / 0,7 / 0,3 |
| `d` nó ou dataset novo / nova sessão / nova semente | 1,0 / 0,5 / 0,2 |
| `γ` (penalidade de busca) | 0,5 |
| `λ` (peso das tentativas ambíguas no fator de conclusão) | 0,5 |
| Falha da abordagem reproduzida: `q` / mínimo de repetições | 0,3 / 2 |
| Ponto de partida neutro de `α` e `β` | 1 |
| Faixas de leitura do veredito | 0,1 / 0,3 / 0,5 |

A discussão desta seção está na questão 4 abaixo.

### 10. Diretrizes do Curator para criação de nós

Estas diretrizes devem constar no prompt e nas ferramentas do Curator (ADR 012). O objetivo é
um grafo **enxuto e significativo**: poucos nós, cada um com um motivo claro para existir.

**Antes de criar qualquer nó, o Curator revisa minuciosamente o que já existe:**

1. **Busca semântica** no Qdrant por nós do mesmo tipo (top-k, filtrando por status ativo).
2. **Busca estrutural** no grafo: nome canônico, sinônimos no vocabulário, e — para
   `Descoberta` — descobertas existentes sobre o mesmo par `Abordagem`–`Problema`.
3. **Classificação do candidato** pelas faixas do §6:
   - **Duplicata:** não cria. Reforça o nó existente: adiciona a nova evidência
     (`BASEADA_EM`), atualiza `n_evidencias` e confiança, amplia `condicoes` se for o caso.
   - **Relacionado:** só cria se conseguir **enunciar explicitamente o que é diferente**
     (outra condição, outro domínio, outra configuração, resultado oposto). Liga ao existente
     por `VARIANTE_DE`, `SEMELHANTE_A` ou `CONTRADIZ`.
   - **Novo:** cria.
   - **Na dúvida entre duplicata e variação, não cria:** liga ao existente e sinaliza para
     revisão.

**Teste de significado — um nó só é criado se:**

- **aponta um novo caminho de pesquisa** (uma oportunidade, uma variação ainda não testada,
  uma transferência entre problemas ou domínios); **ou**
- **documenta um caminho explorado**, com resultado positivo, negativo, ou **sem conclusão**
  (interrompido por limite de uso, abandonado, bloqueado). Caminhos sem fim são registrados
  como `Descoberta` do tipo `caminho_sem_conclusao`, com ponto de parada, motivo e próximo
  passo sugerido — para que ninguém os repita às cegas e para que possam ser retomados.

**Não criar nós para:** a mesma descoberta com outras palavras; fatos triviais (ex.: "a
biblioteca foi importada"); repetições por semente (são evidências de um nó existente, não
nós novos); logs intermediários; especulação sem evidência.

**Preferências e registro:**

- **Atualizar antes de criar:** reforçar, mudar status, acrescentar condições.
- **Consolidar em lote:** as sinalizações de outros agentes são revisadas juntas, ao fim de
  um experimento ou num checkpoint da sessão — não uma a uma.
- **Usar o vocabulário controlado** para domínios e métricas (§8).
- **Justificar:** todo nó criado registra `justificativa_criacao` e `nos_consultados`,
  permitindo auditar a decisão de criar.

### 11. Acesso do pesquisador ao grafo

- A visualização completa será feita futuramente por um serviço de frontend (a discutir).
- **Visualizar é um comando simples da CLI, sem agente e sem LLM** (sem custo de tokens):
  imprime o grafo do projeto em que o pesquisador atua — nós, tipos, propriedades e relações —
  com filtros por tipo de nó, domínio e status. O comando usa consultas fixas, somente-leitura.
- **Alterar é sempre com o Curator:** pedir mudanças em nós, arestas e propriedades, ou
  adicionar nós e arestas manualmente, passa pelo agente responsável pelo grafo.
- O pesquisador **não tem acesso direto ao banco**. O Curator traduz o pedido, mostra ao
  pesquisador a alteração proposta e só a aplica após confirmação. A autoria fica registrada
  como `pesquisador`.
- **Proteção do banco** (coerente com o ADR 014 — nada gerado por LLM executa sem controle):
  o Curator **não executa Cypher de escrita livre**. Escritas passam por ferramentas tipadas
  do projeto (criar nó, criar aresta, mudar status) que validam o modelo de dados; consultas
  livres geradas pelo LLM rodam apenas com um usuário de banco somente-leitura.

---

## Discussão com o pesquisador responsável

As respostas do pesquisador estão preservadas como escritas. Cada questão traz a resposta do
arquiteto e o status.

### 1. Granularidade do `Problema` — **decidido**

> O problema deve ser estruturado em alto nível, com uma descrição abrangente do que se pretende resolver é um ponto de partida a ser explorado, como um resumo de um artigo que ainda não tem os resultados.

**Arquiteto:** incorporado (§2, §4: `titulo` + `resumo`). Consequência: a especificidade fica
na `Hipotese` e nas `condicoes` da `Descoberta` — "o que funcionou para X" será respondido
navegando `Problema → Hipotese → Experimento`, não pelo `Problema` sozinho. Isso favorece a
transferência entre áreas, já que resumos em alto nível se aproximam melhor por embedding.
**Ponto a acompanhar:** se problemas amplos acumularem hipóteses demais, pode ser necessário
um nível intermediário (`SUBPROBLEMA_DE`). Proposta de autoria: o Researcher redige o
`Problema` a partir dos insumos e o pesquisador aprova (no modo `assisted`, obrigatoriamente).

> Who writes the problem statement: Keep the Researcher agent for the draft and confirmation by the user.

**Arquiteto:** incorporado (§2): o Researcher redige, o pesquisador confirma — em qualquer
modo de sessão.

### 2. Domínios — **decidido**

> Vocabulário controlado para facilitar buscas no futuro. Será importante ter um processo intermediário para definir qual palavra usar na definição do domínio do projeto/nó do grafo.

**Arquiteto:** incorporado (§8). Proponho três pontos: (a) `Dominio` como **nó**, não
propriedade, para que a travessia entre áreas (química ↔ história) seja uma consulta de grafo;
(b) partir de uma taxonomia reconhecida (OCDE, com mapeamento para o CNPq) em vez de criar
uma; (c) o processo intermediário do §8 — termo candidato proposto pelo Curator e aprovado pelo
pesquisador.

> Looks good to me to start from the CNPq's taxonomy, it's a good strtegy, but don't be limited to it. It should be a start point, not cosntraint

**Arquiteto:** incorporado (§4, §8): a tabela do CNPq é o vocabulário inicial; termos fora
dela entram pelo processo de candidato → aprovação, com `codigo_cnpq` vazio. O mapeamento
para a OCDE fica como opção para a federação.

### 3. Métricas comparáveis — **decidido**

> Sim. É importante identificar as métricas semlehantes até para uniformizar nomes e técnicas no futuro.

**Arquiteto:** incorporado (`Metrica` como nó, aresta `MEDE`, mesmo processo de aprovação do
§8). Ressalva importante (§7): mesmo com nomes uniformizados, valores só são comparáveis dentro
do mesmo problema; entre problemas, compara-se o ganho sobre o baseline. Métricas da mesma
família (ex.: RMSE e MAE) ficam ligadas por `RELACIONADA_A`, mas não são intercambiáveis.

### 4. Fórmula de confiança — **decidido**

> Vamos pensar juntos nesse e criar uma equação. Uma hipótese pode demandar muitos experimentos e o seu peso deve estar atrelado a um resultado, se o experimento levou a um resultado positivo, o peso deve ser maior, se levou a um resultado negativo, o peso deve ser menor. A mesma ideia para número de sessões, sementes e nós, pois uma hipótese que explorou muitos caminhos e obteve resultado positivo deve ter um peso maior do que uma hipótese que explorou poucos caminhos e obteve resultado positivo. Reflita sobre essa estratégia, julgue pontos positivos e negativos, aponte alternativas e ajude a formular uma equação para medir a confiança.

**Arquiteto — pontos positivos da estratégia:**

- É intuitiva e explicável: resultados positivos aumentam a confiança, negativos a reduzem.
- Valoriza a **replicação** em sessões, sementes e nós diferentes — o núcleo do método
  científico e da validação por reprodução prevista na federação (ADR 013).

**Pontos de atenção:**

1. **Confiança não é o mesmo que resultado positivo.** Se um resultado negativo simplesmente
   reduz o peso, uma hipótese refutada por dez experimentos independentes fica parecida com uma
   hipótese nunca testada — mas a primeira é conhecimento sólido ("X não funciona para Y"), e
   resultados negativos são de primeira classe (ADR 009). Por isso a proposta separa `suporte`
   (direção) de `certeza` (quantidade de evidência).
2. **Explorar muitos caminhos pode enfraquecer a evidência, não fortalecer.** Se foram
   tentadas 20 configurações e uma deu certo, esse acerto pode ser sorte (problema das
   comparações múltiplas). É preciso distinguir **replicação** (a mesma hipótese e
   configuração repetidas em condições independentes — fortalece) de **busca** (muitas
   variações até uma funcionar — exige réplica antes de valer por inteiro). Daí o fator `b_e`.
3. **Nem toda repetição é independente.** Dez sementes na mesma sessão e no mesmo computador
   não equivalem a dez laboratórios. Daí os pesos decrescentes de `d_e`: nó ou dataset
   diferente > sessão diferente > semente diferente.
4. **Tamanho do efeito importa.** Superar o baseline por 0,1% não deve pesar como superá-lo
   por 20%. Daí `m_e`, ligado ao `delta_min` do `Problema`.

**Alternativas avaliadas:**

- **Razão ponderada simples** (positivos ÷ total): fácil, mas não informa quanta evidência
  existe — 1 de 1 e 100 de 100 dão o mesmo valor.
- **Beta-Bernoulli (proposta do §9):** simples, explicável, separa direção de quantidade e
  acomoda pesos. Recomendada para começar.
- **Meta-análise por tamanho de efeito** (efeitos aleatórios, ponderação pela variância):
  mais rigorosa, mas exige variância em cada resultado e métricas padronizadas. Boa evolução
  futura, quando o catálogo de métricas estiver maduro.
- **Fatores de Bayes / valores-p:** exigem teste estatístico formal em cada experimento; nem
  toda ferramenta de pesquisa produz isso.

> I like your approach, but I still struggle to see an equantion coming out from it. For example, how do we give a number to "how well it was validated", this can be a bit subjective no not quantitative. My idea is to distribute values to those attribute, which will help to calculate the confidence. Help me with examples set weights to demostrate how yout proposal should work.

**Arquiteto:** concordo — cada atributo precisa de uma regra objetiva. O §9 foi reescrito:
cada peso agora sai de uma **tabela fixa** (`q`, `d`) ou de uma **conta** sobre dados em disco
(`m`, `b`), sem julgamento do LLM. "Quão bem foi validado" virou uma verificação de fatos:
o status do Validator e a presença dos arquivos do contrato de reprodutibilidade. O §9.6 traz
um exemplo completo, com seis evidências, passo a passo.

**Para o pesquisador avaliar:** os valores iniciais (ex.: divergente = 0,3); se inconclusivos
contam; se dataset diferente vale o mesmo que nó diferente; se atingir exatamente `δ` vale 0,5.

> Confidence: Now I understand your proposal, but the only point I would review is about confidence values < 0,5 being positive and above it being "not works". I would work on the equation to invert this logic. Besides, the weights from example looks good to me.
>
> 1. 0.3 is for for a divergent result
> 2. I tend to keep the inconclusive results in the calculation, we may don't know exactly why it was inconclusive o didn't reach a result, but at least it was a trial. Maybe an equipment failure during experiments, or the computer went out of energy. I'm really in doubt if we should keep it. Let's break this down.
> 3. Yes, new dataset weigh the same as new computer. Usable datasets are difficult to find, so it should receive good score if a research is able to test on differents dataset.
> 4. Yes, keep 0.5 as the weight for a result that just reaches δ. Better results should receive better score, and lower results should receive penalties. or lower score.

**Arquiteto:**

- **Escala invertida para um veredito de −1 a +1** (§9.5): positivo = funciona, negativo =
  não funciona, perto de zero = insuficiente; a confiança é a distância de zero. Some a
  leitura confusa em que um número baixo significava "funciona". A escala ficou mais exigente:
  evidência forte (≥ 0,5) pede cerca de cinco réplicas independentes.
- **Pesos confirmados:** divergente = 0,3; dataset novo = nó novo = 1,0; atingir `δ` = 0,5,
  com mais pontos para resultados melhores e penalidade crescente para os abaixo de `δ` (§9.4).
- **Inconclusivos — proposta de decomposição (§9.3), em discussão.** Concordo que toda
  tentativa deve ficar registrada, mas contá-la como evidência a favor ou contra distorceria o
  veredito quando a causa é externa. A proposta separa por causa: (a) **infraestrutura**
  (energia, equipamento, conexão) — registrada em `n_tentativas`, sem afetar o veredito;
  (b) **falha da própria abordagem, reproduzida** — conta como evidência negativa fraca
  (`q = 0,3`), porque "não converge nestas condições" é um resultado; (c) **ambígua** — reduz a
  confiança pelo fator de conclusão `f`, porque muitas tentativas ambíguas indicam problema
  no desenho do experimento. **A decidir:** se essa divisão atende e os valores `λ = 0,5` e
  "2 repetições" para considerar uma falha reproduzida.

> Yes, I agree with the inconclusive-results approach and values

**Arquiteto:** decomposição por causa e valores (`λ = 0,5`, 2 repetições) confirmados (§9.3).

### 5. Limiares de similaridade — **decidido**

> Projetos, Abordagens, Problema, Descobertas e Oportunidades. Aqui a ideia é ajudar a não criar repetições dentro do grafo e evitar poluir com muitas soluções semelhantes, mas sim explorar variações e conectar ideias diferentes que podem levar a novos caminhos e resultados.

**Arquiteto:** incorporado (§6). Interpretei a lista como pares do mesmo tipo e acrescentei
`Descoberta↔Problema` entre projetos, que é o par que revela oportunidades entre áreas — **a
confirmar**. O objetivo descrito virou as três faixas: acima de 0,90 é repetição (não cria),
entre 0,70 e 0,90 é a zona de variações e conexões, abaixo é ruído. Os valores são iniciais e
dependem do modelo de embedding; proponho calibrá-los com uma amostra de pares rotulados pelo
pesquisador.

> Similarity I would only adjust the lower boundry from 0.70 to 0.60 simlarity score, to not miss opportunities. Also, it should not limit to 5 similarity links, we can have similarity in differents domains. Again, we need to find a common ground to not miss opportunities, but we also should avoid creating to much edges and nodes to not polute the database.

**Arquiteto:** limite inferior ajustado para 0,60 e limite de 5 arestas por nó removido (§6).
Como meio-termo, proponho cinco mecanismos (§6): busca em tempo de consulta sem limite e sem
gravação; cota de 3 arestas **por nó e por domínio** (não por nó); faixa 0,60–0,70 aplicada a
conexões entre domínios ou projetos diferentes; arestas descartadas removidas, com o par
registrado para não ser reavaliado; e ajuste dos limiares pela taxa de confirmação das
candidatas. **A confirmar:** a cota por domínio e a regra da faixa baixa.

> Similarity: All your suggestions make sense, the only point a miss here is why to set a limit per domain? Why should we keep limiting connections? Can't we miss opportunities here? I mean, if we have math domain connected to, computer science, enginerring and chemistry, for example, it can't connect to biologyor physics? Besides, the 0.60–0.70 values change applies only across domains
>
> Cross-project links: Yes, connect a discovery in one project to a problem in another project as intended if they reach good levels of confidence and similarity.

**Arquiteto:** esclarecendo: a cota era de 3 arestas **para cada** domínio — matemática poderia
se conectar a biologia e física também —, mas o ponto é válido: qualquer corte pode perder
oportunidades. **A cota foi removida** (§6). A proteção contra poluição passa a ser outra: os
pares candidatos ficam numa **fila fora do grafo** e só viram aresta quando o Curator os
confirma. Nada se perde (o que não for revisado numa sessão fica para a próxima), e o grafo só
guarda conexões com significado. Pares entre domínios diferentes têm prioridade na fila. A
faixa 0,60–0,70 vale só entre domínios diferentes, como indicado. O par
`Descoberta↔Problema` entre projetos está confirmado, com a condição de evidência ao menos
moderada (`|veredito| ≥ 0,3`) e similaridade na faixa "relacionado".

### 6. Configuração — **decidido**

> Nesse caso me parece que se torna uma nova abordagem, pois já foi aplicada um certo número de vezes em projetos diferentes, principalmente se gerar um resultado positivo.

**Arquiteto:** incorporado (§5, `tipo: configuracao`, ligada por `VARIANTE_DE`). Dois
detalhes: a comparação precisa usar a configuração **normalizada** (só hiperparâmetros do
método), e o critério de promoção precisa de números.

> a new configuration should be created after validated in at least 2 projects and at least 3 positive results.

**Arquiteto:** incorporado (§5): **≥ 2 projetos e ≥ 3 resultados positivos validados**.

### 7. Correções humanas — **decidido**

> O pesquisador deverá ter um meio de visualizar o grafo para o projeto em que está atuando. Isso será discutido futuramente em um serviço de frontend a ser desenvolvido. Por enquanto, o pesquisador poderá solicitar o grafo via CLI, o que permitirá visualizar as conexões, tipos, propriedades, relacionamentos e solicitar alterações nesses campos ou até mesmo adicionar nós e arestas manualmente. Porém não terá acesso direto, sempre deverá ter ajuda do agente responsável por atuar no grafo para criar queries.

**Arquiteto:** incorporado (§11). Acrescentei duas salvaguardas: o Curator mostra a alteração
proposta antes de aplicar, e escritas passam por ferramentas tipadas (nunca Cypher livre),
com consultas livres em usuário somente-leitura. Sugeri que a visualização fosse um comando
fixo, sem LLM, reservando o Curator para alterações.

> I like your suggestion of use a simple command to see/print the graph in the CLI. We must go that way and use the agent only to do changes on the graph.

**Arquiteto:** incorporado (§11): visualizar é um comando fixo e somente-leitura; alterar é
sempre com o Curator.

---

## Alternativas Consideradas

### Alternativa A: Relações como arestas simples, sem nós de afirmação

**Descartado porque:** uma aresta `FUNCIONOU_PARA` sozinha não carrega histórico, contestação
nem várias evidências de forma legível. Reificar como `Descoberta` mantém a auditabilidade.

### Alternativa B: Vetores armazenados no próprio grafo

**Descartado porque:** o AGE não tem busca vetorial eficiente; o Qdrant já está na stack e foi
feito para isso. A chave compartilhada evita duplicação.

### Alternativa C: Deixar o LLM escrever todos os nós

**Descartado porque:** fatos estruturais (experimentos, resultados) já existem em disco e
podem ser registrados deterministicamente — sem custo de tokens e sem risco de alucinação.

### Alternativa D: Domínios e métricas em texto livre

**Descartado** pelo pesquisador responsável: dificulta buscas futuras e a conexão entre áreas.

---

## Consequências

### Positivas

- As cinco perguntas do contexto têm um caminho de consulta claro.
- Toda afirmação é rastreável até um resultado medido.
- O modelo serve a qualquer ferramenta e já está preparado para a federação.
- Resultados negativos e caminhos sem conclusão são conhecimento com confiança própria.

### Negativas / Trade-offs

- **Treze tipos de nó** exigem disciplina: extração e deduplicação ruins degradam o grafo. As
  diretrizes do §10 são a principal mitigação.
- **Consistência AGE ↔ Qdrant** depende da rotina de reconciliação.
- **Fila de revisão de similaridade** é uma tabela nova no PostgreSQL — mudança de schema que,
  como o grafo, exige aprovação explícita na implementação (AGENTS.md).
- **Custo LLM do Curator** para revisar candidatos e arestas `SEMELHANTE_A`.
- **Manutenção do vocabulário** exige participação do pesquisador na aprovação de termos.
- **Calibração** de limiares e da fórmula de confiança só será possível com dados reais.

---

## Revisão

Este ADR deve ser revisado quando:
- O frontend de visualização do grafo for especificado.
- O primeiro protótipo mostrar que consultas reais precisam de outros tipos ou relações.
- Houver dados suficientes para calibrar limiares e pesos de confiança.
