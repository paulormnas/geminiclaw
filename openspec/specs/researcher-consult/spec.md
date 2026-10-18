# Especificação: researcher-consult

Verdade atual consolidada a partir das mudanças arquivadas (2026-10-13). Cada requisito indica a
mudança que o definiu por último; os cenários vêm do delta original, em GIVEN/WHEN/THEN.

**Mudanças de origem:** [`v18-researcher-consult`](../../changes/archive/v18-researcher-consult/proposal.md), [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md), [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)

## Requirements

### Requirement: Researcher responde nos modos autônomos
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
O sistema SHALL, nos modos `semi` e `auto`, encaminhar cada chamada de `ask_researcher` ao Researcher consultor e devolver ao agente a resposta dele, e SHALL, no modo `assisted`, registrar a pergunta no gate persistente como `responder_pergunta_agente`, esperar a resposta do pesquisador por até `GATE_ASK_WAIT_SECONDS` (padrão 120) e, sem resposta, devolver ao agente a mensagem de pendência; a resposta posterior SHALL ir ao Researcher no replanejamento (ADR 012 §8).

#### Scenario: Modo auto
- **GIVEN** uma sessão `auto` e o provedor do Researcher simulado respondendo `{"resposta": "Use stratify=y", "confianca": "alta", "fontes": [], "suposicoes": []}`
- **WHEN** o Developer chama `ask_researcher` com a pergunta "Devo estratificar o split?"
- **THEN** o Developer recebe um texto que começa com `[Resposta do Researcher (consultor), confiança alta]` e contém "Use stratify=y"
- **AND** nada é lido do terminal

#### Scenario: Modo assisted respondido a tempo
- **GIVEN** uma sessão `assisted`
- **WHEN** um agente chama `ask_researcher` e o terminal responde "use 5 dobras" pelo gate em 1 s
- **THEN** o agente recebe "use 5 dobras", a interação tem `respondido_por="pesquisador"` e o consultor não é chamado

#### Scenario: Modo assisted sem resposta
- **GIVEN** `GATE_ASK_WAIT_SECONDS=1` em teste
- **WHEN** um agente chama `ask_researcher` e ninguém responde
- **THEN** o agente recebe a mensagem de pendência, a interação tem `respondido_por="pendente_pesquisador"` e o pedido continua `pendente`

#### Scenario: Consultor desligado
- **GIVEN** `RESEARCHER_CONSULT_ENABLED=false` numa sessão `semi`
- **WHEN** um agente chama `ask_researcher`
- **THEN** o agente recebe a suposição documentada atual e a interação tem `respondido_por="suposicao"` e `motivo_fallback="desligado"`

### Requirement: Ferramentas restritas do consultor
_Origem: [`v18-researcher-consult`](../../changes/archive/v18-researcher-consult/proposal.md)_
O consultor SHALL ter acesso somente a `quick_search` e `web_reader`, com no máximo
`RESEARCHER_CONSULT_MAX_SEARCHES` buscas e `RESEARCHER_CONSULT_MAX_READS` leituras por consulta,
e MUST NOT ter acesso a `ask_researcher`, ao sandbox de código, à escrita de arquivos ou à
escrita no grafo.

#### Scenario: Lista de ferramentas
- **WHEN** o consultor é montado
- **THEN** as ferramentas expostas ao modelo são exatamente `quick_search` e `web_reader`

#### Scenario: Excesso de buscas
- **GIVEN** `RESEARCHER_CONSULT_MAX_SEARCHES=3` e um modelo simulado que pede 5 buscas
- **WHEN** a consulta roda
- **THEN** só 3 buscas são executadas e as demais recebem erro de limite

#### Scenario: Web desligada
- **GIVEN** `RESEARCHER_CONSULT_WEB_ENABLED=false`
- **WHEN** o consultor é montado
- **THEN** nenhuma ferramenta é exposta e a resposta vem só do modelo

### Requirement: Guarda de consulta antes do buscador
_Origem: [`v18-researcher-consult`](../../changes/archive/v18-researcher-consult/proposal.md)_
O sistema SHALL verificar toda consulta e toda URL do consultor antes de saírem do nó e SHALL
recusar, sem enviar, as que contenham número com casas decimais, sequência de 4 ou mais dígitos
que não seja ano, nome de arquivo da sessão, mais de `RESEARCHER_CONSULT_QUERY_MAX_CHARS`
caracteres ou mais de 3 linhas, registrando o motivo (ADR 010 item 9, ADR 019 §3).

