# Delta: numeric-provenance

## ADDED Requirements

### Requirement: Sintaxe de referências numéricas
O sistema SHALL reconhecer, por um único parser, as formas `{{res:<exec_id>/<nome_metrica>}}`,
`{{calc:<expressão>}}` e `{{src:<id_insumo_ou_url>#<trecho>}}`, e SHALL tratar como erro de
sintaxe, com posição, qualquer `{{res:`, `{{calc:` ou `{{src:` que não case com a forma
completa.

#### Scenario: Referências válidas
- **WHEN** o texto contém `{{res:exec_<uuid4>/rmse}}`, `{{calc:res:exec_<uuid4>/a / res:exec_<uuid4>/b}}` e `{{src:https://exemplo.org/p#RMSE de 0,42 mm}}`
- **THEN** `find_references` devolve três referências com tipo, span e alvo corretos

#### Scenario: Referência malformada
- **WHEN** o texto contém `{{res:exec_123/rmse}}`
- **THEN** `find_malformed` devolve um erro com a posição, e a referência não é resolvida

#### Scenario: Nome de métrica inválido na gravação
- **WHEN** o código gerado chama `save_experiment_artifacts` com a chave de métrica `"acurácia final"`
- **THEN** a chamada falha com mensagem que indica o conjunto de caracteres permitido

### Requirement: Valor medido vem do registro de execução
O sistema SHALL resolver `{{res}}` a partir do registro de término da execução, conferindo o
sha256 do `metrics.json` (ou `params.json`, para `param.<nome>`) com o registrado, e SHALL
exibir o valor com unidade quando conhecida.

#### Scenario: Resolução com unidade
- **GIVEN** uma execução com registro de término e `metrics.json` com `metrics.rmse = 0.4498` e `unidades.rmse = "mm"`
- **WHEN** `{{res:<exec_id>/rmse}}` é renderizado
- **THEN** o texto exibe `0,4498 mm [R1]` e o apêndice traz o `exec_id`, a subtarefa, o arquivo e o sha256

#### Scenario: Artefato alterado após a execução
- **GIVEN** um `metrics.json` cujo sha256 difere do registro de término
- **WHEN** a referência é resolvida
- **THEN** o texto exibe a referência original seguida de `[não verificado]` e o motivo `artefato_alterado` aparece no apêndice

#### Scenario: Execução órfã
- **GIVEN** uma execução com registro de início e sem registro de término
- **WHEN** a referência é resolvida
- **THEN** ela é marcada `[não verificado]` com motivo `execucao_sem_termino`

### Requirement: Cálculo determinístico sem eval
O sistema SHALL avaliar `{{calc}}` com um avaliador próprio sobre uma árvore sintática com
lista de permissão (operadores `+ - * / **`, sinais unários, constantes numéricas, operandos
`res:`/`src:` e as funções `abs`, `min`, `max`, `media`, `sqrt`, `round`, `pct`), sem usar
`eval`, `exec` ou compilação de código, e SHALL exigir ao menos um operando de referência.

#### Scenario: Divergência percentual
- **GIVEN** `res` = 0,45 mm e `src` = 0,42 mm
- **WHEN** `{{calc:round(pct((res:… - src:…"…") / src:…"…"), 1)}}` é renderizado
- **THEN** o texto exibe `7,1 % [C1]` e o apêndice mostra a expressão com os códigos dos operandos

#### Scenario: Nó não permitido
- **WHEN** a expressão contém `__import__('os')` ou acesso a atributo
- **THEN** o avaliador levanta `CalcError` sem executar nada e o número é marcado `[não verificado]`

#### Scenario: Literal disfarçado de cálculo
- **WHEN** o texto contém `{{calc:0.95}}`
- **THEN** a resolução falha com `calculo_sem_referencia`

#### Scenario: Unidades incompatíveis e divisão por zero
- **WHEN** a expressão soma um valor em `mm` com outro em `s`, ou divide por um operando igual a zero
- **THEN** a resolução falha com `unidades_incompativeis` ou `CalcError`, e o número é marcado

### Requirement: Fonte citada conferida
O sistema SHALL resolver `{{src}}` somente quando o trecho existir no texto do `Insumo` (com
`hash_conteudo` conferido) ou no trecho que a busca técnica devolveu ao sistema e que foi
registrado em `fontes_busca.jsonl`, e o trecho contiver exatamente um número.

#### Scenario: Trecho de insumo encontrado
- **GIVEN** um `Insumo` PDF cujo texto contém "RMSE de 0,42 mm"
- **WHEN** `{{src:<id_insumo>#RMSE de 0,42 mm}}` é renderizado
- **THEN** o texto exibe `0,42 mm [S1]` e o apêndice traz o título e o trecho

#### Scenario: URL não consultada
- **WHEN** a URL citada não aparece em `fontes_busca.jsonl` das sessões do projeto
- **THEN** a citação é marcada `[não verificado]` com motivo `fonte_nao_consultada`

#### Scenario: Trecho ambíguo
- **WHEN** o trecho citado contém dois números
- **THEN** a resolução falha com `trecho_ambiguo`

### Requirement: Renderização com valor, unidade e origem
O sistema SHALL renderizar cada referência no formato numérico pt-BR com unidade e código de
origem (`R`, `C` ou `S`) e SHALL acrescentar ao relatório a seção do orquestrador "Origem dos
números", delimitada por `<!-- numeric-provenance:begin -->` e `<!-- numeric-provenance:end -->`.

#### Scenario: Apêndice completo
- **WHEN** o relatório tem duas referências `res`, uma `calc` e uma `src`
- **THEN** o apêndice lista `R1`, `R2`, `C1` e `S1` com valor exato, unidade, origem e detalhe

