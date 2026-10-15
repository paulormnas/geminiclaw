# Design: Gate Persistente de Decisões Reservadas e Caixa de Entrada da Sessão

## 0. Estado atual (verificado na branch `docs/adr-021-022-exploracao-contrato`, 2026-10-15)

| Ponto | Onde | O que faz hoje |
|---|---|---|
| Gate | `src/human_gate.py:73-134`, `:165-170` | `HumanGate` em memória (dicionário com trava), um por processo (`default_gate()`); `answer` só aceita `Source.TERMINAL`/`Source.CLI` (`:47`, `:112`) |
| Pergunta no terminal | `src/human_gate.py:136-162` | `ask_in_terminal` lê `stdin` se for TTY |
| Autorização pela CLI | `src/human_gate.py:173-182` | registra e autoriza no mesmo processo |
| Decisões reservadas | `src/research_consult/__init__.py:13-19` | cinco: `aprovar_oportunidade`, `confirmar_problema`, `aprovar_termo_vocabulario`, `autorizar_escrita_instrumento`, `ativar_modo_sem_limite` |
| Aprovação de hipóteses | `src/knowledge/hypothesis_cycle.py:571-620`; padrão em `src/exploration.py:203` | `terminal_approver`: lote no terminal; sem TTY devolve `{}` |
| Confirmação de solução | `src/exploration.py:127-162`, uso em `:453` | `terminal_solution_confirmer`: "encerrar"/"continuar" no terminal |
| `ask_researcher` no `assisted` | `src/orchestrator.py:1468-1509` | imprime e espera `input` em `asyncio.to_thread` |
| Oportunidade pendente | `src/knowledge/hypotheses.py:623-632` | pedido no gate em memória |
| Usuários do gate | `src/project_session.py:214`, `src/unlimited_mode.py:129`, `src/cli_graph.py:270`, `src/knowledge/opportunities.py:187` | `default_gate()` |
| Papel principal do banco | `docker-compose.yml` (`POSTGRES_USER`) | é o superusuário criado pela imagem oficial; dono de todas as tabelas |
| Papel somente leitura | `scripts/migrate_v17_knowledge.py:138-185` | precedente: `knowledge_reader` criado por script, senha de variável de ambiente |
| Replanejamento | `src/orchestrator.py:2115-2160` | prompt `MODO: REPLAN` montado pelo orquestrador |

Achado que muda o desenho: o processo da sessão conecta com o papel principal, que é superusuário e dono das tabelas. Privilégios de coluna e `REVOKE` não valem para dono nem superusuário. Para que "o processo da sessão não consegue gravar" (caso 13) valha contra o código da sessão, a proteção fica num gatilho que confere `current_user` (§1.3). O risco residual (superusuário pode desligar gatilho ou assumir o papel) está no §5.

## 1. Decisões

### 1.1 Tipos de pedido

| `decisao` | Quem cria | Opções de resposta (`resposta`) | Efeito |
|---|---|---|---|
| `aprovar_oportunidade`, `confirmar_problema`, `aprovar_termo_vocabulario`, `autorizar_escrita_instrumento` | sessão ou CLI | `{"acao": "autorizar" \| "negar"}` | como hoje |
| `ativar_modo_sem_limite` | terminal, antes do lançamento, com `referencia = launch_id` | `autorizar`/`negar` | o processo da sessão confere no banco o pedido cuja `referencia` é o `launch_id` do seu arquivo de lançamento e o consome (§1.2) |
| `aprovar_hipotese` | sessão `assisted` | `{"acao": "aprovar" \| "rejeitar" \| "editar", "motivo"?: str, "enunciado"?: str}` | a sessão aplica com `Actor` pesquisador |
| `decidir_objetivo_atingido` | sessão, política `perguntar` (hoje: `assisted` ao atingir a solução) | `{"acao": "encerrar" \| "continuar"}` | fecha com `solucao_encontrada` ou segue |
| `responder_pergunta_agente` | `ask_researcher` no `assisted` | `{"texto": str}` | resposta entregue ao agente (se ainda espera) ou ao Researcher no replanejamento |
| `decidir_continuidade` | estagnação, saturação, intervenções esgotadas, cobertura saturada, várias compatíveis, experimento físico, planos rejeitados (`v18.7-exploration-limits`; subtipo em `motivo`) | `{"acao": "continuar" \| "orientar" \| "parar" \| "aceitar_conjunto" \| "objetivo_atingido", "orientacao"?: str}`, limitado às `opcoes` gravadas no pedido | conforme ADR 021 §5.2, §5.5-§5.6 |
| `restringir_direcao` | caso duvidoso de restrição (`v18.7-exploration-limits`, `motivo="restricao_duvidosa"`) ou pedido de agente por `ask_researcher` | `{"acao": "restringir" \| "liberar"}` | conforme ADR 021 §5.5; o efeito (nó `Restricao`) é de `v18.7-exploration-limits` |