#### Scenario: Valor de medição
- **WHEN** o consultor pede a busca "acurácia 0,953 iris svm"
- **THEN** a busca não é enviada ao backend e a recusa tem motivo `numero_decimal`

#### Scenario: Nome de arquivo do projeto
- **GIVEN** `input_snapshot/` contém `medicoes_lote7.csv`
- **WHEN** o consultor pede a busca "medicoes_lote7 formato"
- **THEN** a busca é recusada com motivo `nome_de_arquivo`

#### Scenario: Ano permitido
- **WHEN** o consultor pede a busca "scikit-learn train_test_split stratify 2026"
- **THEN** a busca é enviada

#### Scenario: URL com dado
- **WHEN** o consultor pede `web_reader` para `https://exemplo.org/q?v=12.75`
- **THEN** a leitura é recusada com motivo `numero_decimal`

### Requirement: Decisões reservadas ao pesquisador
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
O consultor MUST NOT responder perguntas que peçam aprovar `Oportunidade`, confirmar `Problema`, aprovar termo de vocabulário, autorizar escrita em instrumento, ativar o modo sem limite, aprovar hipótese, decidir o que fazer ao atingir o objetivo, responder pergunta de agente no `assisted`, decidir a continuidade da exploração ou restringir uma direção (`DECISOES_RESERVADAS`: `aprovar_oportunidade`, `confirmar_problema`, `aprovar_termo_vocabulario`, `autorizar_escrita_instrumento`, `ativar_modo_sem_limite`, `aprovar_hipotese`, `decidir_objetivo_atingido`, `responder_pergunta_agente`, `decidir_continuidade`, `restringir_direcao`). O sistema SHALL registrar essas perguntas como `pendente_pesquisador`, criar o pedido no gate persistente e informar ao agente que a decisão é do pesquisador. Esta lista é a fonte única do catálogo do gate; o efeito de `restringir_direcao` (nó `Restricao`) é de `v18.7-exploration-limits`, e `ativar_adendo_regimento` é acrescentada por `v18.7-agent-system-prompts`.

#### Scenario: Aprovação de oportunidade em modo auto
- **GIVEN** uma sessão `auto`
- **WHEN** um agente chama `ask_researcher` com `decisao_reservada="aprovar_oportunidade"`
- **THEN** o consultor não é chamado
- **AND** a interação tem `respondido_por="pendente_pesquisador"`, existe um pedido `aprovar_oportunidade` pendente e o agente recebe a mensagem de decisão reservada

#### Scenario: Classificação pelo consultor
- **GIVEN** o consultor simulado devolve `{"reservada": true}` para uma pergunta sem `decisao_reservada`
- **WHEN** a consulta termina
- **THEN** a interação é registrada como `pendente_pesquisador`

#### Scenario: Decisão nova é reservada
- **WHEN** um agente chama `ask_researcher` com `decisao_reservada="aprovar_hipotese"` numa sessão `semi`
- **THEN** o consultor não é chamado e a interação é `pendente_pesquisador`

### Requirement: Registro auditável das consultas
_Origem: [`v18-researcher-consult`](../../changes/archive/v18-researcher-consult/proposal.md)_
O sistema SHALL registrar cada interação de `ask_researcher` em
`payload["researcher_interactions"]` com `respondido_por`, o agente e a subtarefa que
perguntaram, a pergunta, o motivo, a resposta, as fontes, as buscas realizadas, as recusas da
guarda, o modelo, os tokens, a duração e `motivo_fallback`, e SHALL emitir o evento de
telemetria `researcher_consult` (ADR 012 §8).

#### Scenario: Consulta com busca
- **GIVEN** uma consulta em que o consultor fez 2 buscas e leu 1 página
- **WHEN** a consulta termina
- **THEN** a interação registrada tem `respondido_por="researcher"`, 2 itens em `buscas_realizadas` e 1 em `leituras`
- **AND** um evento `researcher_consult` foi gravado sem o texto da página lida

#### Scenario: Pergunta repetida
- **GIVEN** uma pergunta já respondida pelo consultor nesta sessão
- **WHEN** uma pergunta com similaridade acima de `ASK_RESEARCHER_DEDUP_SIMILARITY` é feita
- **THEN** a resposta anterior é reutilizada e o consultor não é chamado

