# Benchmark de modelos no pipeline V17/V18: resultados de 2026-10-13

Tarefa: pipeline de classificação supervisionada do dataset Iris (prompt do `run.sh`, arquivo `scripts/benchmark/task_iris.txt`), modo autônomo, Raspberry Pi 5 (8 GB, kernel de 16K), `dev` entre os commits `91e5f57` e `2588d86` (cada combinação rodou com as correções listadas abaixo já mergeadas; ver nota de tempos). Cada combinação usa o mesmo modelo em todos os papéis (Researcher, Validator, Developer, Reviewer, Summarizer, Base), com um projeto de pesquisa novo e um `Problema` confirmado (acurácia ≥ 0,95, ganho mínimo 0,01 sobre o baseline), criado pelo próprio benchmark. Dados em `~/bench/results-2026-10-12.json` no Pi.

Este relatório complementa `2026-10-01-modelos-baixo-custo-resultados.md`: aquele media o pipeline antigo (sem projeto, grafo, proveniência nem verificação); este mede o sistema V17/V18/V18.5 completo, com memória de grafo, vetores, egresso e métricas de operação.

## Resultado em uma frase

**Só o Claude Sonnet 5.5 chegou ao fim por conta própria** (`sem_caminhos_promissores`, 162 s, US$ 0,43); o Claude Haiku 5.5 também fechou o plano (2 de 2 subtarefas), mas parou no limite de execuções de agentes depois de gastar a maior parte do tempo planejando. Gemini 3.8 flash e GPT Terra pararam por `erro` (disjuntor de zero progresso: o revisor reprovou a mesma subtarefa repetidamente) e o GPT Luna em esforço `xhigh` esgotou 3 milhões de tokens sem convergir, a US$ 0,48. O benchmark também expôs **onze defeitos do sistema**, todos corrigidos antes desta rodada final (seção "Defeitos encontrados").

## Configuração

| Item | Valor |
|---|---|
| Modelos | `google/gemini-3.8-flash`, `anthropic/claude-haiku-5-5`, `openai/gpt-5.6-terra`, `openai/gpt-6-luna` (esforço `xhigh`, o máximo aceito), `anthropic/claude-sonnet-5-5` |
| Esforço | Claude `medium`; Terra sem raciocínio (`none`); Luna `xhigh` (via API Responses, que a OpenAI exige para ferramentas com raciocínio) |
| Orçamento | 3 000 000 tokens, 180 min por sessão, 12 000 s por combinação; retentativas de tarefa e de conexão pelos padrões |
| Localidade | `LOCALITY_MIN_GROUP_SIZE=10` (valor fixado pelo benchmark; é decisão do pesquisador) |
| Limite de taxa | 60 requisições/min; sem fallback de modelo |
| Execuções | **uma por combinação** (ver "Limitações") |
| Preços (US$/MTok) | Gemini 3.8: 0,75/3,75; Haiku 5.5: 0,10/0,50 (0,50/2,50 acima de 100K de entrada); Sonnet 5.5: 2/10; Terra: 2/12; Luna: 0,10/0,50 |

## Resultados por combinação

| Combinação | Motivo de parada | Tempo (s) | Tokens in | Tokens out | Chamadas LLM | Custo estimado (US$) | Subtarefas ok | Acurácia declarada | Checklist |
|---|---|---|---|---|---|---|---|---|---|
| Gemini 3.8 flash | `erro` (zero progresso) | 706,7 | 889 407 | 81 536 | 68 | 0,97 | 2/4 | 0,967 | 6/6 |
| Claude Haiku 5.5 | `limite_execucoes` | 1297,1 | 825 819 | 350 124 | 38 | 0,26 | 2/2 | 1,000 | 6/6 |
| GPT Terra | `erro` (zero progresso) | 1314,6 | 1 442 839 | 138 680 | 107 | 4,55 | 2/9 | 0,950 | 6/6 |
| GPT Luna `xhigh` | `limite_tokens` | 5524,4 | 2 489 982 | 466 840 | 167 | 0,48 | 3/8 | 1,000 | 6/6 |
| Claude Sonnet 5.5 | `sem_caminhos_promissores` | 161,8 | 132 390 | 16 400 | 10 | 0,43 | 1/2 | 0,950 | 6/6 |