O `CHECK` de `decisao` inclui também `ativar_adendo_regimento`, cujo produtor e cuja entrada em `DECISOES_RESERVADAS` são de `v18.7-agent-system-prompts` (ADR 022 §4.4), para que aquela mudança não precise alterar o schema. Todos os da tabela entram em `DECISOES_RESERVADAS`, como o ADR 023 §4.1 pede: o consultor nunca os responde (requisito existente "Decisões reservadas ao pesquisador").

Alinhamento com `v18.7-exploration-limits` (2026-10-15): o catálogo é desta mudança, e o design §10 daquela usa os mesmos nomes de `decisao`, `motivo` e opções, sem invólucro próprio. A coluna `motivo` guarda o subtipo e `opcoes` guarda as opções do pedido: `decidir_objetivo_atingido` (política `perguntar`); `decidir_continuidade` com `motivo` em `estagnacao`, `saturacao`, `intervencoes_esgotadas`, `cobertura_saturada`, `varias_compativeis`, `aguarda_experimento_fisico` e `planos_rejeitados` (`aceitar_conjunto` e `objetivo_atingido` fecham com `solucao_encontrada`; `parar` fecha com `encerrada_pesquisador`, exceto em `planos_rejeitados`, que fecha com `planos_rejeitados`; o motivo `planos_rejeitados` só é produzido com `ON_PLAN_REJECTIONS=parar` nos modos `assisted` e `semi`: com a política padrão `explorar` a rejeição consecutiva aciona o Curator e nenhum pedido é criado); `restringir_direcao` com `motivo` `restricao_duvidosa` e opções `restringir`/`liberar`; `confirmar_problema` com `motivo` `revisao_objetivo` para a revisão do objetivo proposta no plano. A `referencia` de cada pedido inclui o `motivo`. O agrupamento em três decisões foi aceito pelo pesquisador em 2026-10-15 (Questão 5).

### 1.2 Persistência e transição condicional

- A sessão cria o pedido com `estado='pendente'`; um índice único parcial impede duplicar o mesmo pedido pendente (`session_id`, `decisao`, `referencia`).
- O terminal resolve com `UPDATE gate_requests SET estado=%s, resposta=%s, resolvido_por='terminal', resolvido_em=now() WHERE id=%s AND estado='pendente' RETURNING id`, numa conexão do papel `terminal_writer`. Sem linha devolvida: "pedido já resolvido" (recusa).
- A sessão marca o consumo (`consumido_em`) e a obsolescência (`obsoleto_em`, por exemplo hipótese retirada pelo replanejamento); essas são as únicas colunas que o papel principal pode alterar.
- **Autorização ligada ao objeto e de uso único** (parecer, item 3). Todo consumidor de uma decisão chama `PersistentGate.consume_authorized(decisao, referencia, session_chain)`, que confere no banco, numa transação, `decisao`, `referencia`, `session_id` dentro da cadeia da sessão (ou `NULL` só para pedido da CLI fora de sessão, nunca aceito por um processo de sessão), `estado = 'autorizada'` e `resolvido_por IN ('terminal','cli')`, e marca o consumo com `UPDATE gate_requests SET consumido_em = now() WHERE id = %s AND consumido_em IS NULL RETURNING id` antes de aplicar o efeito. Sem linha devolvida, a autorização é recusada (`GateAuthorizationRefused`, com o motivo `nao_encontrada`, `outra_sessao`, `ja_consumida` ou `nao_autorizada`) e o efeito não é aplicado. As referências são fixas por tipo: `aprovar_hipotese` usa o id da hipótese; `ativar_modo_sem_limite` usa o `launch_id` do lançamento e só vale para ele; `ativar_adendo_regimento` usa o sha256 dos bytes do adendo; os demais usam a referência gravada pelo produtor (com o `motivo`).
- Na retomada, a sessão nova lê os pedidos da cadeia inteira (`session_id` em qualquer sessão da cadeia) com `consumido_em IS NULL`: pedidos respondidos enquanto a sessão estava fora são aplicados; pendentes continuam pendentes.
- O texto exibido (`pergunta`) é montado pela sessão a partir de campos estruturados, passa por `sanitize_text` e pelo filtro de exibição e tem no máximo `GATE_QUESTION_MAX_CHARS`; nunca leva dado bruto (ADR 019).