### Requirement: Consultas dentro dos limites de uso
_Origem: [`v18-researcher-consult`](../../changes/archive/v18-researcher-consult/proposal.md)_
O sistema SHALL contar os tokens do consultor no orçamento da sessão, SHALL limitar as
consultas a `RESEARCHER_CONSULT_MAX_PER_SESSION`, e SHALL voltar à suposição documentada, com
`motivo_fallback` registrado, quando o limite, o orçamento, o timeout ou um erro impedirem a
consulta (ADR 012 §5).

#### Scenario: Tokens contados
- **GIVEN** o consultor simulado consome 1200 tokens
- **WHEN** o `UsageTracker` é consultado depois da consulta
- **THEN** o total de tokens da sessão aumentou em 1200

#### Scenario: Limite por sessão
- **GIVEN** `RESEARCHER_CONSULT_MAX_PER_SESSION=1` e uma consulta já feita
- **WHEN** outro agente chama `ask_researcher` com uma pergunta diferente
- **THEN** o agente recebe a suposição documentada e a interação tem `motivo_fallback="limite_consultas"`

#### Scenario: Orçamento em fechamento
- **GIVEN** o `UsageTracker` indica fechamento por tokens
- **WHEN** um agente chama `ask_researcher`
- **THEN** o consultor não é chamado e `motivo_fallback="orcamento"`

#### Scenario: Timeout
- **GIVEN** `RESEARCHER_CONSULT_TIMEOUT_SECONDS=1` e um consultor simulado que demora 5 s
- **WHEN** a consulta roda
- **THEN** o agente recebe a suposição documentada e `motivo_fallback="timeout"`

### Requirement: ask_researcher não bloqueante em semi/auto (Spec G5)
_Origem: [`v18-researcher-consult`](../../changes/archive/v18-researcher-consult/proposal.md)_
Nos modos `semi` e `auto`, `ask_researcher` SHALL continuar sem bloquear à espera de um
humano, mas SHALL devolver a resposta do Researcher consultor quando ele estiver habilitado e
dentro dos limites; a suposição documentada passa a ser o comportamento de fallback, não o
padrão.

#### Scenario: Nenhuma leitura de terminal em semi
- **GIVEN** uma sessão `semi` com duas perguntas de agentes
- **WHEN** as duas perguntas são feitas
- **THEN** nenhuma leitura de `stdin` ocorre
- **AND** as duas interações têm `respondido_por` igual a `researcher` ou `suposicao`

### Requirement: Gate persistente de decisões reservadas
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Todo pedido de decisão reservada ao pesquisador SHALL ser gravado na tabela `gate_requests` com `estado="pendente"` e SHALL sobreviver à queda do processo da sessão e à do terminal. O mesmo pedido pendente (sessão, decisão, referência) MUST NOT ser duplicado. Nenhum caminho do processo da sessão MUST ler a entrada padrão para decidir (ADR 023 §4.1 e §4.2).

#### Scenario: Pedido sobrevive à queda
- **GIVEN** uma sessão `assisted` que criou um pedido `aprovar_hipotese` para a hipótese `h1`
- **WHEN** o processo da sessão recebe `SIGKILL` e o REPL é reaberto
- **THEN** o pedido continua `pendente` no banco e aparece em `pendentes`

#### Scenario: Pedido não duplicado
- **WHEN** a sessão pede duas vezes `aprovar_hipotese` com referência `h1`
- **THEN** existe uma única linha pendente e a segunda chamada devolve a mesma

### Requirement: Somente o papel do terminal resolve pedidos
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
A resposta a um pedido SHALL ser gravada só pelo papel de banco `terminal_writer`, por transição condicional de `pendente` para `autorizada` ou `negada`; o papel usado pelo processo da sessão MUST NOT conseguir resolver pedido, gravar mensagem na caixa de entrada nem gravar presença do terminal; a resposta a um pedido já resolvido MUST ser recusada. Respostas de agente, documento, consultor ou caixa de entrada MUST NOT resolver pedido (ADR 023 §4.3; caso 13). Os gatilhos `gate_requests_guard`, `session_inbox_guard` e `terminal_presence_guard` SHALL exigir `session_user = 'terminal_writer'` e `current_user = 'terminal_writer'` ao mesmo tempo, SHALL ser funções sem `SECURITY DEFINER` e com `search_path` fixo. O terminal SHALL conferir em `pg_trigger`, ao abrir e antes de cada `decidir` e `mensagem`, que os três gatilhos existem e estão habilitados (`tgenabled = 'O'`), e MUST recusar operar o gate quando não estiverem.

