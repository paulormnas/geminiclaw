# Delta: evidence-scoring

## ADDED Requirements

### Requirement: Laboratório do veredito sem efeito no sistema
O sistema SHALL oferecer o laboratório `scripts/verdict_lab` (comandos `replay`, `grade`, `simulacao` e `sensibilidade`), que calcula o veredito sob variantes da fórmula sem chamada de LLM, sem acesso a banco ou rede e sem alterar `src/knowledge/verdict.py`, os valores de `src/config.py` ou o grafo (ADR 025 §1 e §3).

#### Scenario: Sem LLM, banco ou rede
- **GIVEN** os provedores LLM, o banco e a rede indisponíveis no teste
- **WHEN** cada um dos quatro comandos é executado com entradas de teste
- **THEN** todos terminam com código 0 e escrevem a saída
- **AND** nenhum provedor, conexão de banco ou socket é aberto

#### Scenario: Nenhum módulo do sistema depende do laboratório
- **WHEN** os imports de `src/` são inspecionados
- **THEN** nenhum módulo de `src/` importa `scripts.verdict_lab`

### Requirement: Variante atual idêntica ao veredito do sistema
O sistema SHALL garantir que a variante `atual` dê o mesmo resultado que `compute_verdict` com `VerdictParams.from_config()`, e que a reimplementação das alternativas de estrutura, com todas no valor atual, também dê (ADR 025 §1).

#### Scenario: Equivalência no catálogo
- **WHEN** a variante `atual` e a reimplementação com as alternativas no valor atual são aplicadas a todos os cenários do catálogo
- **THEN** veredito, `alpha`, `beta`, `f` e o detalhamento por tentativa coincidem com `compute_verdict` com diferença ≤ 1e-12

#### Scenario: Variáveis de ambiente valem no laboratório
- **GIVEN** `VERDICT_GAMMA=0.25` no ambiente
- **WHEN** a variante `atual` é calculada
- **THEN** o resultado é o de `compute_verdict` com `gamma = 0.25`
- **AND** o manifesto registra `gamma = 0.25` com origem `config`

### Requirement: Variantes declaradas em arquivo
O sistema SHALL ler as variantes de um arquivo JSON (`versao`, `variantes` com `nome`, `parametros` e `estrutura`), em que `parametros` sobrescreve campos de `VerdictParams` e `estrutura` escolhe as alternativas `n_config_conta_falhas`, `independencia`, `variacao_util`, `m_sem_baseline` e `b_por` do design §3.2; campo ou valor desconhecido é erro com o nome do campo.

#### Scenario: Campo desconhecido
- **WHEN** uma variante traz `parametros: {"gama": 0.3}`
- **THEN** o comando termina com erro que cita `gama` e a variante, sem calcular nada

#### Scenario: Falhas fora de n_config
- **GIVEN** uma hipótese com duas falhas ambíguas de configurações distintas e uma evidência positiva de uma terceira configuração, sem réplica
- **WHEN** a variante com `n_config_conta_falhas = false` é calculada
- **THEN** o `b` da evidência positiva é 1,0 (`n_config = 1`)
- **AND** na variante `atual` é `1 / (1 + 0,5 · ln 3)`

#### Scenario: Independência por tipo
- **GIVEN** `independencia = por_tipo` com `d_variacao = 1,0`, `d_replica_no = 0,5` e `d_semente = 0,2`
- **WHEN** a hipótese tem, em ordem, a configuração A no nó 1, a configuração B no nó 1, a configuração A no nó 2 e a configuração A no nó 2 com outra semente, todas com o mesmo dataset e cada nó numa só sessão
- **THEN** os `d` são 1,0, 1,0, 0,5 e 0,2

#### Scenario: Variação sem ganho é volume
- **GIVEN** `independencia = por_tipo` e `variacao_util = melhora_o_melhor` com `variacao_util_epsilon = 0`
- **WHEN** a configuração B (0,96) segue a configuração A (0,97) no mesmo nó, ambas acima do alvo
- **THEN** B recebe `d_semente`, e não `d_variacao`

#### Scenario: Alvo exigido com baseline
- **GIVEN** `criterio_com_alvo = exige_alvo`, alvo 0,95, `δ = 0,01` e baseline 0,333
- **WHEN** o resultado validado é 0,80
- **THEN** a evidência é negativa
- **AND** na variante `atual` a mesma tentativa é positiva

#### Scenario: Qualquer melhora conta como variação útil
- **GIVEN** `variacao_util = melhora_o_melhor` com o padrão `variacao_util_epsilon = 0`
- **WHEN** a configuração B (0,9601) segue a configuração A (0,96)
- **THEN** B recebe `d_variacao`

#### Scenario: Magnitude pela folga sem baseline
- **GIVEN** `m_sem_baseline = folga`, alvo 0,95, `δ = 0,01`, sentido `maior_melhor` e nenhum baseline
- **WHEN** o resultado é 0,96
- **THEN** a evidência é positiva com `m = 0,5`
- **AND** com resultado 0,98, `m = 1,0`

### Requirement: Repetição sobre grafos arquivados
O sistema SHALL recalcular, no comando `replay`, o veredito de cada hipótese com tentativas de arquivos `grafo_projeto.json`, coletando as tentativas com `KnowledgeService.collect_attempts` sobre um `InMemoryGraphStore` e comparando com o veredito gravado no nó (ADR 025 §3, etapa 1).

#### Scenario: Arquivo com métrica
- **GIVEN** um `grafo_projeto.json` com `Problema`, `Metrica`, `MEDE`, `Hipotese`, `Experimento -TESTA->` e `Resultado`, e veredito gravado igual ao de `compute_verdict`
- **WHEN** `replay` é executado
- **THEN** a saída lista a hipótese com veredito recalculado igual ao gravado e `metrica_reconstruida = false`