- **Acurácia e checklist** vêm de `scripts/benchmark/scoring.py`: leem os artefatos da sessão (não reexecutam o código); a acurácia é a que o próprio pipeline declara. O checklist 6/6 de todas as combinações mostra que os artefatos existem, não que o pipeline foi aprovado.
- **Custo** é estimado pela tabela de preços do projeto a partir de `token_usage`. Conferido com o painel do pesquisador: Anthropic bate exatamente (US$ 6,37 até 12/10, contra o mesmo valor estimado); a OpenAI fica ~22-25% **acima** do painel (a tabela não desconta tokens em cache), ou seja, o custo real do Terra e da Luna é menor que o da tabela.
- **Gasto total do benchmark (estimado, todas as rodadas e testes de 12 e 13/10):** OpenAI US$ 8,0; Anthropic US$ 1,4; Google US$ 3,9. Saldos de US$ 20 por provedor nunca estiveram em risco.

### Leitura das paradas

| Combinação | O que aconteceu |
|---|---|
| Gemini 3.8 flash | 5 planos aprovados pelo Validator. As quatro primeiras reprovações das subtarefas de treino foram por `metrics.json` sem a chave `accuracy` (o modelo corrigiu depois); a quinta foi legítima: a regressão logística teve acurácia de teste 0,933, abaixo do critério ≥ 0,95 que o próprio plano fixou. Depois de 4 replanejamentos o disjuntor encerrou. |
| Claude Haiku 5.5 | O Validator (Haiku) reprovou 6 das 8 validações de plano do Researcher (Haiku): 24 chamadas do Researcher (1,0 M tokens no total) e 22 execuções de agentes até o limite de execuções por sessão. Só uma subtarefa de código rodou (a EDA); o `metrics.json` dela usou a chave `metricas` (português) na raiz, que o sistema não reconhece. Mais barato de todos (US$ 0,26). |
| GPT Terra | 11 planos (3 reprovados), 107 chamadas e US$ 4,55 estimados (≈ US$ 3,5 reais). O revisor reprovou 12 de 14 subtarefas: artefatos pedidos com nome diferente do gravado (`iris_eda_report.md`, `iris_split_indices.csv`) e métrica `accuracy` ausente, porque o modelo gravou `test_accuracy`/`test_accuracy_reserved`, nomes que o revisor não reconhece como `accuracy`. O disjuntor encerrou com 2 de 9. O mais caro. |
| GPT Luna `xhigh` | 11 ciclos de plano e 66 execuções no sandbox; o revisor reprovou 10 de 12 subtarefas. Três subtarefas aprovadas. O raciocínio máximo tornou cada plano lento (média de 55 s e máximo de 360 s por chamada do Researcher), e o custo por token é baixo (US$ 0,48 no total). Não convergiu em 3 M tokens nem 92 min. |
| Claude Sonnet 5.5 | As duas validações de plano aprovaram, uma subtarefa foi reprovada pelo revisor e não restaram caminhos: terminou em 2,7 min com 10 chamadas. O mais rápido. |

## Recursos do Raspberry Pi 5

| Combinação | CPU do sistema máx (%) | RAM usada máx (MB) | RAM livre mín (MB) | Temp máx (°C) | Throttling |
|---|---|---|---|---|---|
| Gemini 3.8 flash | 35,1 | 1852 | 6263 | 62,8 | não |
| Claude Haiku 5.5 | 41,6 | 1738 | 6349 | 60,6 | não |
| GPT Terra | 38,4 | 1842 | 6320 | 60,6 | não |
| GPT Luna `xhigh` | 71,5 | 2336 | 6055 | 68,9 | não |
| Claude Sonnet 5.5 | 54,0 | 2145 | 6114 | 70,0 | não |

O hardware nunca foi o gargalo: o pico de RAM foi 2,3 GB de 8 GB e não houve throttling. A maior CPU (Luna, 71,5%) e a maior temperatura (Sonnet, 70 °C) coincidem com rajadas do sandbox de código, do `fastembed` e do Postgres (amostragem de 1 s). Retentativas de conexão: zero em todas.

## Memória de conhecimento: vetores e grafo