#### Scenario: SET ROLE não contorna o gatilho
- **GIVEN** um pedido `pendente` e uma conexão com o papel de `DATABASE_URL` (superusuário no ambiente de teste)
- **WHEN** essa conexão executa `SET ROLE terminal_writer` e depois `UPDATE gate_requests SET estado='autorizada', resolvido_por='terminal' WHERE id=<id>`
- **THEN** o banco levanta erro com "só o terminal resolve pedidos", porque `session_user` não é `terminal_writer`, e o pedido continua `pendente`

#### Scenario: Gatilho desligado
- **GIVEN** o gatilho `gate_requests_guard` desligado no banco de teste por `ALTER TABLE gate_requests DISABLE TRIGGER gate_requests_guard`, feito pelo próprio teste com o papel principal
- **WHEN** o pesquisador digita `decidir <id>` no REPL
- **THEN** o terminal recusa com a mensagem que cita os gatilhos ausentes ou desligados e o pedido continua `pendente`

#### Scenario: Terminal resolve
- **GIVEN** um pedido `pendente` e uma conexão de `terminal_writer`
- **WHEN** o terminal responde `autorizar`
- **THEN** o pedido fica `autorizada` com `resolvido_por="terminal"` e `resolvido_em` preenchido

#### Scenario: Sessão não consegue resolver
- **GIVEN** um pedido `pendente` e uma conexão com o papel de `DATABASE_URL`
- **WHEN** essa conexão executa `UPDATE gate_requests SET estado='autorizada', resolvido_por='terminal' WHERE id=<id>`
- **THEN** o banco levanta erro com "só o terminal resolve pedidos" e o pedido continua `pendente`
- **AND** `INSERT` em `session_inbox` e em `terminal_presence` com esse papel também falham

#### Scenario: Pedido já resolvido
- **GIVEN** um pedido `negada`
- **WHEN** o terminal tenta autorizá-lo
- **THEN** `answer` levanta `GateAlreadyResolved` e o estado continua `negada`

#### Scenario: Fonte não humana
- **WHEN** `answer` é chamado com `source=Source.RESEARCHER_CONSULT`
- **THEN** o pedido continua `pendente` e a resposta ignorada é registrada no log com a origem

### Requirement: Autorização ligada ao objeto e de uso único
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Todo efeito de uma decisão reservada SHALL ser aplicado só depois de `consume_authorized(decisao, referencia, session_chain)` encontrar no banco um pedido com a mesma `decisao` e a mesma `referencia`, `session_id` dentro da cadeia da sessão que aplica, `estado = 'autorizada'` e `resolvido_por` em `terminal` ou `cli`, e marcar `consumido_em` por transição condicional (`WHERE consumido_em IS NULL`). Pedido de outra sessão, já consumido, negado ou de outra referência MUST ser recusado sem aplicar o efeito. A ativação do modo sem limite SHALL usar `referencia = launch_id` e MUST valer só para o lançamento com esse `launch_id` (ADR 023 §4.1 e §4.3).

#### Scenario: Reuso de autorização recusado
- **GIVEN** um pedido `aprovar_hipotese` para `h1` autorizado pelo terminal e já consumido pela sessão `s1`
- **WHEN** o código da sessão chama `consume_authorized("aprovar_hipotese", "h1", ["s1"])` de novo
- **THEN** levanta `GateAuthorizationRefused` com o motivo `ja_consumida` e `h1` não recebe segunda aplicação

#### Scenario: Autorização de outra sessão
- **GIVEN** um pedido `aprovar_hipotese` para `h1` autorizado na sessão `s9`, fora da cadeia de `s1`
- **WHEN** a sessão `s1` chama `consume_authorized("aprovar_hipotese", "h1", ["s1"])`
- **THEN** levanta `GateAuthorizationRefused` com o motivo `outra_sessao` e o pedido de `s9` continua sem `consumido_em`

#### Scenario: Modo sem limite preso ao lançamento
- **GIVEN** um pedido `ativar_modo_sem_limite` autorizado pelo terminal com `referencia` igual ao `launch_id` `L1`
- **WHEN** um processo de sessão é iniciado com um arquivo de lançamento de `launch_id` `L2` que cita esse pedido
- **THEN** o processo não ativa o modo sem limite, sai com código 2 (modo sem limite não confirmado, tabela única de `v18.7-background-sessions` design §1.4) e o pedido de `L1` continua sem `consumido_em`