### 1.3 Papel do terminal e gatilhos

- `terminal_writer` é criado por `scripts/migrate_v18_7_terminal_role.py` (rodado com o papel principal). O script gera a senha (`secrets.token_urlsafe(32)`) se o arquivo de credencial não existe e grava o DSN completo no arquivo (`0600`, criado com `O_EXCL`); se existe, reaplica a senha dele (`ALTER ROLE ... PASSWORD`). A senha nunca passa por `.env`, log ou PR.
- Gatilhos `BEFORE INSERT OR UPDATE` (funções PL/pgSQL sem `SECURITY DEFINER`, com `SET search_path = pg_catalog, public`); "papel do terminal" abaixo significa `session_user = 'terminal_writer' AND current_user = 'terminal_writer'`, o que fecha o `SET ROLE terminal_writer` feito a partir do papel principal (parecer, item 1):
  - `gate_requests_guard`: se a operação define ou muda `estado` para algo diferente de `pendente`, ou muda `resposta`, `resolvido_por` ou `resolvido_em`, exige o papel do terminal; se não, `RAISE EXCEPTION 'gate: só o terminal resolve pedidos'`. Inserção com `estado <> 'pendente'` só pelo papel do terminal (autorização pela CLI).
  - `session_inbox_guard`: `INSERT` só pelo papel do terminal; `UPDATE` de outro papel só pode mudar `entregue_em` e `consumido_em`.
  - `terminal_presence_guard`: `INSERT` e `UPDATE` só pelo papel do terminal (fecha o risco 1 de `v18.7-background-sessions`).
- **Conferência dos gatilhos pelo terminal.** Ao abrir e antes de cada `decidir` e `mensagem`, o terminal consulta `pg_trigger` e exige que os três gatilhos existam nas tabelas certas com `tgenabled = 'O'`; se algum faltar ou estiver desligado, o terminal recusa operar o gate, com a mensagem "gatilhos do gate ausentes ou desligados; rode a migração `v18_7_002_gate_inbox.sql`", e não grava nada.
- `HUMAN_SOURCES` continua `{terminal, cli}`; uma mensagem de agente, documento, consultor ou a caixa de entrada nunca resolvem pedido.

### 1.4 Credencial e ambiente da sessão

- `TERMINAL_DATABASE_URL_FILE` (padrão `~/.config/<APP_NAME em minúsculas>/terminal_database_url`). `src/config.py: load_terminal_database_url()` só é chamada pelo processo do terminal (REPL, comando direto e comandos de CLI que decidem); recusa arquivo com permissão de grupo ou outros (`stat.S_IRWXG | S_IRWXO`), com mensagem que pede `chmod 600`; ausência gera mensagem com o comando de migração.
- O `.env` não pode conter a credencial: se `TERMINAL_DATABASE_URL` aparecer no ambiente, ou algum valor de variável contiver `terminal_writer`, a inicialização falha ("credencial do terminal no ambiente; mova para o arquivo").
- `filtered_env` (de `v18.7-background-sessions`) passa a retirar sempre `TERMINAL_DATABASE_URL_FILE`, `TERMINAL_DATABASE_URL`, `PGPASSWORD`, `PGPASSFILE` e `PGSERVICEFILE`, além de `SESSION_ENV_DENYLIST`. No processo da sessão, `load_terminal_database_url()` levanta erro (marcador de processo definido por `src/session_process.py`).

### 1.5 A sessão não para por um pedido

- Pedido criado: a sessão segue com subtarefas que não dependem dele (por exemplo, hipóteses já aprovadas). A hipótese pendente fica fora da fila até a resposta.
- `ask_researcher` no `assisted`: a subtarefa que perguntou espera a resposta por até `GATE_ASK_WAIT_SECONDS` (padrão 120, menor que o `AGENT_TIMEOUT_SECONDS` padrão de 300; a inicialização falha se `AGENT_TIMEOUT_SECONDS` não for 0 e for menor ou igual a `GATE_ASK_WAIT_SECONDS`); sem resposta, o agente recebe a mensagem de pendência, segue com a suposição documentada e o pedido continua pendente; a resposta posterior vai ao Researcher no replanejamento, delimitada como dado.
- Quando só restam pedidos pendentes: `semi` e `auto` vão a `aguarda_pesquisador` e encerram o processo (`v18.7-background-sessions`); `assisted` com o terminal presente espera, consultando o gate a cada `GATE_POLL_SECONDS` (5). Essa espera não incrementa `idle_cycles` (`src/autonomous_loop.py:1087`) nem o contador de estagnação.
- O terminal lembra os pedidos pendentes a cada `GATE_REMINDER_SECONDS` (300) e ao abrir; a lista de pesquisas não finalizadas do `v18.7-background-sessions` passa a mostrar os pedidos.
- Responder o último pedido pendente de uma sessão `aguarda_pesquisador` retoma a sessão pelo mecanismo existente, com a verificação de memória (caso 3); responder em sessão `suspensa_sem_pesquisador` não retoma sozinho (o pesquisador escolhe na pergunta de retomada).

