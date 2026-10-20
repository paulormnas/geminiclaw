# Delta: benchmark

## ADDED Requirements

### Requirement: Dados sintéticos de resposta conhecida
O sistema SHALL gerar, por semente, conjuntos de dados de classificação binária em quatro regimes: P (efeito plantado, teto 0,96, alvo 0,93), T (teto abaixo do alvo, teto 0,90, alvo 0,93), N (rótulo independente dos atributos, alvo 0,55) e F (como P, com 12 000 linhas e volume que quebra a abordagem de núcleo denso no sandbox). A mesma semente MUST produzir o mesmo arquivo byte a byte, sem dependência nova. O teto e os patamares de P, T e F MUST ficar dentro de ±0,005 dos valores do regime, medidos no oráculo (ADR 025 §3, etapa 3; design §2).

#### Scenario: Determinismo
- **GIVEN** o regime P e a semente 7
- **WHEN** o gerador roda duas vezes
- **THEN** os dois `dados.csv` têm o mesmo `sha256`

#### Scenario: Teto e patamares do regime P
- **GIVEN** o regime P calibrado
- **WHEN** o oráculo avalia o preditor ideal e os preditores dos `k` primeiros termos em 200 000 linhas
- **THEN** o teto é 0,96 ± 0,005 e os patamares `p_0 … p_5` são 0,62, 0,74, 0,82, 0,88, 0,93 e 0,96, cada um ± 0,005

#### Scenario: Ruído puro
- **GIVEN** o regime N e 2 000 linhas
- **WHEN** se mede a acurácia do melhor limiar sobre cada atributo
- **THEN** nenhum atributo associa-se ao rótulo além do acaso esperado para o tamanho da amostra

#### Scenario: Dado visível ao Developer
- **WHEN** o gerador grava `dados.yaml`
- **THEN** o carregador de contexto aceita o arquivo e classifica `dados.csv` como `dado_de_pesquisa` `compartilhavel` com o motivo "dado sintético gerado para calibração"

### Requirement: Verdade isolada dos agentes
O sistema SHALL gravar o `verdade.json` de cada exploração (regime, semente, teto, alvo, patamares, `sha256` do dado, resposta correta e, no regime F, a assinatura esperada da falha) fora de `input_context/`, do diretório de saídas da sessão e do ambiente do subprocesso, e SHALL lê-lo somente na medição.

#### Scenario: Caminhos isolados
- **WHEN** o orquestrador prepara uma exploração
- **THEN** `verdade.json` não está sob `INPUT_CONTEXT_DIR` nem sob o diretório de saídas da sessão
- **AND** nenhuma variável do ambiente do subprocesso contém o caminho ou o conteúdo do `verdade.json`

### Requirement: Exploração até o fim natural com teto de gasto
O orquestrador de exploração SHALL iniciar a pesquisa em modo `auto`, retomar automaticamente depois de `limite_tokens`, `limite_tempo`, `limite_custo` e `limite_cota_provedor` enquanto o custo, o número de sessões e os minutos acumulados da cadeia forem menores que o teto da exploração, e SHALL parar em `solucao_encontrada`, `sem_caminhos_promissores` ou `saturacao` (fim natural), em outro motivo (fim por falha), ao atingir o teto de custo ou de sessões (`interrompida_pelo_orcamento`) ou depois de duas sessões seguidas sem experimento novo (`sem_progresso`). O orquestrador MUST NOT retomar depois de um fim natural. O comando SHALL aceitar `--retomar` para continuar uma rodada interrompida, pulando as explorações que já têm `exploracao.json`.

#### Scenario: Retomada depois do limite de custo
- **GIVEN** um teto de exploração de US$ 10, uma sessão fechada com `limite_custo` e custo acumulado de US$ 3 com 4 experimentos novos
- **WHEN** o orquestrador avalia o fim da sessão
- **THEN** inicia a retomada, ligada à sessão anterior por `continues_session_id`

#### Scenario: Fim natural
- **GIVEN** uma sessão fechada com `sem_caminhos_promissores`
- **WHEN** o orquestrador avalia o fim da sessão
- **THEN** a exploração termina com `fim = "natural"` e nenhuma sessão nova é iniciada

