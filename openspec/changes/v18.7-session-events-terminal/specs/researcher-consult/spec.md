# Delta: researcher-consult

## ADDED Requirements

### Requirement: Consulta ao Researcher durante a execução, só leitura
O terminal SHALL permitir que o pesquisador pergunte ao Researcher sobre o projeto, as hipóteses e os resultados enquanto a sessão roda (`perguntar <texto>` ou `? <texto>`). A consulta SHALL rodar num processo filho criado pelo terminal como o processo da sessão (`stdin` fechado e ambiente filtrado, sem `TERMINAL_DATABASE_URL_FILE`, `TERMINAL_DATABASE_URL`, `PGPASSWORD`, `PGPASSFILE`, `PGSERVICEFILE` nem os nomes de `SESSION_ENV_DENYLIST`), que devolve ao terminal só o JSON da resposta; o processo do terminal MUST NOT executar o modelo nem as ferramentas da consulta, e a gravação da orientação confirmada SHALL continuar no terminal. No processo filho, a consulta SHALL ser só leitura: grafo pelo papel `knowledge_reader` em transação somente leitura, banco relacional com `default_transaction_read_only=on` e Qdrant por invólucro sem escrita; as ferramentas do modelo SHALL ser só `quick_search` e `web_reader`, dentro de `RESEARCHER_CONSULT_MAX_SEARCHES` e `RESEARCHER_CONSULT_MAX_READS`; o contexto (até `TERMINAL_CONSULT_CONTEXT_MAX_CHARS`, padrão 12000) SHALL ser delimitado como dado e passar pelo `EgressGate` e pela política de dados da sessão consultada; o consumo SHALL ser registrado com origem `consulta_terminal` e limitado por `TERMINAL_CONSULT_MAX_TOKENS` (padrão 20000) por pergunta (ADR 023 §3 e §7; ADR 019; ADR 022).

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