### 1.6 Comandos do terminal

- `pendentes [apelido]`: lista id, apelido, decisão, pergunta e há quanto tempo está pendente.
- `decidir <id>`: mostra o pedido e pede a resposta conforme o tipo (§1.1); `aprovar_hipotese` aceita `a`/`r`/`e`/`p` como hoje (`p` deixa pendente).
- Comandos de CLI (`vocab approve`, `opportunities approve`, `graph edit`, `project confirm`) registram e resolvem no gate persistente com `resolvido_por='cli'`.

### 1.7 Caixa de entrada

- `mensagem <apelido> <texto>`: o terminal grava a mensagem com o papel do terminal (`tipo='orientacao'`); texto com mais de `SESSION_INBOX_MAX_CHARS` (2000) é recusado, não truncado; controle de caracteres removido; no máximo `SESSION_INBOX_MAX_PENDING` (20) mensagens não consumidas por sessão.
- O terminal registra a orientação no grafo como nó `Decisao` (`contexto="orientacao do pesquisador"`, `justificativa` = texto sanitizado) com `Decisao-TOMADA_EM->Sessao`, autor pesquisador e vetorização `pendente` (o terminal não carrega embeddings; a próxima reconciliação vetoriza).
- A sessão lê a caixa a cada `SESSION_INBOX_POLL_SECONDS` (5), marca `entregue_em` e guarda as mensagens até o próximo replanejamento, quando entram no prompt `MODO: REPLAN` como bloco `<mensagens_do_pesquisador>` com a instrução de que são orientação e dado, não comando; depois marca `consumido_em`.
- A mensagem orienta o plano, mas não decide nada reservado: "rejeite a hipótese h4" numa mensagem não muda o estado da hipótese; o Researcher pode propor, e a decisão continua no gate.
- A coluna `tipo` aceita também `comando`, usado pelas ações imediatas de `v18.7-session-events-terminal` (pausar, parar, cancelar, replanejar); esta mudança só cria o valor.

## 2. Contratos

### 2.1 DDL (esboço; `scripts/init_db.sql` e `scripts/migrations/v18_7_002_gate_inbox.sql`)

```sql
CREATE TABLE IF NOT EXISTS gate_requests (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT,                                   -- NULL para decisão da CLI fora de sessão
    project_id      TEXT,
    decisao         TEXT NOT NULL CHECK (decisao IN (
                        'aprovar_oportunidade','confirmar_problema','aprovar_termo_vocabulario',
                        'autorizar_escrita_instrumento','ativar_modo_sem_limite','aprovar_hipotese',
                        'decidir_objetivo_atingido','responder_pergunta_agente','decidir_continuidade',
                        'restringir_direcao','ativar_adendo_regimento')),   -- o último é produzido por v18.7-agent-system-prompts
    motivo          TEXT CHECK (char_length(motivo) <= 64),             -- subtipo (ex.: estagnacao, saturacao)
    referencia      TEXT NOT NULL CHECK (char_length(referencia) <= 120),
    pergunta        TEXT NOT NULL CHECK (char_length(pergunta) <= 1000),
    opcoes          JSONB NOT NULL DEFAULT '[]',
    estado          TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','autorizada','negada')),
    resposta        JSONB,
    resolvido_por   TEXT CHECK (resolvido_por IN ('terminal','cli')),
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolvido_em    TIMESTAMPTZ,
    consumido_em    TIMESTAMPTZ,
    obsoleto_em     TIMESTAMPTZ,
    CHECK ((estado = 'pendente') = (resolvido_por IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_gate_pendente ON gate_requests (session_id, decisao, referencia) WHERE estado = 'pendente';
CREATE INDEX IF NOT EXISTS idx_gate_sessao ON gate_requests (session_id, estado);

CREATE TABLE IF NOT EXISTS session_inbox (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL,
    tipo         TEXT NOT NULL CHECK (tipo IN ('orientacao', 'comando')),
    conteudo     TEXT NOT NULL CHECK (char_length(conteudo) <= 2000),
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    entregue_em  TIMESTAMPTZ,
    consumido_em TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_inbox_pendentes ON session_inbox (session_id, id) WHERE consumido_em IS NULL;

-- gatilhos gate_requests_guard, session_inbox_guard, terminal_presence_guard (§1.3), em PL/pgSQL
-- papel e grants: scripts/migrate_v18_7_terminal_role.py
```