#### Scenario: Arquivo anterior sem métrica
- **GIVEN** um arquivo sem `Metrica` nem `MEDE`, com `Resultado` de `nome_original` igual à métrica do critério
- **WHEN** `replay` é executado
- **THEN** as tentativas são reconstruídas por esse nome, a hipótese sai com `metrica_reconstruida = true`
- **AND** o relatório conta as hipóteses cujo veredito recalculado diverge do gravado

#### Scenario: Hipótese sem tentativa
- **WHEN** o arquivo tem hipóteses sem `TESTA`
- **THEN** elas são contadas no relatório como não testadas e não entram nas tabelas de veredito

### Requirement: Grade sintética com desfecho esperado
O sistema SHALL aplicar, no comando `grade`, cada variante a um catálogo determinístico de cenários das famílias E, V, R, S, N, F, M e B (design §4), cada cenário com `esperado` ∈ {`funciona`, `nao_funciona`, `indeciso`}, e registrar por (cenário, variante, limiar) o veredito, a leitura e o acerto contra o esperado (ADR 025 §3, etapa 2).

#### Scenario: Acerto contra o esperado
- **GIVEN** um cenário `esperado = indeciso` e uma variante em que seu veredito é 0,35, com limiar 0,3
- **WHEN** a grade é executada
- **THEN** a linha registra `conclui = funciona` e `acerto = false`

#### Scenario: Vários limiares
- **WHEN** `--limiar 0.2 0.3` é passado
- **THEN** cada par (cenário, variante) aparece uma vez por limiar

#### Scenario: Esperado pelas regras do pesquisador
- **WHEN** o catálogo é carregado
- **THEN** E3 (três variações positivas, cada uma melhor que a anterior) tem `esperado = funciona`
- **AND** E2 e V8 (oito variações com o mesmo valor) têm `esperado = indeciso`
- **AND** existem as famílias C, D, G, P e Q do design §4

#### Scenario: Caso da etapa 1 no catálogo
- **WHEN** o catálogo é carregado
- **THEN** a família F tem o cenário de sete falhas ambíguas seguidas de uma positiva sem baseline, cujo veredito na variante `atual` é 0,0138 ± 0,0005

### Requirement: Simulação com resposta conhecida
O sistema SHALL simular, no comando `simulacao`, hipóteses `verdadeira`, `falsa` e `sem_efeito` com ruído (`sigma`), efeito por configuração (`tau`), probabilidade de variação, de falha e número de nós (design §5), e medir por variante e por número de tentativas as taxas de falsa validação, falsa refutação e indecisão e as tentativas até cruzar 0,1, 0,3 e 0,5 (ADR 025 §4).

#### Scenario: Reprodutível pela semente
- **WHEN** a simulação é executada duas vezes com `--semente 7` e os mesmos argumentos
- **THEN** os dois `resultados.csv` são idênticos byte a byte

#### Scenario: Falsa validação medida
- **GIVEN** hipóteses `sem_efeito` com `sigma = 0` e `tau = 0`
- **WHEN** a simulação é executada para qualquer variante
- **THEN** a taxa de falsa validação é 0

#### Scenario: Recordes por acaso medidos
- **GIVEN** hipóteses `sem_efeito` com `sigma > 0`, `p_variacao = 1` e 20 tentativas
- **WHEN** a simulação é executada com a variante `por_tipo + melhora_o_melhor`
- **THEN** a saída traz, por `variacao_util_epsilon` (0, `δ` e `sigma`), a taxa de falsa validação e o poder

#### Scenario: Curva de compromisso
- **WHEN** a simulação termina
- **THEN** o relatório traz, por variante, falsa validação e poder para cada limiar de 0,1 a 0,6 em passos de 0,1
- **AND** o custo por validação útil

#### Scenario: Estimativa antes de começar
- **WHEN** a simulação começa
- **THEN** o comando imprime o número estimado de cálculos do veredito antes do primeiro

### Requirement: Sensibilidade e propriedades por variante
O sistema SHALL medir, no comando `sensibilidade`, a variação do veredito por variação isolada e em pares de cada parâmetro, ordenando os parâmetros pelo efeito, e, com `grade --propriedades`, as propriedades de limites, determinismo, ordem de entrada, monotonicidade, simetria e volume sem ganho (design §6), relatando o número de violações e um exemplo de cada sem reprovar a variante.

#### Scenario: Assimetria da variante atual relatada
- **WHEN** as propriedades da variante `atual` são medidas
- **THEN** a simetria aparece com violações e um exemplo em que a penalidade de busca altera o módulo do veredito
- **AND** o comando termina com código 0

#### Scenario: Parâmetro sem efeito
- **GIVEN** cenários com uma única evidência positiva
- **WHEN** a sensibilidade de `d_new_seed` é medida
- **THEN** a variação do veredito é 0 e o parâmetro aparece no fim da ordenação

### Requirement: Saída reprodutível
O sistema SHALL escrever em `--saida` os arquivos `resultados.csv`, `relatorio.md` e `manifesto.json`, este com commit, data UTC, comando e argumentos, variantes com parâmetros efetivos, sementes e caminho e sha256 de cada entrada, recusando diretório que já tenha `manifesto.json` sem `--sobrescrever`.

#### Scenario: Manifesto completo
- **WHEN** `replay` lê dois arquivos
- **THEN** `manifesto.json` lista os dois com o sha256 de cada um e o commit atual

#### Scenario: Resultado anterior protegido
- **GIVEN** `--saida` com um `manifesto.json`
- **WHEN** o comando é executado sem `--sobrescrever`
- **THEN** termina com erro e não altera nenhum arquivo do diretório
