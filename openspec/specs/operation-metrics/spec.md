# Especificação: operation-metrics

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md), [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md), [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md), [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Métricas de operação registradas por sessão
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
O sistema SHALL agregar, para cada sessão, as métricas de egresso, proveniência, verificação,
custo e recursos, e intervenções humanas definidas no ADR 019 §8, e gravá-las em
`agent_sessions.payload["operation_metrics"]` e em `session_metadata.json`.

#### Scenario: Fechamento grava as métricas
- **GIVEN** uma sessão com chamadas LLM, execuções no sandbox e uma resposta a `ask_researcher`
- **WHEN** a sessão é fechada por qualquer motivo
- **THEN** `payload["operation_metrics"]` contém os grupos `egresso`, `proveniencia`, `verificacao`, `custo_recursos` e `intervencoes_humanas`, com `versao=1` e `parcial=false`
- **AND** `session_metadata.json` contém a mesma estrutura

#### Scenario: Egresso por destino e por origem
- **GIVEN** `egress_log` com envios a dois provedores de `trust` diferentes e trechos de origens `instrucao` e `saida_execucao`
- **WHEN** as métricas são agregadas
- **THEN** `egresso.por_destino` separa bytes e chamadas por provedor, modelo, `trust` e `localidade`
- **AND** `egresso.por_origem` traz bytes por valor de `ContentOrigin`
- **AND** intervenções do filtro, consultas de busca e chamadas de visão são contadas

#### Scenario: Custo e recursos por tarefa
- **GIVEN** duas subtarefas, uma com modelo de nuvem e outra com modelo local sem custo informado
- **WHEN** as métricas são agregadas
- **THEN** `custo_recursos.por_tarefa` traz tokens das duas e custo apenas da primeira; a segunda tem custo `null`
- **AND** picos de CPU, RAM e temperatura do nó vêm da telemetria existente, ou `null` quando o sensor não existe

#### Scenario: Intervenções humanas
- **GIVEN** o pesquisador aprovou uma hipótese, rejeitou outra, editou um enunciado e interrompeu a sessão
- **WHEN** as métricas são agregadas
- **THEN** `intervencoes_humanas` registra 1 aprovação, 1 rejeição, 1 edição e 1 interrupção, com os eventos datados

### Requirement: Métricas agregadas, não produzidas, por esta capacidade
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
O sistema SHALL obter cada grupo de métricas de um leitor do produtor responsável e SHALL
marcar como `indisponivel` ou `erro` o grupo cujo produtor não existe ou falha, sem preencher
valores numéricos.

#### Scenario: Produtor não implementado
- **GIVEN** que `v18.5-claim-verification` ainda não foi implementada
- **WHEN** a sessão fecha
- **THEN** `verificacao.estado="indisponivel"` com o nome da mudança produtora e sem contagens
- **AND** o relatório mostra "indisponível (v18.5-claim-verification)"

#### Scenario: Falha de leitura isolada
- **WHEN** o leitor de `egresso` levanta exceção
- **THEN** `egresso.estado="erro"` com a mensagem, os demais grupos são gravados e o fechamento conclui
- **AND** é registrado o evento `operation_metrics_error`

### Requirement: Seção de métricas no relatório renderizada pelo orquestrador
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
O sistema SHALL acrescentar ao `relatorio_final.md` a seção "Métricas de operação", gerada por
código determinístico a partir de `operation_metrics`, e SHALL NOT enviar estatísticas de
telemetria ao Summarizer para que ele as reescreva.

#### Scenario: Seção determinística
- **WHEN** o relatório final é gerado
- **THEN** a seção "Métricas de operação" aparece delimitada por `<!-- operation-metrics:begin -->` e `<!-- operation-metrics:end -->`
- **AND** seus números são iguais aos de `payload["operation_metrics"]`

#### Scenario: Summarizer sem estatísticas
- **WHEN** o prompt do Summarizer é montado
- **THEN** ele não contém o bloco de `get_summarized_stats`

### Requirement: Limite de volume de egresso como condição de parada
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
Fora do modo sem limite, o sistema SHALL tratar o volume de egresso de saídas de execução por
sessão como condição de parada graciosa, com `motivo_parada="limite_egresso"`.

#### Scenario: Limite de egresso atingido
- **GIVEN** `max_egress_bytes` igual a 1 000 000 e sessão sem modo sem limite
- **WHEN** o volume registrado pelo `EgressGate` atinge 1 000 000 bytes
- **THEN** nenhuma nova chamada externa é despachada, as em andamento são aguardadas e o fechamento grava o checkpoint com `motivo_parada="limite_egresso"`
- **AND** a sessão pode ser retomada

### Requirement: Modo sem limite explícito
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL oferecer o modo sem limite apenas por opção explícita do pesquisador, por sessão (`--unlimited`) ou por projeto, e SHALL exigir confirmação no início de cada execução, no terminal (ADR 023 §1) ou pelo gate persistente quando a sessão já roda em segundo plano. O modo SHALL NOT ser ativado por padrão, por variável de ambiente, por configuração ou por qualquer agente. O texto da confirmação SHALL dizer que tokens, tempo, custo e volume de egresso não interrompem a sessão e que, sem limites, não há parada automática garantida: a sessão segue até o objetivo (conforme a política), a falta de caminho, a saturação, o pesquisador ou uma falha. O texto SHALL dizer também que, no `auto`, a sessão pode rodar indefinidamente e que só `wait_for_health` e `SANDBOX_MIN_FREE_BYTES` protegem o hardware (ADR 021 §5.4, §5.5; parecer de segurança, item 5).

#### Scenario: Ativação por sessão confirmada
- **WHEN** o pesquisador executa `geminiclaw --unlimited "<prompt>"` e digita "sem limite" na confirmação
- **THEN** a sessão inicia com `UsageBudget(unlimited=True)`, `max_cost_usd = None`, e `payload["budget"]` registra `unlimited=true`, a origem `cli` e o instante da confirmação

#### Scenario: Texto da confirmação
- **WHEN** a confirmação é exibida
- **THEN** o texto contém "custo" e "não há parada automática garantida"
- **AND** o texto contém "indefinidamente", `wait_for_health` e `SANDBOX_MIN_FREE_BYTES`

#### Scenario: Confirmação ausente
- **WHEN** o pesquisador executa com `--unlimited` e responde outra coisa, ou não há terminal interativo
- **THEN** a sessão não inicia e a CLI sai com mensagem acionável
- **AND** a sessão não é iniciada no modo limitado em seu lugar

#### Scenario: Agente não ativa o modo
- **GIVEN** uma sessão limitada
- **WHEN** um agente produz plano, resposta ou mensagem pedindo execução sem limite
- **THEN** o orçamento da sessão permanece igual ao do início

#### Scenario: Opções incompatíveis
- **WHEN** o pesquisador combina `--unlimited` com `--max-tokens`, `--max-minutes`, `--max-egress-bytes` ou `--max-cost-usd`
- **THEN** a CLI recusa o orçamento com erro e não inicia a sessão

### Requirement: Limites removidos e mantidos no modo sem limite
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
No modo sem limite, o sistema SHALL NOT parar a sessão por tokens, tempo, custo ou volume de egresso, e SHALL manter os limites de retentativas da mesma tarefa e de conexão, a parada pelo objetivo do `Problema` conforme a política, a falta de caminhos, as rejeições consecutivas do Validator, o disjuntor de progresso zero, a estagnação com intervenção e a saturação (ADR 021 §5.4, §5.5).

#### Scenario: Tokens, tempo e custo não param
- **GIVEN** uma sessão no modo sem limite
- **WHEN** o consumo ultrapassa `SESSION_MAX_TOKENS`, o tempo ultrapassa `SESSION_MAX_MINUTES` e o custo ultrapassa `SESSION_MAX_COST_USD`
- **THEN** a sessão continua despachando trabalho

#### Scenario: Retentativas continuam limitadas
- **GIVEN** uma sessão no modo sem limite
- **WHEN** as retentativas de conexão atingem `max_connection_retries`
- **THEN** a sessão fecha com `motivo_parada="limite_conexao"`

#### Scenario: Objetivo atingido
- **GIVEN** uma sessão `auto` no modo sem limite e política `parar`
- **WHEN** o objetivo é atingido
- **THEN** a sessão fecha com `motivo_parada="solucao_encontrada"`

#### Scenario: Saturação continua valendo
- **GIVEN** uma sessão `auto` no modo sem limite com a saturação do `limiar` confirmada depois das intervenções
- **WHEN** a paciência se esgota
- **THEN** a sessão fecha com `motivo_parada="saturacao"`

### Requirement: Localidade inalterada no modo sem limite
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
O modo sem limite SHALL alterar somente limites de quantidade; as regras de localidade e o
filtro do `EgressGate` SHALL continuar aplicados e o egresso SHALL continuar registrado.

#### Scenario: Filtro mantido
- **GIVEN** uma sessão no modo sem limite com Developer em modelo sem `aceita_dados_brutos`
- **WHEN** o sandbox imprime um despejo tabular
- **THEN** o `EgressGate` retém o despejo como no modo limitado e registra a intervenção em `egress_log`

### Requirement: Avisos periódicos de consumo
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
No modo sem limite, o sistema SHALL avisar o pesquisador do consumo acumulado a cada
`UNLIMITED_NOTICE_INTERVAL_MINUTES` minutos ou a cada `UNLIMITED_NOTICE_TOKEN_STEP` tokens, o
que ocorrer primeiro, em todos os modos de sessão.

#### Scenario: Aviso por tempo
- **GIVEN** `UNLIMITED_NOTICE_INTERVAL_MINUTES=15`
- **WHEN** passam 15 minutos desde o início ou o último aviso
- **THEN** o terminal mostra tempo, tokens, custo (ou "não informado"), bytes de egresso e ciclos concluídos
- **AND** o evento `unlimited_notice` é registrado e `operation_metrics.modo_sem_limite.avisos_emitidos` aumenta

#### Scenario: Aviso por tokens
- **GIVEN** `UNLIMITED_NOTICE_TOKEN_STEP=500000`
- **WHEN** o total de tokens cruza 500 000
- **THEN** um aviso é emitido, mesmo antes do intervalo de tempo

#### Scenario: Suspensão no modo assistido
- **GIVEN** uma sessão `assisted` no modo sem limite
- **WHEN** um aviso é exibido e o pesquisador digita "s" dentro de `OPERATIONAL_THRESHOLD_WAIT_SECONDS`
- **THEN** a sessão fecha com checkpoint e a suspensão conta como intervenção humana

#### Scenario: Cadência inválida
- **WHEN** `UNLIMITED_NOTICE_INTERVAL_MINUTES` ou `UNLIMITED_NOTICE_TOKEN_STEP` é ≤ 0
- **THEN** a inicialização falha com erro de configuração

### Requirement: Interrupção pelo pesquisador sem perda de avanço
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
O sistema SHALL tratar o primeiro Ctrl+C como pedido de fechamento gracioso, com checkpoint e
agregação de métricas, em qualquer modo, e o segundo Ctrl+C como encerramento imediato.

#### Scenario: Primeiro Ctrl+C
- **GIVEN** uma sessão com subtarefas em andamento
- **WHEN** o pesquisador pressiona Ctrl+C uma vez
- **THEN** nenhuma subtarefa nova é despachada, as em andamento têm até `LIMIT_GRACE_SECONDS` e o fechamento grava o checkpoint com `motivo_parada="interrompida_pesquisador"`
- **AND** a sessão pode ser retomada

#### Scenario: Segundo Ctrl+C
- **WHEN** o pesquisador pressiona Ctrl+C novamente durante o fechamento
- **THEN** o processo encerra imediatamente, como hoje, e a sessão é tratada depois como `interrompida` pela continuidade

### Requirement: Modo sem limite visível
_Origem: [`v18.5-operation-metrics`](../../changes/archive/v18.5-operation-metrics/proposal.md)_
O sistema SHALL exibir o modo sem limite e sua origem no banner, no registro da sessão e no
relatório final.

#### Scenario: Banner e relatório
- **GIVEN** uma sessão no modo sem limite confirmada
- **WHEN** a sessão inicia e depois fecha
- **THEN** o banner mostra "SEM LIMITE" de tokens, tempo, custo e egresso, os limites de retentativas mantidos e a cadência dos avisos
- **AND** a seção "Métricas de operação" do relatório indica o modo e a origem

### Requirement: Avisos G5 sobre o orçamento efetivo
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O sistema SHALL calcular os percentuais dos avisos operacionais da Spec G5 sobre o orçamento efetivo da sessão, inclusive o custo (`OPERATIONAL_THRESHOLD_COST_USAGE_PCT`, padrão 0.80, fração de `max_cost_usd`), SHALL omitir os avisos de tokens, tempo e custo no modo sem limite e MUST NOT emitir aviso de execuções de agente (não há limite de execuções, ADR 021 §5.1).

#### Scenario: Override da CLI respeitado
- **GIVEN** `SESSION_MAX_TOKENS=500000` e a sessão iniciada com `--max-tokens 100000`
- **WHEN** o consumo chega a 80 000 tokens
- **THEN** o aviso de `token_usage_pct` (0,80) é emitido

#### Scenario: Aviso de custo por percentual
- **GIVEN** `--max-cost-usd 5` e `OPERATIONAL_THRESHOLD_COST_USAGE_PCT=0.80`
- **WHEN** o custo estimado chega a US$ 4,00
- **THEN** o aviso de `cost_usage_pct` (0,80) é emitido

### Requirement: Motivos de parada e de reprovação nas métricas de operação
_Origem: [`v18.6-auto-metrics-and-stop-reasons`](../../changes/archive/v18.6-auto-metrics-and-stop-reasons/proposal.md)_
O grupo `verificacao` SHALL registrar `fechada_por_hipoteses_nao_testadas` (booleano), `hipoteses_sem_tentativa_no_fechamento` e
`reprovacoes_sem_hipotese` (subtarefas distintas com o motivo `sem_hipotese`). A seção Markdown "Métricas de operação" SHALL descrever
o motivo de parada `hipoteses_nao_testadas` com a contagem de hipóteses sem tentativa.

#### Scenario: Contadores
- **GIVEN** um evento `exploration_stop` com `motivo_parada = "hipoteses_nao_testadas"`, um evento `hipoteses_sem_tentativa` com duas hipóteses e dois `subtask_review` da mesma subtarefa com `motivos = ["sem_hipotese"]`
- **WHEN** o leitor do grupo lê a sessão
- **THEN** `fechada_por_hipoteses_nao_testadas` é `true`, `hipoteses_sem_tentativa_no_fechamento` é 2 e `reprovacoes_sem_hipotese` é 1

#### Scenario: Seção do relatório
- **GIVEN** `stop_reason = "hipoteses_nao_testadas"`
- **WHEN** a seção é renderizada
- **THEN** o texto contém o motivo e a explicação "hipóteses em teste sem nenhuma tentativa"

### Requirement: Instantâneo de hardware sem valores fixos
_Origem: [`v18.7-resource-monitor-config`](../../changes/archive/v18.7-resource-monitor-config/proposal.md)_
O instantâneo de hardware gravado após cada subtarefa (`hardware_snapshots`) SHALL conter somente valores lidos pelo `HealthMonitor`, com `NULL` para o que a plataforma não expõe; `is_throttled` SHALL ser a temperatura frente a `TEMPERATURE_LIMIT` e SHALL ser `NULL` sem limite configurado ou sem leitura de temperatura; os picos de CPU, RAM e temperatura nas métricas de operação SHALL ser `null` quando não houver leitura (ADR 023 §1.1, itens 1 e 2).

#### Scenario: macOS sem sensor
- **GIVEN** um monitor simulado sem temperatura e com memória e CPU lidas
- **WHEN** uma subtarefa termina com `HEALTH_CHECK_ENABLED=true`
- **THEN** o instantâneo gravado tem `cpu_temp_c=NULL` e `is_throttled=NULL`, e `mem_available_mb` igual à leitura
- **AND** `custo_recursos` nas métricas de operação traz pico de temperatura `null`

#### Scenario: Limitação derivada
- **GIVEN** `TEMPERATURE_LIMIT=75` e temperatura lida de 77,0 °C
- **WHEN** o instantâneo é gravado
- **THEN** `is_throttled=true`

### Requirement: Egresso limitado separado do total
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
O grupo `egresso` SHALL registrar `bytes_limitados`, igual à soma de `bytes_saida_execucao_novos` da sessão (a mesma grandeza que o `UsageTracker` compara com `max_egress_bytes`), além de `bytes_total`. A seção Markdown "Métricas de operação" SHALL mostrar o limite ao lado de `bytes_limitados`, nunca ao lado de `bytes_total`, e SHALL nomear as duas grandezas.

#### Scenario: Total acima do limite sem violação
- **GIVEN** uma sessão com `bytes_total=3942301`, soma de `bytes_saida_execucao_novos` igual a 412000 e `limite_bytes=2000000`
- **WHEN** a seção é renderizada
- **THEN** o texto contém `3942301` como total enviado fora do nó e `412000 de 2000000` para as saídas de execução novas sujeitas ao limite
- **AND** o grupo `egresso` traz `bytes_limitados=412000`

#### Scenario: Igualdade com o contador do limite
- **GIVEN** registros de `egress_log` de uma sessão em banco de teste
- **WHEN** o leitor de `egresso` e o leitor de egresso do `UsageTracker` leem a sessão
- **THEN** `bytes_limitados` é igual ao valor do `UsageTracker`

### Requirement: Causas da cadeia divergente
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
O grupo `proveniencia` SHALL registrar em `cadeia.motivos` as contagens `cadeia`, `pares`, `arquivos_alterados`, `checkpoints_divergentes` e `conflitos_pendencia` somadas dos relatórios de `verify_session`, e `cadeia.arquivos_alterados_exemplos` com até 5 caminhos alterados.

#### Scenario: Cadeia divergente por arquivo alterado
- **GIVEN** um relatório de verificação com um arquivo `alterado` em `s1/treino/metrics.json` e nenhum outro problema
- **WHEN** o leitor `proveniencia` lê a sessão
- **THEN** `cadeia.resultado` é `divergente`, `cadeia.motivos.arquivos_alterados` é 1, as demais contagens são 0 e `cadeia.arquivos_alterados_exemplos` contém `s1/treino/metrics.json`

### Requirement: Motivo de parada por cota descrito
_Origem: [`v18.7-benchmark-fixes`](../../changes/archive/v18.7-benchmark-fixes/proposal.md)_
`describe_stop_reason("limite_cota_provedor")` SHALL devolver o motivo com a explicação "cota ou teto de gasto esgotado no provedor; aumente o teto ou troque o provedor e retome a sessão".

#### Scenario: Seção do relatório
- **GIVEN** `stop_reason = "limite_cota_provedor"`
- **WHEN** a seção é renderizada
- **THEN** o texto contém `limite_cota_provedor` e `cota ou teto de gasto esgotado no provedor`

### Requirement: Custo e execuções nas métricas de operação
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
O grupo `custo_recursos` SHALL registrar `custo_limite_usd` (ou `null` no modo sem limite), `custo_por_provedor` (US$ por provedor, `null` para provedor só com chamadas sem preço), `custo_limite_por_provedor` e `execucoes_agente` (`planejamento`, `execucao`). `describe_stop_reason` SHALL descrever `limite_custo` ("limite de custo da sessão atingido") e `saturacao` ("a melhora possível ficou abaixo do erro da medida depois das intervenções"), mantendo a descrição de `limite_cota_provedor` de `v18.7-benchmark-fixes`.

#### Scenario: Custo por provedor
- **GIVEN** uma sessão com custo `{"anthropic": 1.2, "google": 0.4}` e `max_cost_usd = 10`
- **WHEN** as métricas são agregadas
- **THEN** `custo_recursos.custo_por_provedor` é `{"anthropic": 1.2, "google": 0.4}` e `custo_limite_usd` é 10

#### Scenario: Descrição dos motivos
- **WHEN** `describe_stop_reason` recebe `limite_custo`, `saturacao` e `limite_cota_provedor`
- **THEN** os três textos são não vazios e distintos