O limite de 2000 no `CHECK` acompanha o padrão de `SESSION_INBOX_MAX_CHARS`; o valor configurado não pode passar dele (validado na inicialização).

### 2.2 Privilégios

| Papel | `gate_requests` | `session_inbox` | `terminal_presence` |
|---|---|---|---|
| `terminal_writer` | `SELECT, INSERT, UPDATE` | `SELECT, INSERT, UPDATE` | `SELECT, INSERT, UPDATE` |
| papel principal (sessão) | dono; o gatilho só permite inserir `pendente` e alterar `consumido_em`, `obsoleto_em` | dono; o gatilho só permite alterar `entregue_em`, `consumido_em` | dono; o gatilho recusa escrita |

### 2.3 Interface

```python
class PersistentGate:
    def request(self, decisao: str, referencia: str, pergunta: str, opcoes: list[str], *,
                motivo: str | None = None,
                session_id: str | None, project_id: str | None) -> GateRequest: ...   # idempotente por (sessão, decisão, referência)
    def pending(self, session_ids: Iterable[str]) -> list[GateRequest]: ...
    def answered_unconsumed(self, session_ids: Iterable[str]) -> list[GateRequest]: ...
    def mark_consumed(self, request_id: int) -> None: ...
    def authorized(self, request_id: int) -> bool: ...                               # autorizada e resolvido_por humano
    def consume_authorized(self, decisao: str, referencia: str,
                           session_chain: Iterable[str]) -> GateRequest: ...       # §1.2; GateAuthorizationRefused

class TerminalGate(PersistentGate):    # só no processo do terminal; conexão de terminal_writer
    def answer(self, request_id: int, *, source: Source, estado: str, resposta: dict) -> GateRequest: ...  # GateAlreadyResolved
```

### 2.4 Interface comum de aprovação

Esta mudança é a dona da interface comum que o laço de hipóteses usa para pedir e conferir aprovação do pesquisador, tanto com o gate persistente quanto com o aprovador injetado nos testes. Ela fica em `src/human_approval.py` (nome conferido com a `v18.7-source-layout`) e mantém os tipos que já existem em `src/knowledge/hypothesis_cycle.py:65-85` (`ApprovalItem`, `ApprovalDecision`):

```python
class ApprovalPort(Protocol):
    def __call__(self, items: list[ApprovalItem]) -> dict[str, ApprovalDecision]: ...
        # mesma assinatura do Approver de hoje; item fora do dicionário continua pendente
    def previously_approved(self, hypothesis_id: str, session_chain: Iterable[str]) -> bool: ...
        # verdadeiro só com pedido aprovar_hipotese desse id, estado autorizada e resolvido_por humano

class PersistentGateApprover:   # implementação de produção, sobre PersistentGate
class FakeGate:                 # tests/support/fake_gate.py: implementa ApprovalPort e a API do PersistentGate em memória
```

`PersistentGateApprover.__call__` cria um pedido `aprovar_hipotese` por item (idempotente) e devolve só as decisões já respondidas e consumidas por `consume_authorized` (ou negadas). `previously_approved` lê `gate_requests`, nunca a trilha de auditoria do grafo. `v18.7-hypothesis-linking` (mesma onda, em paralelo) depende desta interface: se for mergeada antes, cria `src/human_approval.py` com o `Protocol` exatamente como acima e usa a implementação provisória `NoGateApprovalPort` (envolve o `Approver` injetado; `previously_approved` devolve sempre `False`, o que faz a reabertura no `assisted` voltar a `proposta`); esta mudança troca a provisória por `PersistentGateApprover`.

### 2.5 Máquina de estados do pedido

```
pendente ──(terminal_writer: autorizar)──> autorizada ──(sessão: consumido_em)──> consumida
    │    ──(terminal_writer: negar)─────> negada ─────(sessão: consumido_em)──> consumida
    └──(sessão: obsoleto_em; continua pendente na tabela, some das listas)
```

