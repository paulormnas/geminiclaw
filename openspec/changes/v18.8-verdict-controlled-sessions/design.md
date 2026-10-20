# Design: v18.8-verdict-controlled-sessions

## 1. Confronto com o código (2026-10-19)

| Ponto | Onde está hoje | O que esta mudança faz |
|---|---|---|
| Runner | `run_combination` (`scripts/benchmark/run_benchmark.py:475`) chama `seed_project(combo["name"])`, lê um único `task_file` por matriz e executa `main.py --mode auto --project P <tarefa>` uma vez por repetição | O orquestrador de exploração reaproveita `reset_stores`, `check_guards`, o arquivamento (`archive_repetition`, `project_graph_full`) e a coleta de custo; `seed_project` e o diretório de entrada ganham parâmetros opcionais |
| `Problema` semeado | `BENCHMARK_DRAFT` fixo (Iris, alvo 0,95, δ 0,01, `seed_project.py:25`) | Um `ProblemDraft` por regime, com `ao_atingir_objetivo = "continuar"` |
| Pontuador | `scoring.py` é do Iris (acurácia declarada, algoritmos citados) | Não é usado; a medição vem do grafo (veredito, hipóteses, tentativas) |
| Dados da tarefa | `INPUT_CONTEXT_DIR` global (`src/config.py:482`); marcações em `input_context/dados.yaml` (spec `research-data`) | Um diretório por exploração, passado no ambiente do subprocesso; o dataset sai marcado `compartilhavel` com motivo, para o Developer enxergá-lo |
| Fim da pesquisa | Em `semi` e `auto` o processo roda até um motivo de parada (V18.7); os limites de uso (`limite_tokens`, `limite_tempo`, `limite_custo`) fecham a sessão e a retomada é manual (`resume`) | O orquestrador retoma sozinho depois desses três (retomáveis sem perguntar, spec `session-continuity`) |
| Parada ao atingir o alvo | `ao_atingir_objetivo` padrão `parar` no `auto` (`solucao_encontrada` na primeira variação que atinge o alvo) | Os `Problema` sintéticos declaram `continuar`; é uma diferença consciente do uso real (§9, limitação 2) |
| Hipótese | Hipótese do sistema, chave (problema, abordagem canônica, métrica); variação = `config_hash` novo (`src/knowledge/system_hypotheses.py`, `service.py:_config_of`) | A unidade de leitura do veredito; a verdade é do problema (§6) |
| Falha de abordagem | `VERDICT_APPROACH_FAILURE_Q` = 0,3 e `..._MIN_REPEATS` = 2 (`src/config.py:780`) | Avaliada offline (§7); mudar o valor é decisão do pesquisador |
| Memória do sandbox | `CODE_SANDBOX_MEMORY_LIMIT` = `256m` (`src/config.py:561`) | Base do regime F (§2.2) |
| Laboratório | `scripts/verdict_lab/` (catálogo, simulação, `replay`, `selecao`) | Ganha o cenário N-abordagem-3, variantes de `approach_failure_q` e falhas de abordagem na simulação (§7) |

## 2. Regimes sintéticos

### 2.1 Gerador

`scripts/verdict_lab/controlled/generator.py`, só biblioteca padrão (`random.Random(semente)`, `math`): mesma semente, mesmo arquivo byte a byte, sem dependência nova. Saída: `dados.csv` (colunas `x1`…`x8` e `y` em {0,1}, 2000 linhas; 12000 no regime F) e um `dados.yaml` marcando `dados.csv` como `compartilhavel` com motivo "dado sintético gerado para calibração". Os atributos são `N(0,1)` independentes.

**Regimes P, T e F.** O rótulo vem de `s = Σ a_k · t_k(x) + ruído` com termos de força decrescente:

| Termo | Forma | Papel |
|---|---|---|
| `t0` | `0,6·x7 + 0,8·x8` | o que um modelo linear nos atributos brutos já acerta (patamar ≈ 0,62) |
| `t1` | `x1·x2` | interação dominante |
| `t2` | `(x3² − 1)/√2` | termo quadrático |
| `t3` | `x4·x5` | segunda interação |
| `t4` | `sin(2·x6)` normalizado | termo não polinomial |
| `t5` | `x7·x8` | interação entre os atributos do termo linear |

Todos têm variância 1. `y = 1` com probabilidade `Φ(s)`, `s = Σ a_k·t_k` (o ruído de desvio 1 está embutido nas forças `a_k`). As forças `a_k` foram calibradas **por mínimos quadrados no oráculo** (400 000 linhas, semente 12345) até o **teto de Bayes** `p_5` do regime e os **patamares** `p_k` = acurácia do preditor `sinal(Σ_{j≤k} a_j t_j)` (quem descobre os `k` primeiros termos, `k` de 0 a 5) ficarem nos valores abaixo; o oráculo da implementação (200 000 linhas, esperança sobre o rótulo) confere cada valor com tolerância de ±0,005 em um teste do gerador. O ruído e as amostras mudam a cada semente; os termos e as forças não. (Correção de 2026-10-19: a primeira versão listava cinco termos e cinco patamares, sem o termo `t5` que dá o teto de 0,96 depois do patamar de 0,93.)

**Regime N.** `y ~ Bernoulli(0,5)` independente dos atributos (teto = acaso = 0,50).

### 2.2 Regime F

Mesma construção de P (mesmas forças e patamares), com 12 000 linhas. Um método que guarda uma matriz `n × n` de ponto flutuante (núcleo denso, processo gaussiano, agrupamento espectral) precisa de cerca de 1,1 GB com `n = 12 000`, acima do limite de 256 MB do sandbox, e falha com `MemoryError` (causa `abordagem`, assinatura repetida em configurações distintas). Os demais métodos (árvores, regressão, vizinhos, redes pequenas) seguem como em P. **O tamanho exato é calibrado no piloto**: se a falha de abordagem não for reproduzível (o Developer contorna com amostragem, por exemplo, ou a falha vira `infraestrutura`/`ambigua`), o regime F sai e o N-abordagem-4 fica só com a avaliação offline (§7). Isso é registrado no relatório do piloto.

### 2.3 Valores propostos e aprovados (2026-10-19)

Classificação binária tabular, métrica acurácia (maior é melhor), `δ` = 0,01, baseline "classe majoritária", `ao_atingir_objetivo = continuar`, objetivo `limiar`.

| Regime | Teto | Alvo | Patamares `p_0 … p_4` | Verdade (resposta correta) |
|---|---|---|---|---|
| **P** efeito plantado | 0,96 | 0,93 | 0,62 · 0,74 · 0,82 · 0,88 · 0,93 · **0,96** (teto) | `funciona`: o alvo é alcançável por variações com evolução |
| **T** teto abaixo do alvo | 0,90 | 0,93 | 0,62 · 0,72 · 0,79 · 0,84 · 0,87 · **0,90** (teto) | nunca `funciona`: o alvo não é alcançável |
| **N** ruído puro | 0,50 | 0,55 | — | nunca `funciona`: só alcança o alvo por acaso |
| **F** falha plantada | 0,96 | 0,93 | como P | a abordagem de núcleo denso nunca `funciona`; as demais, como P |

O efeito `e` = 0,03 (cerca de três desvios da medida: com um teste de 400 a 600 linhas o desvio da acurácia é de cerca de um ponto). No regime N, ultrapassar 0,55 por sorte tem cerca de 1 % de chance por tentativa e cerca de 20 % em uma exploração de 20 variações; validar exige ainda cinco melhoras consecutivas acima do alvo.

Os valores podem mudar **antes** do piloto, por decisão do pesquisador; depois do piloto, só com registro da mudança e do motivo no relatório.

