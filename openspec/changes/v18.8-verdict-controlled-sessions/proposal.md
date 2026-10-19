# Proposta: Explorações controladas com efeito conhecido (etapa 3 do ADR 025)

**ID:** `v18.8-verdict-controlled-sessions` · **Versão:** V18.8

**Capacidades:** `benchmark`, `evidence-scoring`

**ADRs de origem:** [ADR 025](../../../docs/decisions/adr_025_calibracao_do_veredito.md) §3 (etapa 3), §4.1 a §4.3 (medidas, critério de 2 % e método registrado) e decisões 1 a 11; [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §9.9 (modelo v2); [ADR 021](../../../docs/decisions/adr_021_exploracao_rastreavel_por_hipoteses.md) §5 (parada pelo objetivo); [ADR 023](../../../docs/decisions/adr_023_pesquisa_em_segundo_plano.md) (sessão em processo próprio).

**Depende de:** `v18.8-verdict-lab` e `v18.8-verdict-calibration` (mergeadas: #222 a #228); `v18.7-background-sessions` e `v18.7-exploration-limits` (arquivadas ou mergeadas). Relatórios anteriores em [`docs/calibracao-veredito/`](../../../docs/calibracao-veredito/README.md).

**Nota de data:** escrita em 2026-10-19, a partir das decisões do pesquisador da mesma data (seção "Decisões do pesquisador").

## Por quê

O modelo v2 do veredito foi escolhido e medido só em simulação: 1,1 % de falsa validação e 29,9 % de poder (teto de 2 %). No replay dos 18 grafos arquivados nenhuma hipótese chega a 0,3, porque cada uma tem no máximo duas evidências positivas e concluir `funciona` exige cerca de cinco variações com evolução. A simulação supõe efeitos normais e tentativas independentes; falta confirmar com **agentes reais, tarefas de resposta conhecida e dados que o ajuste não viu** (ADR 025 §4.3, passo 6), e medir o que a simulação não alcança: quantas variações um agente produz por hipótese, quanto custa cada validação útil e como o veredito se comporta quando o Developer falha por incapacidade (caso N-abordagem-4, que dá −0,14 e fica indecisa).

O pesquisador também esclareceu o que é uma pesquisa: a sessão não é o terminal. A exploração deve terminar quando encontra solução ou não há mais hipóteses a testar, e não quando uma sessão fecha por limite. O sistema já roda a sessão em processo próprio (V18.7), mas o limite de uso fecha a sessão antes do fim natural e quem retoma é o pesquisador. A medição precisa de uma **exploração**: a cadeia de sessões retomadas até um fim natural ou até o teto de gasto do experimento.

## O que muda

### Novo

- **Gerador sintético com resposta conhecida** (`scripts/verdict_lab/controlled/`): conjuntos de dados determinísticos por semente, em quatro regimes (P efeito plantado, T teto abaixo do alvo, N ruído puro, F falha de abordagem plantada), cada um com `Problema` próprio e arquivo de verdade guardado fora do alcance dos agentes (design §2 e §3).
- **Orquestrador de exploração**: inicia a pesquisa em `auto` e segundo plano, retoma depois de `limite_tokens`, `limite_tempo` e `limite_custo` e para no fim natural (`solucao_encontrada`, `sem_caminhos_promissores`, `saturacao`), em falha, ou no teto de gasto da exploração (design §4).
- **Orçamento antes da execução**: comando `orcamento` que calcula, sem chamar LLM, o gasto máximo e o esperado por combinação e por repetição, a partir do teto e dos dados do piloto (design §5).
- **Medição com o veredito real**: poder, falsa validação, falsa refutação, indecisão, variações com evolução por hipótese e custo por validação útil, com intervalos de confiança, e **comparação com a previsão do laboratório** (design §6).
- **Tratamento do N-abordagem-4**: avaliação offline no laboratório (cenário N-abordagem-3, valores de `VERDICT_APPROACH_FAILURE_Q`, falhas de abordagem na simulação) antes da bateria, e confirmação com o regime F (design §7).
- **Pré-registro**: regimes, valores, medidas e critérios de leitura entram no `design.md` e no commit **antes** de qualquer resultado.
- **Relatórios** em `docs/calibracao-veredito/` (piloto e bateria), com comando, commit, sementes e sha256 das entradas.

### Modificado

- `scripts/benchmark/run_benchmark.py`: `seed_project` e o diretório de entrada deixam de ser fixos no Iris (parâmetros opcionais, comportamento atual por padrão), para o orquestrador reaproveitar o reset isolado, o arquivamento e os guardas (design §4.4).
- ADR 025 (etapa 3 e status), `roadmaps/roadmap_V18.8.md`, `openspec/README.md` e `docs/decisions/README.md`.

### Fora do escopo

- Mudar o código de `src/` (a equação, `DECISION_EVAL_MIN_VERDICT` e a política de parada não mudam). A única mudança possível de comportamento é o valor de `VERDICT_APPROACH_FAILURE_Q`, **só com aprovação do pesquisador depois da avaliação offline** (design §7), em PR próprio.
- Bateria no Raspberry Pi com a tarefa Iris (etapa 4 do ADR 025).
- Direção da evidência pela predição (`v18.8-verdict-direction`) e modelos de uma família só (Gemini, enquanto o teto de gasto não for ajustado).

## Impacto

- **Código:** `scripts/verdict_lab/controlled/` (novo), `scripts/verdict_lab/` (cenários e simulação de falha de abordagem), `scripts/benchmark/run_benchmark.py` e `seed_project.py` (parâmetros). Nenhum arquivo de `src/` muda nesta mudança.
- **Contratos:** formato de `verdade.json`, `exploracao.json`, `orcamento.json` e do manifesto das explorações (design §3, §4 e §8).
- **Schema:** nenhum.
- **Custo:** o gerador, o orçamento, a medição e o laboratório não chamam LLM. O piloto (8 explorações) e a bateria chamam LLM e só rodam com **confirmação explícita do pesquisador**, depois da tabela de orçamento aprovada.

## Aprovações necessárias

- **Esta spec e os valores dos regimes** (design §2.3), antes de qualquer implementação (aprovados em 2026-10-19).
- **Gasto de LLM:** a tabela de orçamento (design §5) e, separadamente, a confirmação de cada execução com LLM (piloto, depois bateria), com `--reset-stores --confirm-target geminiclaw_bench@localhost`.
- **Alterar `VERDICT_APPROACH_FAILURE_Q`** (se a avaliação offline recomendar): revisão do ADR 015 §9.9 e aprovação do pesquisador.
- Nenhuma aprovação de schema, Dockerfile, `docker-compose.yml`, `AGENTS.md` ou exclusão de arquivo.

## Decisões do pesquisador (2026-10-19)

- A unidade de medida é a **exploração** (cadeia de sessões até um fim natural), e não a sessão: a sessão não é o terminal, e a exploração termina por solução ou por falta de hipóteses (design §4).
- Rótulo de verdade no nível do problema; poder e falsa validação por exploração (design §6).
- Tarefa neutra, sem instrução para variar configurações; as variações vêm do que o agente faz sozinho.
- Piloto primeiro (uma exploração por regime e por combinação); regime F incluído.
- Valores sugeridos dos regimes aprovados (design §2.3).