| Combinação | Vetores novos (Qdrant `knowledge_nodes`) | Nós do projeto | Arestas | Nós por rótulo |
|---|---|---|---|---|
| Gemini 3.8 flash | 17 | 68 | 84 | Resultado 41, Abordagem 9, Experimento 7, Decisão 5, Hipótese 3, Problema 1, Projeto 1, Sessão 1 |
| Claude Haiku 5.5 | 20 | 24 | 27 | Abordagem 12, Decisão 4, Hipótese 4, Experimento 1, Problema 1, Projeto 1, Sessão 1 |
| GPT Terra | 58 | 111 | 145 | Abordagem 38, Resultado 36, Decisão 17, Experimento 14, Hipótese 3, Problema 1, Projeto 1, Sessão 1 |
| GPT Luna `xhigh` | 105 | 124 | 149 | Abordagem 54, Resultado 31, Decisão 21, Experimento 12, Hipótese 3, Problema 1, Projeto 1, Sessão 1 |
| Claude Sonnet 5.5 | 15 | 26 | 28 | Abordagem 9, Resultado 7, Decisão 3, Hipótese 3, Experimento 1, Problema 1, Projeto 1, Sessão 1 |

- Cada combinação criou **seu** projeto (título, objetivo, domínio "Aprendizado de Máquina"), o `Problema` confirmado e as hipóteses/decisões/abordagens do plano, o que mostra a memória de grafo registrando o projeto em todas as sessões. O Qdrant só recebeu a coleção `knowledge_nodes` (a `geminiclaw_documents` ficou em zero: não havia documentos em `input_context/`). Os vetores correspondem só aos rótulos vetorizáveis: entre 0,25 e 0,85 vetor por nó do projeto.
- Quanto mais replanejamentos, mais `Abordagem`, `Decisão` e vetores: Luna (11 planos) criou 54 abordagens; Sonnet (1 plano) 9. Os nós `Resultado` acompanham as métricas gravadas (Gemini 41).
- Linhas gravadas por combinação: `execution_records` (cadeia de proveniência) 86 / 2 / 72 / 220 / 10; `egress_log` 69 / 42 / 128 / 368 / 18; `knowledge_audit` 26 / 25 / 73 / 127 / 19 (na ordem Gemini, Haiku, Terra, Luna, Sonnet). A Haiku teve só 2 registros porque rodou 1 execução de código.

## Métricas de operação (v18.5-operation-metrics)

| Combinação | Egresso (bytes, fora do nó) | Buscas | Principais intervenções do filtro | Cadeia de execuções | Planos reprovados |
|---|---|---|---|---|---|
| Gemini 3.8 flash | 2 963 090 | 1 | tabela retida, traceback literal, estatística sem n | íntegra | 0 |
| Claude Haiku 5.5 | 1 589 037 | 4 | dado de pesquisa retido | íntegra | 6 |
| GPT Terra | 5 016 532 | 12 | tabela retida, estatística sem n | íntegra | 3 |
| GPT Luna `xhigh` | 8 532 269 | 55 | extremo em faixa (1874), estatística sem n (830), tabela retida (326) | íntegra | 5 |
| Claude Sonnet 5.5 | 249 121 | 1 | extremo em faixa, dado retido | íntegra | 0 |