## 3. Tarefa, projeto e verdade

- **Tarefa neutra** (um arquivo por regime, mesmo texto exceto a descrição do dado): "Construa e avalie modelos de classificação para o conjunto de dados em `input_context/dados.csv` e recomende o melhor, com justificativa. Salve os artefatos em disco." Não induz variações, não cita termos, interações nem o alvo.
- **`Problema` do regime** (`ProblemDraft`): título e resumo neutros, classe `classificacao`, métrica `acurácia`, `alvo` e `delta_min` da tabela, `ao_atingir_objetivo = "continuar"`, baseline "classificador que prediz a classe majoritária". O vocabulário precisa ter a métrica aprovada (`seed_project` já exige).
- **`verdade.json`** (no diretório de saída da exploração, **fora** de `input_context/`, do diretório de saídas da sessão e do ambiente do subprocesso): regime, semente do dado, teto, alvo, patamares calibrados, `sha256` do `dados.csv`, resposta correta por regime e, no F, a assinatura esperada da falha. O orquestrador só o lê na medição.
- **Sementes:** a semente do dado de cada repetição vem de um `--semente` único (`random.Random`), registrada no manifesto; combinações diferentes recebem as **mesmas** sementes de dado, para comparar modelos sobre os mesmos conjuntos.

## 4. Orquestrador de exploração

### 4.1 Unidade

Uma **exploração** = (combinação, regime, repetição). Começa com `main.py --mode auto --background --project P <tarefa>` (ou o comando direto em primeiro plano, equivalente) e termina num **fim natural**, num fim por falha ou no **teto de gasto da exploração**. O identificador da primeira sessão (e o apelido) identifica o início; as sessões seguintes são ligadas por `continues_session_id`.

### 4.2 Laço

```
reset isolado (guardas do runner) → gerar dados → semear projeto → iniciar sessão
repetir:
    esperar o processo; ler motivo_parada e o custo acumulado da cadeia (banco)
    motivo ∈ {solucao_encontrada, sem_caminhos_promissores, saturacao}     → fim natural
    motivo ∈ {limite_tokens, limite_tempo, limite_custo, limite_cota_provedor}
         e custo da cadeia < teto da exploração
         e a sessão produziu ≥ 1 experimento novo                           → retomar (resume)
    custo da cadeia ≥ teto                                                  → interrompida_pelo_orcamento
    sessão sem experimento novo duas vezes seguidas                          → sem_progresso
    qualquer outro motivo (erro, planos_rejeitados, interrompida, ...)       → fim por falha
    número de sessões ≥ teto de sessões                                      → interrompida_pelo_orcamento
arquivar (grafo do projeto, eventos, sessões, custos) em <saida>/<combinação>/<regime>/r<r>/
```

`solucao_encontrada` e `saturacao` pedem confirmação do pesquisador na retomada manual; o orquestrador **não** retoma depois deles: são fins naturais. `limite_cota_provedor` é retomável, mas uma segunda ocorrência seguida sem progresso fecha a exploração como `sem_progresso` (evita laço contra um provedor sem cota).

### 4.3 Estados registrados (`exploracao.json`)

`fim`: `natural` | `falha` | `interrompida_pelo_orcamento` | `sem_progresso`; `motivo_final`; `censurada` (verdadeiro em todos os fins que não são `natural`); sessões da cadeia (id, apelido, motivo, custo, tokens, chamadas por papel, minutos); custo total e por provedor; número de experimentos, resultados e hipóteses; nome, versão e fonte dos modelos dos papéis (`model_versions`). Uma exploração que não termina em fim natural (orçamento, `sem_progresso` ou falha) é **censurada**: entra nas taxas como "sem conclusão" e nunca como validada nem refutada por inferência; o relatório conta quantas foram.

### 4.4 Reuso do runner