#### Scenario: Teto de gasto
- **GIVEN** um teto de US$ 4 e custo acumulado de US$ 4,10 depois de uma sessão fechada por `limite_tempo`
- **WHEN** o orquestrador avalia o fim da sessão
- **THEN** a exploração termina com `fim = "interrompida_pelo_orcamento"` e conta como censurada

#### Scenario: Cota repetida sem progresso
- **GIVEN** duas sessões seguidas fechadas com `limite_cota_provedor` e nenhum experimento novo
- **WHEN** o orquestrador avalia a segunda
- **THEN** a exploração termina com `fim = "sem_progresso"`

#### Scenario: Falha
- **GIVEN** uma sessão fechada com `planos_rejeitados`
- **WHEN** o orquestrador avalia o fim da sessão
- **THEN** a exploração termina com `fim = "falha"` e `motivo_final = "planos_rejeitados"`

### Requirement: Execução protegida
O orquestrador SHALL rodar em modo de ensaio por padrão (sem criar processo, sem tocar nos bancos) e SHALL, com `--executar`, exigir `--reset-stores` e `--confirm-target BANCO@HOST` com as mesmas guardas do runner de benchmark, recusando a execução com erro explícito antes de qualquer escrita quando faltar alguma.

#### Scenario: Ensaio por padrão
- **WHEN** o comando roda sem `--executar`
- **THEN** imprime o plano e o orçamento e não cria processo, banco nem diretório de saída além do plano

#### Scenario: Execução sem confirmação do alvo
- **WHEN** o comando roda com `--executar` e sem `--confirm-target`
- **THEN** termina com erro que mostra o alvo esperado (sem senha), sem apagar nada

### Requirement: Orçamento antes da execução
O comando `orcamento` SHALL calcular, sem chamar LLM nem abrir banco, por combinação e regime: número de explorações, teto por exploração, chamadas de LLM por papel, tokens e US$ (média e p90, quando há dados do piloto), gasto esperado e gasto máximo (explorações × teto), com total por combinação e geral. O gasto máximo MUST valer mesmo sem dados do piloto, e o orquestrador MUST impor o teto por exploração.

#### Scenario: Sem dados do piloto
- **GIVEN** um plano com 2 combinações, 4 regimes, uma repetição cada e teto de US$ 4 (haiku) e US$ 10 (sonnet)
- **WHEN** `orcamento` roda sem arquivo de piloto
- **THEN** o gasto máximo geral é US$ 56, as colunas esperadas mostram "sem dados" e nenhum LLM é chamado

#### Scenario: Com dados do piloto
- **GIVEN** um piloto com média de US$ 2,50 por exploração P da combinação sonnet e plano de 10 repetições
- **WHEN** `orcamento` roda
- **THEN** o gasto esperado de P na combinação sonnet é US$ 25,00 e o máximo é 10 × o teto

### Requirement: Estado da exploração registrado
O sistema SHALL gravar em `exploracao.json` o `fim`, o `motivo_final`, as sessões da cadeia (id, apelido, motivo de parada, custo, tokens, chamadas por papel e minutos), o custo total e por provedor, os totais de experimentos, resultados e hipóteses, e o nome, a versão e a fonte dos modelos de cada papel. Uma exploração que não termina em fim natural (orçamento, `sem_progresso` ou falha) SHALL ser marcada censurada.

#### Scenario: Cadeia de duas sessões
- **GIVEN** uma exploração com duas sessões ligadas por `continues_session_id`
- **WHEN** a exploração termina
- **THEN** `exploracao.json` lista as duas sessões em ordem, com o custo de cada uma, e o custo total é a soma

### Requirement: Medição com o veredito real
O comando `medir` SHALL calcular, por combinação e regime, sobre as explorações não censuradas: poder (regime P), falsa validação (regimes T, N e a abordagem plantada de F), refutação discordante (P), indecisão, contagem de hipóteses validadas, refutadas e indecisas, variações úteis e totais por hipótese (mediana, p10 e p90), tentativas até cruzar 0,3 e custo por validação útil em US$ e chamadas. Cada taxa MUST vir com `k/n` e intervalo de 95 % (Wilson; Clopper-Pearson quando `k` é 0 ou `n`). As explorações censuradas MUST ser contadas à parte.

#### Scenario: Poder e falsa validação
- **GIVEN** 10 explorações P (6 com hipótese validada) e 15 explorações N (1 com hipótese validada), todas não censuradas
- **WHEN** `medir` roda
- **THEN** o poder é 6/10 com o intervalo de Wilson de 95 % e a falsa validação de N é 1/15 com o seu intervalo