#### Scenario: Modo sem limite consumido uma vez
- **GIVEN** o pedido `ativar_modo_sem_limite` de `L1` autorizado e já consumido pelo processo de `L1`
- **WHEN** um segundo processo é iniciado com o mesmo arquivo de lançamento de `L1`, copiado pelo teste antes de ser apagado
- **THEN** o segundo processo sai com código 2 sem criar sessão

### Requirement: Leitura sem consumo para o adendo do regimento
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Como única exceção ao uso único, o gate SHALL oferecer `authorized_reference(decisao, referencia)`, que devolve verdadeiro só quando existe um pedido com `decisao = 'ativar_adendo_regimento'`, a mesma `referencia` (o sha256 dos bytes do adendo), `estado = 'autorizada'` e `resolvido_por` em `terminal` ou `cli`, sem marcar `consumido_em` e sem restringir à cadeia da sessão. O método MUST recusar qualquer outra `decisao`, e o `FakeGate` SHALL implementar o mesmo comportamento (ADR 022 §4.4; ADR 023 §4.3).

#### Scenario: Adendo aprovado vale em sessões seguintes do projeto
- **GIVEN** um pedido `ativar_adendo_regimento` com `referencia` igual ao sha256 do adendo, autorizado pelo terminal na sessão `s1`
- **WHEN** a sessão `s2`, fora da cadeia de `s1`, chama `authorized_reference('ativar_adendo_regimento', sha)`
- **THEN** o resultado é verdadeiro e `consumido_em` continua nulo

#### Scenario: Outra decisão não usa a exceção
- **GIVEN** um pedido `aprovar_hipotese` autorizado
- **WHEN** a sessão chama `authorized_reference('aprovar_hipotese', 'h1')`
- **THEN** a chamada é recusada com erro explícito e nenhum efeito é aplicado

#### Scenario: Adendo alterado exige nova aprovação
- **GIVEN** um adendo aprovado com sha256 `a`
- **WHEN** o arquivo muda e o sha256 passa a ser `b`
- **THEN** `authorized_reference('ativar_adendo_regimento', 'b')` devolve falso

### Requirement: Garantias do gate escritas
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
O sistema SHALL garantir, e a documentação da mudança SHALL dizer por escrito, que o código da sessão e os agentes (inclusive ações conduzidas por LLM) não gravam resposta a pedido, mensagem na caixa de entrada nem presença do terminal; e SHALL dizer por escrito que essa garantia MUST NOT ser lida como proteção contra código arbitrário executado no host com o mesmo usuário do sistema operacional, nem contra quem tem o papel de superusuário do banco. Nenhum caminho de `src/` SHALL usar `SET ROLE`, `SET SESSION AUTHORIZATION`, `session_replication_role`, `DISABLE TRIGGER`, `DROP TRIGGER`, `ALTER ROLE` nem a cadeia `terminal_writer`, exceto `src/terminal_db.py` e o script de migração do papel (ADR 023 §4.3; caso 13).

#### Scenario: Teste estático dos contornos
- **WHEN** o teste estático percorre os arquivos `.py` de `src/`
- **THEN** nenhuma das cadeias `SET ROLE`, `SET SESSION AUTHORIZATION`, `session_replication_role`, `DISABLE TRIGGER`, `DROP TRIGGER`, `ALTER ROLE` e `terminal_writer` aparece fora de `src/terminal_db.py`

#### Scenario: Garantia documentada
- **WHEN** o teste lê o texto de ajuda do comando `decidir` e a seção do `README.md` sobre o gate
- **THEN** os dois contêm a frase "protege contra defeito de código e ações de agentes; não protege contra código executado no host com o mesmo usuário do sistema nem contra superusuário do banco"

### Requirement: Credencial do terminal fora do processo da sessão
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
A credencial de `terminal_writer` SHALL ficar num arquivo separado do `.env` (`TERMINAL_DATABASE_URL_FILE`), com modo `0600`, lido só por `load_terminal_database_url()` no processo do terminal; o processo da sessão SHALL ser iniciado com ambiente filtrado, sem `TERMINAL_DATABASE_URL_FILE`, `TERMINAL_DATABASE_URL`, `PGPASSWORD`, `PGPASSFILE` e `PGSERVICEFILE`, e MUST falhar se tentar carregar a credencial; a credencial no ambiente ou no `.env` MUST fazer a inicialização falhar (ADR 023 §4.3).