`run_combination` ganha os parâmetros opcionais `seeder` e `input_dir` (o `extra_env` já existia), com os valores atuais como padrão, e `seed_project` ganha `draft`; o Iris continua idêntico (teste de regressão). Como a exploração precisa de **um** reset, **uma** semeadura e **um** arquivamento para uma cadeia de sessões, o laço não chama `run_combination` por segmento: `explorer.py` guarda só a política de parada (testável sem processo), `runner.py` cria os processos (`main.py --mode auto --project P <tarefa>` e `main.py --mode auto --session <id> resume`) e reaproveita as guardas do reset, `build_env`, o encerramento do grupo de processos, `sum_tokens`/`db_token_usage`, `fetch_events` e `archive_repetition`. Os testes substituem o executor de processos, o leitor de custo e as contagens do grafo.

### 4.5 Segurança de execução

O reset de bancos vale só com `--reset-stores --confirm-target BANCO@HOST` (guardas da spec `benchmark`). O orquestrador recusa começar sem as duas flags quando `--executar` é passado, e roda em modo de ensaio (`--ensaio`, sem processo) por padrão. Nenhuma chave de API é lida ou impressa pelo orquestrador; o ambiente do subprocesso é o do runner (`build_env`).

## 5. Orçamento

### 5.1 Comando `orcamento`

`python -m scripts.verdict_lab.controlled orcamento --plano plano.json [--piloto resultados_piloto.json]` imprime, **sem chamar LLM nem abrir banco**, uma tabela por combinação e regime:

| Coluna | Origem |
|---|---|
| Explorações | `repeticoes[regime]` do plano |
| Teto por exploração (US$, sessões, minutos) | plano |
| Chamadas de LLM por exploração (média, p90), por papel | piloto; sem piloto, "sem dados" |
| Tokens por exploração (média, p90) | piloto |
| US$ por exploração (média, p90) | piloto |
| **Gasto esperado** = explorações × média | piloto |
| **Gasto máximo** = explorações × teto | plano (vale mesmo sem piloto) |

Mais a linha de total por combinação e geral. O gasto máximo é garantido pelo orquestrador (o teto por exploração é imposto pelo laço, §4.2, além do `SESSION_MAX_COST_USD` de cada sessão).

### 5.2 Plano do piloto (proposta, a aprovar antes de rodar)

Oito explorações: regimes P, T, N, F × combinações `haiku-dev-sol-juiz` e `sonnet-dev-sol-juiz`, uma repetição cada. Propostas: `SESSION_MAX_COST_USD` = 3,0 por sessão, no máximo 6 sessões por exploração, **teto por exploração** US$ 4 (haiku) e US$ 10 (sonnet), 12 horas de relógio por exploração. Gasto máximo do piloto: 4 × (4 + 10) = **US$ 56**. Referência de custo por sessão: a bateria V18.7 parcial (14 min; haiku US$ 0,27 com falha precoce; sonnet US$ 2,10 chegando ao alvo). Uma sessão que acumula cinco variações com evolução custa mais que isso, e o piloto existe para medir quanto.

### 5.3 Plano da bateria (proposta; números finais saem do piloto)

Repetições por combinação: P 10, T 15, N 15, F 5 (45 explorações por combinação, 90 no total). Com 0 erros em `n` explorações, o limite superior de 95 % da taxa de falsa validação é de cerca de 3/n: 20 % com `n` = 15. A bateria **não prova** o teto de 2 % (seriam necessárias cerca de 150 explorações nulas por combinação); ela confirma, com dados novos, se a taxa observada é compatível com a previsão do laboratório (§6.3). Os tetos e as repetições finais são aprovados pelo pesquisador com a tabela `orcamento` preenchida pelo piloto.

## 6. Medição

### 6.1 Coleta

`medir` lê, de cada diretório de exploração arquivado, o `grafo_projeto.json` (já com `Metrica` e `MEDE`, `v18.8-verdict-lab`), o `exploracao.json` e o `verdade.json`. Reaplica `replay` (o mesmo `KnowledgeService.collect_attempts` do sistema) para obter as tentativas por hipótese e o veredito gravado (`modelo_veredito`).