## 3. Configuração (`src/config.py`)

| Variável | Padrão | Uso |
|---|---|---|
| `TERMINAL_DATABASE_URL_FILE` | `~/.config/<app>/terminal_database_url` | arquivo da credencial do papel do terminal |
| `GATE_POLL_SECONDS` | `5` | consulta do gate pela sessão `assisted` em espera |
| `GATE_REMINDER_SECONDS` | `300` | lembrete de pedidos pendentes no REPL |
| `GATE_ASK_WAIT_SECONDS` | `120` | espera da subtarefa por `responder_pergunta_agente` |
| `GATE_QUESTION_MAX_CHARS` | `1000` | texto exibido do pedido |
| `GATE_ANSWER_MAX_CHARS` | `2000` | texto livre da resposta (pergunta de agente, edição de enunciado, orientação) |
| `SESSION_INBOX_MAX_CHARS` | `2000` | tamanho máximo da mensagem (não pode passar de 2000) |
| `SESSION_INBOX_MAX_PENDING` | `20` | mensagens não consumidas por sessão |
| `SESSION_INBOX_POLL_SECONDS` | `5` | leitura da caixa pela sessão |

Escolha do tamanho da mensagem: 2000 caracteres comportam uma orientação de alguns parágrafos, limitam a superfície de injeção e o custo de contexto do replanejamento (ADR 022), e a recusa (em vez de truncar) evita entregar orientação cortada no meio.

## 4. Mapa dos casos de aceite do ADR 023

| Caso | Requisito (spec desta mudança) | Tipo |
|---|---|---|
| 3 (resposta que reabre) | `researcher-consult` / "Resposta ao último pedido retoma a sessão" | integração |
| 7 (pedidos pendentes na lista) | `researcher-consult` / "Pedidos pendentes visíveis no terminal" | unidade |
| 13 | `researcher-consult` / "Somente o papel do terminal resolve pedidos" | integração (PostgreSQL real, dois papéis) |

Os demais requisitos (aprovação de hipóteses, confirmação de solução, `ask_researcher`, caixa de entrada) não correspondem a um caso numerado do ADR, mas cada cenário vira teste.

## 5. Análise de impacto (6 eixos)

| Eixo | Impacto | Detalhes |
|---|---|---|
| Orquestrador & Loop | Alto | Pedidos persistentes; espera sem contar como ocioso; leitura da caixa; retomada ao responder. |
| Agentes & Prompts | Médio | `ask_researcher` no `assisted` com espera limitada; bloco `<mensagens_do_pesquisador>` no replanejamento. |
| Sandboxes & Containers | Nenhum | |
| Persistência | Alto | Duas tabelas, três gatilhos, papel novo, nó `Decisao` de orientação no grafo. |
| Segurança | Alto | Separação de papéis; credencial fora do `.env`; injeção de prompt pela caixa de entrada. |
| Testes & Telemetria | Alto | Testes com PostgreSQL real e dois papéis; contagem de intervenções humanas a partir do gate. |

## 6. Segurança

Parecer do Analista de Segurança (2026-10-15): **Aprovado com ressalvas.**

O achado do papel superusuário está confirmado no código: `docker-compose.yml` cria o papel principal por `POSTGRES_USER` (superusuário da imagem oficial), `src/db.py:84-86` usa esse `DATABASE_URL` em todo o processo e `scripts/init_db.sql` não cria papel de aplicação. Um superusuário ignora `GRANT`/`REVOKE` e pode `SET ROLE terminal_writer`, `ALTER TABLE ... DISABLE TRIGGER`, `SET session_replication_role = replica`, `ALTER ROLE terminal_writer PASSWORD` ou `COPY ... TO PROGRAM`. Porém um papel não superusuário sozinho não fecharia o caso 13 contra código hostil: o arquivo de credencial é legível pelo mesmo usuário do sistema operacional (risco residual 2). O que esta mudança garante de fato é proteção contra defeito de código e contra ação conduzida por LLM. Os agentes não têm ferramenta de SQL nem executam código no host (ADR 014), o Cypher é sempre parametrizado (`src/knowledge/graph_store.py:651-676`) e a leitura de arquivos pelos agentes fica confinada à sessão (`src/skills/document_processor/skill.py:52-60`). Isso basta para a V18.7, com os requisitos abaixo. Severidade do achado do superusuário: **Média**.