#### Scenario: Ambiente da sessão
- **GIVEN** o terminal com `TERMINAL_DATABASE_URL_FILE` e `PGPASSWORD` definidos
- **WHEN** o processo da sessão é criado
- **THEN** `os.environ` do processo não contém nenhum dos nomes da lista
- **AND** `load_terminal_database_url()` no processo da sessão levanta erro

#### Scenario: Nome da lista no .env
- **GIVEN** um `.env` temporário com `TERMINAL_DATABASE_URL_FILE=/tmp/x` no diretório de trabalho do processo da sessão
- **WHEN** o processo da sessão importa `src.config` (que chama `load_dotenv()`)
- **THEN** `os.environ` do processo não contém `TERMINAL_DATABASE_URL_FILE` depois da importação

#### Scenario: Permissão aberta
- **GIVEN** o arquivo de credencial com modo `0644`
- **WHEN** o REPL abre
- **THEN** a abertura falha com mensagem que pede `chmod 600`

#### Scenario: Credencial no .env
- **GIVEN** `TERMINAL_DATABASE_URL=postgresql://terminal_writer:x@localhost/db` no ambiente
- **WHEN** `src.config` é importado
- **THEN** a importação falha com mensagem que manda mover a credencial para o arquivo

### Requirement: A sessão não para por um pedido
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Enquanto um pedido está pendente, a sessão SHALL continuar com o que não depende dele e SHALL esperar só quando não houver mais nada a fazer: nos modos `semi` e `auto`, SHALL passar a `aguarda_pesquisador` e encerrar o processo; no `assisted`, com o terminal presente, SHALL esperar consultando o gate a cada `GATE_POLL_SECONDS` (padrão 5), sem contar a espera como ciclo ocioso nem como estagnação (ADR 023 §4.4; ADR 021 §5.6).

#### Scenario: Segue com o que não depende
- **GIVEN** uma sessão `assisted` com a hipótese `h1` aprovada e `h2` com pedido pendente
- **WHEN** o ciclo executa
- **THEN** as subtarefas de `h1` executam e as de `h2` não

#### Scenario: Espera no assisted
- **GIVEN** `GATE_POLL_SECONDS=1` em teste, uma sessão `assisted` com só o pedido de `h2` pendente e o terminal presente
- **WHEN** passam 3 consultas do gate sem resposta
- **THEN** `idle_cycles` e o contador de estagnação não mudam e a sessão continua `active`

### Requirement: Pedidos pendentes visíveis no terminal
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
O terminal SHALL listar os pedidos pendentes (`pendentes`), incluí-los na lista de pesquisas não finalizadas ao abrir o REPL e lembrá-los a cada `GATE_REMINDER_SECONDS` (padrão 300); `decidir <id>` SHALL pedir a resposta conforme o tipo do pedido (ADR 023 §4.4 e §1.2, item 3; caso 7).

#### Scenario: Lista ao abrir
- **GIVEN** a sessão `b-01` em `aguarda_pesquisador` com os pedidos 12 (`decidir_objetivo_atingido`) e 13 (`aprovar_hipotese`)
- **WHEN** o REPL abre com entrada simulada "m"
- **THEN** a linha de `b-01` cita os pedidos 12 e 13 com o texto de cada um

#### Scenario: Lembrete
- **GIVEN** `GATE_REMINDER_SECONDS=1` em teste e um pedido pendente
- **WHEN** o REPL fica 2 s ocioso com relógio simulado
- **THEN** o lembrete com o id do pedido é impresso ao menos uma vez

### Requirement: Resposta ao último pedido retoma a sessão
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
Quando a resposta do pesquisador resolve o último pedido pendente de uma sessão `aguarda_pesquisador`, o terminal SHALL retomá-la pelo mecanismo de retomada, com a verificação de memória, e a sessão nova SHALL aplicar a resposta e continuar do checkpoint (ADR 023 §1.2, item 1; caso 3).

#### Scenario: Política perguntar em semi
- **GIVEN** uma sessão `semi` que ficou `aguarda_pesquisador` com o único pedido `decidir_objetivo_atingido`, e respostas gravadas para a continuação
- **WHEN** o pesquisador responde `decidir <id>` com "continuar"
- **THEN** um processo novo cria a sessão que continua a origem, as subtarefas concluídas não são reexecutadas e o pedido fica com `consumido_em` preenchido