- **Egresso:** quase todo o volume é `instrucao` (prompts); a saída de execução enviada fora do nó foi de 4,7 KB (Terra) a 666 KB (Luna). O filtro de localidade agiu em todas as sessões. As 55 buscas do Luna são consultas do agente a cada tentativa.
- **Cadeia de execuções:** verificada de novo no Pi depois da última correção (#137): **íntegra nas cinco sessões**, sem órfãs. (O `operation_metrics` gravado nas sessões diz "divergente" porque foi calculado antes da correção.)
- **Números do relatório** (só nas sessões que chegaram ao Summarizer): Haiku 0 números por referência e 12 não verificados; Luna 8 por referência e 12 não verificados; Sonnet 7 por referência e 11 não verificados. Gemini e Terra fecharam por `erro` e não geraram relatório.
- **Verificação de afirmações:** quase tudo ficou `nao_verificavel` (Haiku 53, Luna 58); o Sonnet não gerou `afirmacoes.json`. Ou a decomposição e o verificador determinístico ainda cobrem pouco as conclusões em prosa, ou há defeito; **pendente de investigação**.
- Modo sem limite: não usado.

## Defeitos encontrados pelo benchmark (todos corrigidos e mergeados em `dev`)

| # | PR | Defeito | Efeito observado |
|---|---|---|---|
| 1 | #121 / #123 | Colisão de pacote `provenance` nos testes; build do sandbox enviava 6 GB de contexto | Suíte completa não coletava; `ensure` do sandbox demorava minutos |
| 2 | #124 | `/chat/completions` recusa ferramentas com raciocínio ligado | Luna `xhigh` não rodava; agora usa a API Responses |
| 3 | #125 | Modo de entrega `copy` do sandbox nunca entregava os insumos (`put_archive` não grava em tmpfs) | Falha silenciosa; agora `tar` sem root |
| 4 | #129 | Plano bruto do Researcher não era gravado; Curator sem modelo elegível contava como falha | Impossível auditar uma sessão que retirou todas as subtarefas |
| 5 | #131 | EDA e síntese com `approach` preenchido eram retiradas por "sem hipótese" | Gemini fechava em 1 min sem executar nada |
| 6 | #132 | Cadeia de proveniência "divergente" a cada retentativa; Validator reprovava `approach`/`hypothesis_ref`; matriz com 500 mil tokens | Quatro de cinco sessões sem relatório final; Luna reprovada por campos do próprio formato |
| 7 | #133 | `metrics.json` com métricas na raiz era reprovado como "métrica ausente" | Gemini caía no disjuntor de zero progresso |
| 8 | #135 | Compressão de contexto separava a chamada de ferramenta da sua resposta (400 da OpenAI); NUL na telemetria derrubava o lote | Luna xhigh fechava por `erro` |
| 9 | #136 | `neighbors` usava caminho de comprimento variável do AGE (0,25 s por consulta no Pi) | Ciclo de hipóteses passou de 16 s para **869 s** com o grafo crescendo; agora 2-17 s |
| 10 | #137 | `script.py` reescrito pelo sandbox acusado como alteração | Cadeia "divergente" em todas as sessões |
| 11 | #130 | Retirada de subtarefas sem motivo registrado | Diagnóstico demorado de #5 |

Efeito somado nos tempos: o ciclo de hipóteses (validação do plano até registro no grafo) caiu para **2 a 17 s** em todas as sessões da tabela (antes: 254 a 869 s com o grafo cheio). Luna e Sonnet rodaram depois do #136 e antes do #137 (que só muda a verificação de proveniência, não o tempo); Gemini, Haiku e Terra rodaram depois do #137.

## Limitações e cuidados

1. **Uma execução por combinação, variância alta.** O Gemini 3.8 flash rodou várias vezes ao longo do dia e, com o sistema funcional, teve desfechos diferentes: `limite_tokens` com 500 mil tokens (2/4 subtarefas, acurácia 0,958), `sem_caminhos_promissores` (4/5, 1,000) e `erro` (2/4, 0,967, a rodada desta tabela). Nenhuma diferença entre modelos deste relatório deve ser lida como ordenação sem repetir 3 a 5 vezes.
2. **A parada por `erro` e por `limite_*` é resultado do modelo sob as regras do sistema**, não do hardware: o revisor LLM é rígido com nomes de arquivo, chaves de `metrics.json` e critérios numéricos do próprio plano (0,95), e o disjuntor de zero progresso encerra depois de ciclos sem avanço.
3. **O `Problema` e o projeto foram semeados pelo benchmark** (alvo 0,95; `delta_min` 0,01), sob autorização do pesquisador; a confirmação usa o mesmo caminho de produção. Mudar o alvo muda quais modelos "passam".
4. **Custos:** Claude confere com o painel; GPT está ~25% acima do real. Terra e Haiku têm preços de fontes secundárias (confirmar nas páginas oficiais antes de usar como cobrança). Luna `xhigh` e Terra com raciocínio ligado não foram comparados com a Luna sem raciocínio nesta rodada.
5. **Tempos incluem a espera da API** (limite de 60 req/min configurado); o Luna `xhigh` gastou a maior parte do tempo em raciocínio no Researcher.
6. Não foi usado Ollama (previsto para outro ambiente).

## Pendências

- Investigar por que a verificação de afirmações classifica quase tudo como `nao_verificavel`.
- `neighbors` sem filtro de relação ainda leva ~450 ms (37 tabelas de aresta); só afeta `graph show --depth`.
- Repetir a matriz 3 a 5 vezes por combinação e reportar médias e desvios.
- Rever o rigor do revisor LLM (nomes de arquivo e chaves exatas reprovam resultados válidos) e o critério de zero progresso.
- Calibrar o preço do GPT com o desconto de tokens em cache.
- Tolerância do revisor aos nomes das métricas: `test_accuracy`, `test_accuracy_reserved` e a chave `metricas` (pt) reprovam resultados válidos (Terra e Haiku); avaliar aliases com prefixo/sufixo `test_`/`holdout_`, mantendo `cv_*` distinto.