#### Scenario: Zero erros
- **GIVEN** 15 explorações T sem nenhuma hipótese validada
- **WHEN** `medir` roda
- **THEN** a falsa validação é 0/15 com o intervalo de Clopper-Pearson (limite superior ≈ 0,218)

#### Scenario: Censura
- **GIVEN** 3 explorações P interrompidas pelo orçamento entre 10
- **WHEN** `medir` roda
- **THEN** o poder usa 7 explorações, e o relatório informa "3 censuradas" para o regime P

#### Scenario: Custo por validação útil
- **GIVEN** explorações P que somam US$ 30 e 3 com hipótese validada
- **WHEN** `medir` roda
- **THEN** o custo por validação útil é US$ 10

### Requirement: Comparação com a previsão do laboratório
O comando `medir` SHALL (1) conferir que o veredito calculado pelo sistema coincide com o da variante `completa2` aplicada às mesmas tentativas (diferença ≤ 1e-12) e com o gravado no grafo (≤ 1e-6, arredondamento do sistema) e calcular a variante `atual` ao lado; (2) estimar da exploração os parâmetros da simulação (`sigma`, `tau`, probabilidades de variar e de falhar, tentativas por hipótese), rodar a simulação com a semente fixa e comparar, por regime, a taxa prevista com a observada; (3) classificar cada regime como compatível (taxa observada dentro do intervalo previsto) ou não, sem ajustar nenhum parâmetro com esses dados.

#### Scenario: Equivalência
- **GIVEN** um grafo arquivado cujas hipóteses têm veredito gravado pelo modelo v2
- **WHEN** `medir` reaplica `completa2`
- **THEN** a diferença entre o veredito do sistema e `completa2` é ≤ 1e-12 em todas as hipóteses e a diferença contra o valor gravado é ≤ 1e-6 (o sistema grava com seis casas); qualquer divergência encerra o comando com erro que cita a hipótese

#### Scenario: Taxa incompatível
- **GIVEN** falsa validação observada de 4/15 em N e previsão de 0,02 com intervalo [0, 0,06]
- **WHEN** `medir` classifica o regime
- **THEN** o relatório registra "incompatível" e nenhum valor de `VERDICT_*` é alterado

### Requirement: Rodada reprodutível
Cada rodada do orquestrador e da medição SHALL gravar `manifesto.json` com `commit`, data UTC, comando e argumentos, sementes, modelos e versões, variáveis `VERDICT_*` efetivas e `sha256` de cada entrada lida, e SHALL recusar um `--saida` que já contenha `manifesto.json` (salvo `--sobrescrever`); a medição grava em `<rodada>/medicao/`. Os relatórios SHALL ficar em `docs/calibracao-veredito/` e nunca em `docs/benchmarks/`.

#### Scenario: Saída ocupada
- **GIVEN** um `--saida` que já tem `manifesto.json`
- **WHEN** o comando roda sem `--sobrescrever`
- **THEN** termina com erro, sem alterar o diretório

#### Scenario: Mesma semente, mesma saída
- **GIVEN** o mesmo plano, commit e semente
- **WHEN** `orcamento` e a geração dos dados rodam duas vezes
- **THEN** `orcamento.json` e os `sha256` dos dados coincidem byte a byte

## MODIFIED Requirements

### Requirement: Runner de benchmark com semeadura e entrada configuráveis
O runner de benchmark SHALL aceitar, como parâmetros opcionais, a função de semeadura do projeto, o diretório de entrada (`INPUT_CONTEXT_DIR`) e variáveis de ambiente extras por execução, mantendo como padrão a semeadura do Iris e o diretório de entrada atual. (Antes: a semeadura e a tarefa eram fixas no Iris.)

#### Scenario: Iris inalterado
- **WHEN** o runner roda sem os parâmetros novos
- **THEN** semeia o projeto `Benchmark <combinação>` com o `Problema` do Iris e usa o `INPUT_CONTEXT_DIR` do ambiente, como antes

#### Scenario: Semeadura e entrada por exploração
- **GIVEN** uma função de semeadura de regime e um diretório de entrada próprio
- **WHEN** o runner executa a exploração
- **THEN** o subprocesso recebe `INPUT_CONTEXT_DIR` desse diretório e o projeto tem o `Problema` do regime