#### Scenario: Ainda há pedidos
- **GIVEN** uma sessão `aguarda_pesquisador` com dois pedidos pendentes
- **WHEN** o pesquisador responde um deles
- **THEN** nenhuma sessão nova é criada e o terminal lembra o pedido restante

### Requirement: Caixa de entrada da sessão
_Origem: [`v18.7-persistent-human-gate`](../../changes/archive/v18.7-persistent-human-gate/proposal.md)_
O pesquisador SHALL poder mandar uma mensagem a uma sessão em execução pelo terminal (`mensagem <apelido> <texto>`); a mensagem SHALL ser gravada só pelo papel do terminal, MUST ser recusada acima de `SESSION_INBOX_MAX_CHARS` (padrão 2000) ou com mais de `SESSION_INBOX_MAX_PENDING` (padrão 20) não consumidas, SHALL ser registrada no grafo como `Decisao` de orientação do pesquisador ligada à sessão (`TOMADA_EM`) e SHALL ser entregue ao Researcher no próximo replanejamento, delimitada como dado em `<mensagens_do_pesquisador>`. A mensagem MUST NOT resolver pedido reservado (ADR 023 §5; ADR 022).

#### Scenario: Entrega no replanejamento
- **GIVEN** uma sessão `auto` em execução com provedor gravado que registra o prompt recebido
- **WHEN** o pesquisador manda "não teste mais SVM" e a sessão replaneja
- **THEN** o prompt de replanejamento contém o texto dentro de `<mensagens_do_pesquisador>` e a mensagem fica com `consumido_em` preenchido

#### Scenario: Mensagem longa
- **WHEN** o pesquisador manda uma mensagem de 2001 caracteres
- **THEN** o terminal recusa, cita o limite e nada é gravado

#### Scenario: Mensagem não decide
- **GIVEN** um pedido `aprovar_hipotese` pendente para `h4`
- **WHEN** o pesquisador manda "rejeite a hipótese h4" e a sessão replaneja
- **THEN** o pedido de `h4` continua `pendente` e a hipótese não muda de estado

#### Scenario: Registro no grafo
- **WHEN** a mensagem é gravada
- **THEN** existe um nó `Decisao` com `contexto="orientacao do pesquisador"` ligado por `TOMADA_EM` à sessão

### Requirement: Restrição de direção só por decisão do pesquisador
_Origem: [`v18.7-exploration-limits`](../../changes/archive/v18.7-exploration-limits/proposal.md)_
Uma restrição de direção (nó `Restricao`, spec `knowledge-graph`) SHALL ser criada só pela ação do pesquisador no processo do terminal: o comando `geminiclaw project restrict` ou a resposta `restringir` a um pedido `restringir_direcao` do gate persistente. Um pedido de agente por `ask_researcher` com `decisao_reservada="restringir_direcao"` SHALL seguir a regra das decisões reservadas (consultor não chamado, interação `pendente_pesquisador`, pedido no gate) e MUST NOT criar `Restricao` enquanto o pesquisador não responder (ADR 021 §5.5).

#### Scenario: Restrição de direção pedida por agente
- **GIVEN** uma sessão `auto`
- **WHEN** um agente chama `ask_researcher` com `decisao_reservada="restringir_direcao"` e a pergunta "encerrar a linha que usa o reagente X?"
- **THEN** o consultor não é chamado, a interação tem `respondido_por="pendente_pesquisador"`, existe um pedido `restringir_direcao` pendente e nenhum nó `Restricao` é criado

#### Scenario: Resposta do pesquisador cria a restrição
- **GIVEN** um pedido `restringir_direcao` com `motivo="restricao_duvidosa"` para a subtarefa `t3`
- **WHEN** o terminal responde `restringir`
- **THEN** a sessão consome o pedido por `consume_authorized` e cria um nó `Restricao` com `decidida_por="pesquisador"` e `pedido_id` igual ao id do pedido, ligado por `RESTRINGE` ao `Problema`

#### Scenario: Liberar não cria restrição
- **GIVEN** o mesmo pedido
- **WHEN** o terminal responde `liberar`
- **THEN** nenhum nó `Restricao` é criado e `t3` pode voltar no próximo plano