### 6.2 Medidas (ADR 025 §4.1)

A unidade da taxa é a **exploração** (a hipótese também é contada, como detalhe). O estado de uma hipótese ao fim vem do grafo: `validada` (veredito ≥ 0,3), `refutada` (≤ −0,3) ou `em_teste` (indecisa).

| Medida | Definição |
|---|---|
| **Poder** (P, F-restante) | explorações P com pelo menos uma hipótese `validada` / explorações P não censuradas |
| **Falsa validação** (T, N, F na abordagem plantada) | explorações com pelo menos uma hipótese `validada` / explorações não censuradas; a maior entre T e N é a que se compara ao teto |
| **Falsa refutação** | em P, explorações com hipótese `refutada` em que **nenhuma** hipótese foi validada (refutação discordante: pode ser abordagem ruim, não erro certo); relatada como discordância, conforme decisão do pesquisador |
| **Indecisão** | explorações sem hipótese validada nem refutada |
| **Hipóteses** | contagem de hipóteses validadas/refutadas/indecisas por regime |
| **Variações com evolução** | por hipótese: variações úteis (modelo v2) e total de variações; distribuição por combinação (mediana, p10, p90) |
| **Tentativas até cruzar 0,3** | por hipótese validada |
| **Custo por validação útil** | (US$ e chamadas de LLM de todas as explorações P) / (explorações P com hipótese validada) |
| **Censura** | explorações interrompidas pelo orçamento ou por falha, por regime |

Intervalos de 95 %: Wilson para taxas, Clopper-Pearson para 0 ou `n` sucessos (`math`, sem dependência nova). O relatório sempre traz `k/n` junto da taxa.

### 6.3 Comparação com a previsão do laboratório

1. **Equivalência (reaplicação).** O veredito que o sistema calcula com as tentativas arquivadas coincide com `lab_verdict` da variante `completa2` (diferença ≤ 1e-12) e com o veredito gravado no grafo dentro do arredondamento de seis casas do sistema (≤ 1e-6); divergência é defeito, não resultado e encerra o comando. A variante `atual` (equação do ADR 015) é calculada ao lado, para mostrar o que o modelo anterior teria concluído com os mesmos dados.
2. **Previsão.** Dos dados das explorações P e N se estimam os parâmetros da simulação (desvio do resultado `sigma` entre repetições da mesma configuração, dispersão `tau` entre configurações, probabilidade de variar e de falhar por passo, número de tentativas por hipótese) e a simulação do laboratório roda com **esses** parâmetros e os efeitos dos regimes (`+e`, `−e`, 0), com a semente fixa. A tabela compara, por regime, a taxa prevista (e seu intervalo) com a observada (e o seu).
3. **Leitura.** "Compatível" quando a taxa observada cai no intervalo previsto; caso contrário, a diferença é relatada com a hipótese explicativa (por exemplo, variações menos independentes que no modelo, ou tentativas correlacionadas) e **nenhum parâmetro é ajustado com estes dados** (ADR 025 §4.3, passo 6). Se a falsa validação observada ou o seu intervalo contrariar o teto de 2 %, o resultado vai ao pesquisador com os números, sem ajuste automático.

## 7. N-abordagem-4 (falha de abordagem reproduzida)

**Fato medido (2026-10-19, `compute_verdict` v2, 4 falhas de abordagem em 4 configurações):** −0,141 com `q` = 0,3 (atual); −0,250 com 0,5; **−0,340 com 0,7**; −0,444 com 1,0. Com duas falhas na mesma configuração: −0,053, −0,111, −0,170 e −0,250. Com `q` = 0,7 o caso conclui `nao_funciona`, e a reprodução mínima continua indecisa, como o catálogo espera.