1. **Médio: gatilhos endurecidos.** Os três gatilhos exigem `session_user = 'terminal_writer' AND current_user = 'terminal_writer'`, o que fecha o `SET ROLE` a partir do papel principal. As funções não são `SECURITY DEFINER` e fixam o `search_path`. O terminal confere em `pg_trigger` que os três gatilhos existem e estão habilitados (`tgenabled = 'O'`) ao abrir e antes de cada `decidir`, e recusa operar se não estiverem. O teste estático do risco 1 cobre também `SET SESSION AUTHORIZATION`, `session_replication_role`, `DISABLE TRIGGER`, `DROP TRIGGER`, `ALTER ROLE` e a cadeia `terminal_writer` em `src/`, exceto em `src/terminal_db.py` e no script de migração.
2. **Médio: modelo de ameaça escrito.** O requisito do caso 13 diz o que garante: "o código da sessão e os agentes não gravam resposta, mensagem nem presença". Diz também o que não garante: código arbitrário rodando com o mesmo usuário do sistema operacional. O endurecimento fica numa mudança própria, a fazer antes de produção (decisão do pesquisador, 2026-10-15: a versão atual é de desenvolvimento 0.0 e o endurecimento não é necessário até lá; não é portão de nenhuma versão do roadmap). Ela leva as duas medidas juntas, porque uma sem a outra não fecha o caso. A primeira é um papel de aplicação não superusuário para o processo da sessão, sem permissão de gravar a resposta em `gate_requests` e sem `INSERT` em `session_inbox` e `terminal_presence`. A segunda é um usuário de sistema operacional separado, que não lê o arquivo de credencial. O papel não superusuário também vale por si: tira `COPY ... TO PROGRAM` e a leitura de arquivos do servidor do alcance de uma eventual injeção de SQL. Resposta à Questão 1: fica fora desta mudança, para antes de produção.
3. **Médio: autorização ligada ao objeto e de uso único.** Todo consumidor de decisão confere no banco `decisao`, `referencia`, `session_id` dentro da cadeia da sessão, `estado = 'autorizada'` e `resolvido_por IN ('terminal','cli')`. Antes de aplicar o efeito, marca o consumo com `UPDATE ... SET consumido_em = now() WHERE id = %s AND consumido_em IS NULL RETURNING id`. `ativar_modo_sem_limite` usa `referencia = launch_id` e só vale para esse lançamento. `aprovar_hipotese` usa como `referencia` o id da hipótese. Pedido de outra sessão, ou já consumido, é recusado. Um teste cobre a tentativa de reuso.
4. **Médio: ambiente filtrado e `.env`.** `src/config.py:8` chama `load_dotenv()` na importação, então o processo da sessão relê o `.env`. Os nomes da lista fixa do §1.4 são retirados de `os.environ` logo depois dessa carga, no processo da sessão (requisito 2 do parecer de `v18.7-background-sessions`). Um teste usa um `.env` que contém `TERMINAL_DATABASE_URL_FILE`.
5. **Baixo: arquivo de credencial.** O diretório tem modo `0700` e o arquivo é aberto com `O_NOFOLLOW`. Link simbólico e dono diferente de `os.getuid()` são recusados. O DSN nunca vai para log nem para mensagem de exceção: erros de conexão registram só host e papel.
6. **Baixo: inundação de pedidos.** Teto `GATE_MAX_PENDING_PER_SESSION` (sugestão: 20). Acima dele, a sessão registra o excesso como evento e não cria pedido, o que protege o pesquisador de um plano injetado que gere muitos `restricao_duvidosa`.
7. **Baixo: exibição.** `pergunta`, `resposta` e mensagens passam por `sanitize_text` também na exibição, não só na gravação, porque a tabela é gravável pela sessão. No `decidir`, texto escrito por agente (por exemplo, o enunciado de uma hipótese) aparece rotulado como tal.
8. **Informativo: caixa de entrada.** As mitigações do §6 bastam. A mensagem vai ao provedor pelo `EgressGate` como texto do pesquisador, como a tarefa.

