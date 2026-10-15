# Delta: researcher-consult

## ADDED Requirements

### Requirement: Consulta ao Researcher durante a execução, só leitura
O terminal SHALL permitir que o pesquisador pergunte ao Researcher sobre o projeto, as hipóteses e os resultados enquanto a sessão roda (`perguntar <texto>`, `? <texto>` ou texto livre sem comando). A consulta SHALL rodar num processo filho criado pelo terminal como o processo da sessão (`stdin` fechado e ambiente filtrado, sem `TERMINAL_DATABASE_URL_FILE`, `TERMINAL_DATABASE_URL`, `PGPASSWORD`, `PGPASSFILE`, `PGSERVICEFILE` nem os nomes de `SESSION_ENV_DENYLIST`), que devolve ao terminal só o JSON da resposta; o processo do terminal MUST NOT executar o modelo nem as ferramentas da consulta, e a gravação da orientação confirmada SHALL continuar no terminal. No processo filho, a consulta SHALL ser só leitura: grafo pelo papel `knowledge_reader` em transação somente leitura, banco relacional com `default_transaction_read_only=on` e Qdrant por invólucro sem escrita; as ferramentas do modelo SHALL ser só `quick_search` e `web_reader`, dentro de `RESEARCHER_CONSULT_MAX_SEARCHES` e `RESEARCHER_CONSULT_MAX_READS`; o contexto (até `TERMINAL_CONSULT_CONTEXT_MAX_CHARS`, padrão 12000) SHALL ser delimitado como dado e passar pelo `EgressGate` e pela política de dados da sessão consultada; o consumo SHALL ser registrado com o `execution_id` da sessão consultada e origem `consulta_terminal`, limitado por `TERMINAL_CONSULT_MAX_TOKENS` (padrão 20000) por pergunta, e SHALL contar no orçamento dessa sessão (uso, `limite_tokens` e `limite_custo`), identificável como `consulta` nas métricas de operação (decisão do pesquisador, 2026-10-15; ADR 023 §3 e §7; ADR 019; ADR 022).

#### Scenario: Resposta sobre o projeto
- **GIVEN** a sessão `iris-01` em execução com as hipóteses `h1` (refutada) e `h2` (em teste) e um provedor simulado chamado pela função `ask` (teste de unidade, sem processo filho)
- **WHEN** o pesquisador digita `perguntar quais hipóteses já foram refutadas?`
- **THEN** o prompt enviado ao provedor contém `h1` e `h2` dentro do bloco de contexto delimitado
- **AND** a resposta do provedor é exibida no terminal

#### Scenario: Consulta em processo filho sem a credencial
- **GIVEN** o REPL com `TERMINAL_DATABASE_URL_FILE` e `PGPASSWORD` definidos e um provedor simulado que, ao ser chamado, grava `os.getpid()` e as chaves de `os.environ` do processo
- **WHEN** o pesquisador digita `perguntar quais hipóteses já foram refutadas?`
- **THEN** o PID gravado é diferente do PID do REPL, as chaves gravadas não contêm `TERMINAL_DATABASE_URL_FILE` nem `PGPASSWORD` e `load_terminal_database_url()` levanta erro no processo filho
- **AND** a resposta é exibida no REPL

#### Scenario: Nenhuma escrita possível
- **GIVEN** a consulta em curso
- **WHEN** o código da consulta tenta gravar no banco relacional, no grafo ou no Qdrant
- **THEN** a gravação levanta erro (transação somente leitura, papel `knowledge_reader` ou invólucro) e nada muda

#### Scenario: Ferramentas expostas
- **WHEN** a consulta do terminal é montada
- **THEN** as ferramentas expostas ao modelo são exatamente `quick_search` e `web_reader`

#### Scenario: Localidade do projeto
- **GIVEN** uma sessão com política `self_hosted_only` e o papel `researcher` resolvido só para provedor de nuvem
- **WHEN** o pesquisador pergunta
- **THEN** a consulta é recusada com o motivo de política e nenhum provedor é chamado

#### Scenario: Consumo registrado
- **WHEN** uma consulta termina com 1500 tokens simulados
- **THEN** `token_usage` tem um registro com o `execution_id` da sessão e origem `consulta_terminal`

#### Scenario: Consumo da consulta conta no orçamento
- **GIVEN** a sessão `iris-01` com `max_tokens = 10000`, consumo de 9000 tokens e um leitor de consumo que soma `token_usage` pelo `execution_id`
- **WHEN** uma consulta termina com 1500 tokens simulados
- **THEN** o uso da sessão passa a 10500, `LimitStatus.tokens_exhausted` é verdadeiro no próximo ponto de verificação e a sessão fecha com `limite_tokens`
- **AND** as métricas de operação mostram os 1500 tokens como `consulta`

### Requirement: Texto livre é conversa e `nova-pesquisa` inicia a pesquisa
O REPL SHALL tratar o texto livre sem comando como conversa com o Researcher, equivalente a `perguntar`, e MUST NOT iniciar pesquisa por ele; iniciar uma pesquisa SHALL exigir o comando explícito `nova-pesquisa <tarefa>`, com a verificação de memória de `v18.7-background-sessions`. Com outra pesquisa em execução, `nova-pesquisa` SHALL perguntar "Iniciar outra? [s/N]" antes da verificação de memória. Sem pesquisa para consultar, o texto livre SHALL ser recusado com a indicação de `nova-pesquisa <tarefa>`, sem chamada ao modelo (decisão do pesquisador, 2026-10-15; ADR 023 §3).

#### Scenario: Texto livre é conversa
- **GIVEN** a sessão `iris-01` em execução e a entrada simulada "quais hipóteses foram refutadas?"
- **WHEN** o REPL processa a linha
- **THEN** a consulta ao Researcher é chamada com esse texto e nenhum processo de sessão novo é criado

#### Scenario: Nova pesquisa por comando
- **GIVEN** nenhuma pesquisa em execução e a entrada simulada "nova treinar um classificador no iris"
- **WHEN** o REPL processa a linha
- **THEN** o processo da sessão é criado com a tarefa "treinar um classificador no iris"

#### Scenario: Nova com outra em execução
- **GIVEN** a sessão `iris-01` em execução e a entrada simulada "nova outra tarefa" seguida de "n"
- **WHEN** o REPL processa a linha
- **THEN** o terminal pergunta "Já há pesquisa em execução (iris-01). Iniciar outra? [s/N]" e, com "n", nenhum processo é criado

#### Scenario: Texto livre sem pesquisa
- **GIVEN** nenhuma pesquisa para consultar
- **WHEN** o pesquisador digita texto livre
- **THEN** o terminal recusa, sugere `nova-pesquisa <tarefa>` e nenhum provedor é chamado

### Requirement: Orientação vinda da conversa só com confirmação
Quando a resposta da consulta trouxer `orientacao_sugerida`, o terminal SHALL propor transformá-la em mensagem à sessão e SHALL gravá-la pela caixa de entrada somente se o pesquisador confirmar; sem confirmação, nada SHALL ser gravado (ADR 023 §3 e §5).

#### Scenario: Pesquisador confirma
- **GIVEN** o provedor simulado devolve `{"resposta": "...", "orientacao_sugerida": "priorize modelos lineares"}` e a entrada simulada é "s"
- **WHEN** a consulta termina
- **THEN** existe uma mensagem `orientacao` na caixa de entrada de `iris-01` com o texto "priorize modelos lineares"

#### Scenario: Pesquisador recusa
- **GIVEN** a mesma resposta e a entrada simulada "n"
- **WHEN** a consulta termina
- **THEN** nenhuma mensagem é gravada