**Risco:** um Developer fraco falha por incapacidade, e não porque a abordagem não funciona; subir `q` aumenta a falsa refutação. É um compromisso que a simulação não mede hoje (as falhas simuladas são ambíguas ou de infraestrutura). Plano, em duas camadas:

1. **Offline (antes de qualquer sessão com LLM):**
   - o catálogo ganha **N-abordagem-3** (três configurações) e **N-abordagem-ruido** (falhas de abordagem em hipótese que depois funciona);
   - `variantes.json` ganha `completa2` com `approach_failure_q` em 0,5, 0,7 e 1,0;
   - a simulação ganha `p_falha_abordagem` (fração das tentativas que falham por abordagem, com a mesma assinatura) e o tipo `abordagem_falha` (todas as tentativas da abordagem falham);
   - medem-se, por `q`: conclusão correta da hipótese de abordagem plantada, **falsa refutação das hipóteses `verdadeira`** com Developer incapaz (`p_falha_abordagem` > 0) e a falsa validação (que não deve mudar).
   O resultado vai ao pesquisador com a proposta; **o valor só muda em `src/config.py` com aprovação**, em PR próprio com revisão do ADR 015 §9.9.
2. **Em sessões:** o regime F confirma o efeito do valor escolhido; a falsa refutação em P e T (hipóteses refutadas por falhas de abordagem do Developer) é relatada por combinação.

## 8. Saídas

`<saida>/` por rodada (a medição grava `resultados.csv`, `relatorio.md` e o seu próprio `manifesto.json` em `<saida>/medicao/`, para não colidir com o manifesto do orquestrador): `manifesto.json`, `orcamento.json`, `<combinação>/<regime>/r<r>/{exploracao.json, verdade/verdade.json, input_context/{dados.csv,dados.yaml}, grafo_projeto.json, eventos.json, sessao.tar.gz, run.log, pre_reset/}` (as sessões da cadeia estão em `exploracao.json`; `eventos.json` reúne os eventos de todas), `resultados.csv` (uma linha por hipótese e uma por exploração), `relatorio.md` (tabelas em português) e `manifesto.json` (commit, data UTC, comando, sementes, modelos e versões, variáveis `VERDICT_*` efetivas, sha256 de cada entrada). O diretório não pode já conter `manifesto.json` (`--sobrescrever` libera, como no laboratório); `--retomar` continua uma rodada interrompida (queda de luz, por exemplo) pulando as explorações que já têm `exploracao.json`. O `dados.csv` completo de cada exploração é regenerável pela semente e não é versionado.

Os relatórios do piloto e da bateria vão para `docs/calibracao-veredito/` (**nunca** para `docs/benchmarks/`), com pergunta, entradas, método, resultados, leitura, limitações, comandos e commit, escritos para a dissertação.

## 9. Pré-registro, limitações e riscos

**Pré-registro (fixado neste commit, antes dos resultados):** regimes e valores (§2.3), medidas (§6.2), critério de comparação (§6.3), regra de censura (§4.3) e a regra de que nenhum parâmetro é ajustado com os dados da etapa 3. A leitura do resultado contra o teto de 2 % é a do §6.3.

**Limitações declaradas no relatório:**

1. **Poder estatístico.** Com 5 a 15 explorações por regime e combinação, o intervalo de confiança é largo (0/15 ⇒ até ≈ 20 %); a bateria confirma compatibilidade com a previsão, não o teto de 2 %.
2. **`ao_atingir_objetivo = continuar`.** No uso real do modo `auto` o padrão é `parar`, e a pesquisa fecha na primeira variação que atinge o alvo, antes de o veredito concluir. O relatório mede o veredito sob exploração longa, que é a condição em que ele decide o ciclo de vida das hipóteses (ADR 021 §4).
3. **Rótulo no nível do problema.** Em P não se sabe se uma abordagem específica era boa; a refutação discordante é relatada como tal. Em T, N e F (abordagem plantada) toda validação é falsa com certeza.
4. **Dados sintéticos de uma família** (classificação binária tabular, métrica discreta); a generalização para outros domínios fica para a etapa 4 e para a V20.
5. **Dois modelos de agente** (Claude Haiku 5.5 e Sonnet 5.5, com GPT-6.1 Sol como Validator); variância entre repetições é medida, não eliminada.