### Requirement: Números sem origem são marcados, não apagados
O sistema SHALL percorrer o texto final e marcar com `[não verificado]` todo número sem origem
— em algarismos, por extenso ou como multiplicador em pt-BR — sem apagar nem alterar o texto
do número, e SHALL listá-lo no apêndice.

#### Scenario: Algarismo literal
- **WHEN** o Summarizer escreve "a acurácia foi 0,95"
- **THEN** o relatório exibe "a acurácia foi 0,95 [não verificado]"

#### Scenario: Multiplicador por extenso
- **WHEN** o texto contém "o erro caiu três vezes" ou "ficou 3x menor" ou "o dobro"
- **THEN** cada ocorrência recebe `[não verificado]` e o texto original permanece

#### Scenario: Número após span renderizado
- **WHEN** o texto contém "{{calc:res:a / res:b}} vezes maior"
- **THEN** nenhum número é marcado

### Requirement: Exclusões estruturais por regra explícita
O sistema SHALL excluir da verificação somente os números que se enquadrem nas regras X1–X9
do design (spans renderizados, seções do orquestrador, código, numeração, identificadores,
datas, anos em contexto, contagens iguais às do orquestrador, artigos e ordinais).

#### Scenario: Ano e numeração de seção
- **WHEN** o texto contém "## 3.2 Resultados" e "publicado em 2021"
- **THEN** nenhum desses números é marcado

#### Scenario: Ano fora de contexto
- **WHEN** o texto contém "o modelo obteve 2000 amostras corretas"
- **THEN** "2000" é marcado `[não verificado]`

#### Scenario: Contagem do orquestrador
- **GIVEN** uma sessão com 3 subtarefas
- **WHEN** o texto contém "foram executadas três subtarefas" e, em outro ponto, "5 subtarefas"
- **THEN** "três" não é marcado e "5" é marcado `[não verificado]`

#### Scenario: Seção do orquestrador
- **WHEN** a seção `<!-- operation-metrics:begin -->` … `<!-- operation-metrics:end -->` contém tokens e custo
- **THEN** nenhum número dentro dela é marcado

### Requirement: Métricas literais sinalizadas
O sistema SHALL analisar estaticamente o código executado e sinalizar, sem bloquear a
execução, métricas gravadas como literais; o relatório SHALL exibir `[literal no código]`
junto às referências a essas métricas.

#### Scenario: Dicionário literal
- **WHEN** o código executado contém `save_experiment_artifacts("t", {}, {"acc": 0.95})`
- **THEN** `metricas_literais.json` registra `acc` com a linha e o padrão `P1`, e a execução segue normalmente
- **AND** `{{res:<exec_id>/acc}}` é exibido com `[literal no código]`

#### Scenario: Métrica calculada
- **WHEN** o código grava `metrics = {"acc": accuracy_score(y, y_hat)}`
- **THEN** nada é sinalizado

### Requirement: Contrato de escrita do Summarizer e do Curator
O Summarizer SHALL receber um catálogo de referências no lugar do bloco de métricas e SHALL ser
instruído a escrever referências e expressões, não números, sem calcular divergências nem
escrever os metadados de execução; as ferramentas de escrita do Curator SHALL recusar
referências malformadas ou que não resolvem e SHALL aceitar números sem referência com aviso.

#### Scenario: Instrução do Summarizer
- **WHEN** a instrução do Summarizer é carregada
- **THEN** ela descreve `{{res}}`, `{{calc}}` e `{{src}}` e não contém a ordem de calcular a divergência percentual

#### Scenario: Metadados pelo orquestrador
- **WHEN** o relatório final é gerado
- **THEN** a seção de metadados de execução é acrescentada pelo orquestrador, delimitada, com valores da telemetria

#### Scenario: Ferramenta do Curator com referência inválida
- **WHEN** o Curator chama `create_discovery` com `{{res:exec_<uuid4>/inexistente}}`
- **THEN** a ferramenta devolve erro com o motivo `metrica_ausente` e nada é gravado

#### Scenario: Ferramenta do Curator com número sem referência
- **WHEN** o Curator chama `create_discovery` com o enunciado "reduz o erro em 12%"
- **THEN** a descoberta é gravada, a ferramenta devolve aviso e o número é exibido com `[não verificado]`

### Requirement: Conversores exibem as marcas
Os conversores HTML, DOCX e LaTeX SHALL exibir os códigos de origem com ligação ao apêndice e
SHALL destacar visualmente `[não verificado]` e `[literal no código]`.

#### Scenario: HTML
- **WHEN** um relatório com `0,95 [não verificado]` e `0,87 [R1]` é convertido para HTML
- **THEN** o HTML contém `<mark class="nao-verificado">` e um link `#origem-R1` que existe no apêndice

#### Scenario: DOCX e LaTeX
- **WHEN** o mesmo relatório é convertido para DOCX e LaTeX
- **THEN** o DOCX tem o run "não verificado" em negrito com realce, inclusive dentro de tabela, e o LaTeX usa `\colorbox` com `xcolor` no preâmbulo

### Requirement: Contagens para métricas de operação
O sistema SHALL gravar `proveniencia_numerica.json` por sessão e SHALL expor ao
`v18.5-operation-metrics` as contagens por origem, de números não verificados e de métricas
literais.

#### Scenario: Leitura do grupo proveniência
- **GIVEN** um relatório com 3 `res`, 1 `calc`, 1 `src`, 2 números não verificados e 1 métrica literal
- **WHEN** `NumericProvenanceReader.read(session_id)` é chamado
- **THEN** devolve `numeros_por_origem = {"res": 3, "calc": 1, "src": 1}`, `numeros_nao_verificados = 2` e `metricas_literais = 1`