Pontos para o parecer:
- **Papel do terminal:** só `terminal_writer` resolve pedidos, grava mensagens e presença; a transição é condicional. Risco residual 1: o papel principal é superusuário (`POSTGRES_USER` da imagem oficial) e poderia, por código deliberado, `SET ROLE terminal_writer` ou desligar o gatilho; nenhum caminho do código faz isso, os agentes não executam código no host (ADR 014) e não há ferramenta de SQL livre. Endurecimento (Questão 1): rodar o processo da sessão com papel não superusuário, antes de produção (decisão do pesquisador, 2026-10-15).
- **Arquivo de credencial:** fora do repositório, `0600`, recusado com permissão mais aberta; nunca carregado pelo `load_dotenv`; inicialização falha se a credencial aparecer no ambiente. Risco residual 2 (ADR 023 §4.3): mesmo usuário de sistema operacional pode ler o arquivo; endurecimento opcional com usuário separado.
- **Ambiente filtrado:** lista fixa de nomes retirados do ambiente do processo da sessão (§1.4); teste confere que o processo não enxerga nenhum deles.
- **`stdin` removido:** todos os leitores dentro da sessão são substituídos pelo gate; teste com `StdinForbiddenError` no laço completo.
- **Injeção de prompt pela caixa de entrada:** a mensagem vem do pesquisador, mas pode colar texto de terceiros. Mitigações: tamanho limitado, controle removido, entrega delimitada como dado com instrução explícita, nunca resolve pedido reservado (só o gate), registrada no grafo para auditoria.
- **Texto do pedido:** montado de campos estruturados, sanitizado e filtrado para exibição; o pesquisador vê o mesmo que fica no banco.

## 7. Riscos e mitigações

1. **Superusuário contorna o gatilho** (§6). Mitigação nesta mudança: nenhum caminho de código; gatilhos com `session_user` e `current_user`; conferência em `pg_trigger` pelo terminal; teste estático com a lista completa do requisito "Garantias do gate escritas". Fechamento: mudança de endurecimento antes de produção (decisão do pesquisador, 2026-10-15; Questão 1).
2. **Pedido respondido por dois terminais.** Só há um REPL (`v18.7-background-sessions`), e a transição condicional recusa a segunda resposta.
3. **Resposta perdida entre gravação e consumo.** A sessão marca `consumido_em` só depois de aplicar; na queda, a sessão retomada reaplica (operações idempotentes por id de pedido).
4. **Ordem com `v18.7-exploration-limits`.** Os tipos `decidir_continuidade` e `restringir_direcao` existem no `CHECK` desde esta mudança; quem os produz (`v18.7-exploration-limits`) depende desta e é mergeada depois. Até lá, só `decidir_objetivo_atingido` (no `assisted`), `aprovar_hipotese` e `responder_pergunta_agente` têm produtor.
5. **`ask_researcher` esperando consome tempo do agente.** Limitado por `GATE_ASK_WAIT_SECONDS` e pela validação contra `AGENT_TIMEOUT_SECONDS`.

## 8. Questões em aberto

1. **Papel não superusuário para a sessão (encaminhada como mudança própria). Decidido pelo pesquisador em 2026-10-15: não é necessário até a produção; a versão atual é de desenvolvimento 0.0.** O gatilho protege contra defeito de código e contra ação conduzida por LLM, não contra código arbitrário no host com o mesmo usuário do sistema operacional ou com superusuário (requisito "Garantias do gate escritas"). Pelo parecer (item 2), fica fora desta mudança: uma mudança de endurecimento separada, a fazer antes de produção (decisão do pesquisador, 2026-10-15), sem prazo de versão e sem entrar em portão de entrega do roadmap, com as duas medidas juntas: papel de banco de aplicação não superusuário para o processo da sessão (sem gravar a resposta em `gate_requests` nem `INSERT` em `session_inbox` e `terminal_presence`, com `GRANT` nas tabelas e no esquema do AGE, mexendo na imagem e no `docker-compose.yml`) e usuário de sistema operacional separado para o processo da sessão, sem leitura do arquivo de credencial.
2. **Nó do grafo para a orientação:** esta spec usa `Decisao` (sem mudança de esquema do grafo). Um rótulo próprio (`Orientacao`) seria mais claro na consulta, mas exige mudança de esquema e vetorização. Qual o pesquisador prefere?
3. **`GATE_ASK_WAIT_SECONDS=120`:** o pesquisador prefere que o agente espere mais (com o tempo do agente pausado durante a espera, o que muda o runtime) ou que nunca espere e só registre?
4. **Comandos de CLI fora do REPL** (`geminiclaw vocab approve` etc.) passam a exigir o arquivo de credencial. Em máquinas sem a migração, falham com a mensagem do comando de migração. Aceitável?
5. **Catálogo de pedidos com `v18.7-exploration-limits`.** Decidido pelo pesquisador em 2026-10-15: o agrupamento do §1.1 (três decisões com `motivo`) está aceito, sem uma `decisao` por motivo. Regra adotada: o catálogo do §1.1; as duas mudanças ficam consistentes.