| Risco | Mitigação |
|---|---|
| O agente lê a verdade ou o gerador | `verdade.json` fora de `input_context/`, das saídas da sessão e do ambiente; o gerador não é copiado para o sandbox; teste verifica os caminhos |
| Exploração sem fim consome o orçamento | Teto por exploração (US$, sessões, minutos), `sem_progresso` e censura |
| 429 do provedor ou queda de luz durante uma exploração | Retomada automática limitada; queda de luz deixa a exploração `falha`, retomável pelo `exploracao.json` |
| Resultado dependente do Developer que não variou | A medida "variações com evolução por hipótese" aparece ao lado do poder: poder baixo com poucas variações é limitação do agente, não do veredito |
| Ajustar o veredito aos novos dados | Regra do pré-registro; qualquer mudança passa pelo pesquisador com os números |
| Falsa refutação com Developer fraco ao subir `q` | Avaliada offline antes (§7) e medida no regime F e nas hipóteses de P e T |

## 10. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Arquitetura | Ferramenta em `scripts/` (como `verdict_lab` e `benchmark`); `src/` não muda. O orquestrador chama a CLI pública (`main.py`, `resume`) e lê o grafo pelas APIs existentes. |
| Dados | Escreve só em `--saida` e no banco de benchmark (isolado, com guardas). Dados sintéticos; nenhum dado de pesquisa real. |
| Segurança | §9 e §11. |
| Desempenho | Gerador e medição em processo único, segundos; o gasto está nas sessões de LLM. Memória do Pi: uma exploração por vez (ADR 023, verificação de memória). |
| Custo | Zero tokens exceto piloto e bateria, sob orçamento aprovado e confirmação. |
| Manutenção | Teste de equivalência do veredito com o laboratório na medição; teste de regressão do runner (Iris idêntico). |

## 11. Segurança

- Arquivos de entrada são locais e lidos com `json.load`/`csv`, sem `eval` nem pickle; chaves e caminhos fora do esperado são erro com o caminho do arquivo.
- O dado é sintético; a única informação sensível é a verdade do regime, isolada como no §3. Os agentes veem apenas o `Problema` e o dataset (com resumo seguro, spec `research-data`).
- Operações destrutivas (recriar o banco e o Qdrant de benchmark) usam as guardas já especificadas (`--reset-stores`, `--confirm-target`, marca no nome, banco diferente do de desenvolvimento) e nunca rodam em ensaio.
- O orquestrador não imprime chaves, URLs com senha nem o conteúdo de `.env`; o ambiente do subprocesso vem de `build_env`.
- O teto de gasto é imposto fora do agente (laço do orquestrador e `SESSION_MAX_COST_USD` do sistema).

Parecer do Analista de Segurança: a revisar no PR das specs (a mudança toca banco de benchmark, subprocessos e segredos de ambiente).

## 12. Questões em aberto

1. **Tetos do piloto e da bateria** (§5.2, §5.3): propostos, aprovados na tabela `orcamento` depois do piloto.
2. **Regime F**: o tamanho do volume e a reprodutibilidade da falha saem do piloto; se não reproduzir, o regime sai (§2.2).
3. **`VERDICT_APPROACH_FAILURE_Q`**: decisão do pesquisador depois da avaliação offline (§7).
4. **Repetições finais por regime**: dependem do custo medido no piloto.
5. **Direção da evidência pela predição** (`v18.8-verdict-direction`): não entra aqui; se a falsa refutação em P ou a refutação discordante indicarem a lacuna, abre-se a spec própria.
