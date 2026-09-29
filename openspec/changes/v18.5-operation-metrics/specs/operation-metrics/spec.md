# Delta: operation-metrics

## ADDED Requirements

### Requirement: Métricas de operação registradas por sessão
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
Fora do modo sem limite, o sistema SHALL tratar o volume de egresso de saídas de execução por
sessão como condição de parada graciosa, com `motivo_parada="limite_egresso"`.

#### Scenario: Limite de egresso atingido
- **GIVEN** `max_egress_bytes` igual a 1 000 000 e sessão sem modo sem limite
- **WHEN** o volume registrado pelo `EgressGate` atinge 1 000 000 bytes
- **THEN** nenhuma nova chamada externa é despachada, as em andamento são aguardadas e o fechamento grava o checkpoint com `motivo_parada="limite_egresso"`
- **AND** a sessão pode ser retomada

### Requirement: Modo sem limite explícito
O sistema SHALL oferecer o modo sem limite apenas por opção explícita do pesquisador, por
sessão (`--unlimited`) ou por projeto, e SHALL exigir confirmação interativa no início de cada
execução. O modo SHALL NOT ser ativado por padrão, por variável de ambiente, por configuração
ou por qualquer agente.

#### Scenario: Ativação por sessão confirmada
- **WHEN** o pesquisador executa `geminiclaw --unlimited "<prompt>"` e digita "sem limite" na confirmação
- **THEN** a sessão inicia com `UsageBudget(unlimited=True)` e `payload["budget"]` registra `unlimited=true`, a origem `cli` e o instante da confirmação

#### Scenario: Confirmação ausente
- **WHEN** o pesquisador executa com `--unlimited` e responde outra coisa, ou não há terminal interativo
- **THEN** a sessão não inicia e a CLI sai com mensagem acionável
- **AND** a sessão não é iniciada no modo limitado em seu lugar

#### Scenario: Ativação por projeto
- **GIVEN** o projeto marcado com `geminiclaw project unlimited <id> --on`
- **WHEN** uma nova execução do projeto começa
- **THEN** a confirmação é pedida e, confirmada, a sessão registra a origem `projeto`

#### Scenario: Retomada não herda o modo
- **GIVEN** uma sessão anterior no modo sem limite, em projeto sem a marcação
- **WHEN** o pesquisador executa `geminiclaw continue --project <id>` sem `--unlimited`
- **THEN** a nova sessão usa o orçamento limitado de `config`

#### Scenario: Agente não ativa o modo
- **GIVEN** uma sessão limitada
- **WHEN** um agente produz plano, resposta ou mensagem IPC pedindo execução sem limite
- **THEN** o orçamento da sessão permanece igual ao do início

#### Scenario: Opções incompatíveis
- **WHEN** o pesquisador combina `--unlimited` com `--max-tokens`, `--max-minutes` ou `--max-egress-bytes`
- **THEN** a CLI recusa o orçamento com erro e não inicia a sessão

### Requirement: Limites removidos e mantidos no modo sem limite
No modo sem limite, o sistema SHALL NOT parar a sessão por tokens, tempo, custo ou volume de
egresso, e SHALL manter os limites de retentativas da mesma tarefa e de conexão, os
critérios de parada da V18, as rejeições consecutivas do Validator e o circuit breaker de
progresso zero.

#### Scenario: Tokens e tempo não param
- **GIVEN** uma sessão no modo sem limite
- **WHEN** o consumo ultrapassa `SESSION_MAX_TOKENS` e o tempo ultrapassa `SESSION_MAX_MINUTES`
- **THEN** a sessão continua despachando trabalho

#### Scenario: Retentativas continuam limitadas
- **GIVEN** uma sessão no modo sem limite
- **WHEN** as retentativas de conexão atingem `max_connection_retries`
- **THEN** a sessão fecha com `motivo_parada="limite_conexao"`

#### Scenario: Retentativas da mesma tarefa
- **GIVEN** uma sessão no modo sem limite
- **WHEN** uma tarefa atinge `max_task_retries`
- **THEN** a tarefa é abandonada, como no modo limitado

#### Scenario: Solução encontrada
- **GIVEN** uma sessão `auto` no modo sem limite
- **WHEN** o critério `solucao_encontrada` é satisfeito
- **THEN** a sessão fecha com `motivo_parada="solucao_encontrada"`

#### Scenario: Sem caminhos promissores
- **GIVEN** uma sessão no modo sem limite
- **WHEN** não há hipótese nova, aprovada pendente nem sugestão do Curator
- **THEN** a sessão fecha com `motivo_parada="sem_caminhos_promissores"`

### Requirement: Localidade inalterada no modo sem limite
O modo sem limite SHALL alterar somente limites de quantidade; as regras de localidade e o
filtro do `EgressGate` SHALL continuar aplicados e o egresso SHALL continuar registrado.

#### Scenario: Filtro mantido
- **GIVEN** uma sessão no modo sem limite com Developer em modelo sem `aceita_dados_brutos`
- **WHEN** o sandbox imprime um despejo tabular
- **THEN** o `EgressGate` retém o despejo como no modo limitado e registra a intervenção em `egress_log`

### Requirement: Avisos periódicos de consumo
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
O sistema SHALL exibir o modo sem limite e sua origem no banner, no registro da sessão e no
relatório final.

#### Scenario: Banner e relatório
- **GIVEN** uma sessão no modo sem limite confirmada
- **WHEN** a sessão inicia e depois fecha
- **THEN** o banner mostra "SEM LIMITE" de tokens, tempo, custo e egresso, os limites de retentativas mantidos e a cadência dos avisos
- **AND** a seção "Métricas de operação" do relatório indica o modo e a origem

### Requirement: Avisos G5 sobre o orçamento efetivo
O sistema SHALL calcular os percentuais dos avisos operacionais da Spec G5 sobre o orçamento
efetivo da sessão e SHALL omitir os avisos de tokens, tempo e custo no modo sem limite.

#### Scenario: Override da CLI respeitado
- **GIVEN** `SESSION_MAX_TOKENS=500000` e a sessão iniciada com `--max-tokens 100000`
- **WHEN** o consumo chega a 80 000 tokens
- **THEN** o aviso de `token_usage_pct` (0,80) é emitido
