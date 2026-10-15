# ADR 023 — Pesquisa em Segundo Plano com Acompanhamento pelo Terminal

**Status:** Proposto
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md` (criado junto com as mudanças OpenSpec)
**ADRs relacionados:** ADR 005 (persistência), ADR 010 (assistente de pesquisa), ADR 012 §8 (decisões
reservadas ao pesquisador), ADR 014 (agentes em processo, sandbox de código), ADR 019 (localidade e
egresso), ADR 021 §5 (limites e parada pelo objetivo), ADR 022 (contrato de contexto por chamada)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 010 | A sessão de pesquisa iniciada pelo REPL deixa de ocupar o terminal: roda num processo próprio, e o terminal vira o lugar de conversar e acompanhar (§1–§3). |
| 012 §8 | O gate de decisões reservadas passa a ser persistente e só o terminal o responde (§4); `DECISOES_RESERVADAS` ganha os pedidos que hoje leem o terminal dentro da sessão (§4.1). |
| 014 | Os agentes continuam em processo, mas no processo da sessão, não no do terminal (§1). |
| Spec `session-continuity` | Detecção de sessão parada pelo terminal, recusa de reativar sessão já continuada, verificação do PID e do laço de eventos (§6). |
| Spec `researcher-consult` | O Researcher passa a responder ao pesquisador durante a execução, em modo só leitura (§3), além de responder a `ask_researcher`. |
| Spec `benchmark` | O runner continua usando o comando direto em primeiro plano (§1). |
| Spec `hypothesis-loop` | A aprovação em lote do `assisted` e a confirmação de solução no `assisted` passam pelo gate persistente (§4.1). |

---

## Contexto

### Decisão do pesquisador (2026-10-15)

> A sessão deve ficar livre, mas o trabalho deve ocorrer em segundo plano, como uma visualização à parte,
> como acontece no Claude Code quando novos subagentes são instanciados. Assim, pequenas atualizações
> aparecem no terminal enquanto o pesquisador pode continuar trabalhando e conversando com os agentes.

### Por que agora

O ADR 021 §5 remove os tetos de hipóteses e de ciclos e permite, por decisão do pesquisador, desligar os
limites de custo, tokens, tempo e egresso: uma exploração pode durar horas. Hoje, `execute_prompt` é
aguardado dentro do REPL (`src/cli.py:1249-1318`): enquanto a sessão roda, o pesquisador não digita nada.
Várias decisões leem a entrada padrão de dentro da sessão: aprovação de hipóteses no `assisted`
(`terminal_approver`, `src/knowledge/hypothesis_cycle.py:577`), confirmação de solução
(`src/exploration.py:129-155`), `ask_researcher` no `assisted` (`src/orchestrator.py:1468`). O gate de decisões reservadas
(`src/human_gate.py`) guarda os pedidos em memória: uma sessão longa sem ninguém diante do terminal fica
parada, e um pedido se perde se o processo cair.

O que já existe e este ADR reaproveita: estado da sessão no PostgreSQL (`agent_sessions`), batimento em
thread própria (`src/heartbeat.py`), retomada de sessão interrompida (`resume`, `continue_project`),
fechamento gracioso com checkpoint.

---

## Decisão

### 1. A sessão iniciada pelo REPL roda num processo próprio

No REPL, iniciar uma pesquisa cria um **processo de sessão** separado do terminal, que executa o
orquestrador, os agentes e o laço autônomo como hoje. O processo:

- não depende do terminal: fechar o REPL não interrompe a pesquisa;
- registra o PID, o início e o batimento na própria sessão;
- grava o progresso como eventos (§2);
- nunca lê da entrada padrão: tudo o que hoje pergunta no terminal passa a ser pedido ao gate (§4).

O que precisa de confirmação **antes** de a pesquisa começar (editar e confirmar o Problema, confirmar o
modo sem limite) continua no terminal, antes de criar o processo.

O **comando direto** (`geminiclaw "tarefa"`) continua em primeiro plano por padrão, como hoje, para
scripts e para o benchmark (`scripts/benchmark/run_benchmark.py` espera o subprocesso terminar); uma
opção o manda para o segundo plano.

**Sessões simultâneas.** `MAX_CONCURRENT_SESSIONS` (padrão 1 no Pi 5, por memória e temperatura) define
quantas rodam ao mesmo tempo. Uma sessão além do limite espera na fila, e o terminal mostra a posição e a
sessão que ocupa a vaga. O pesquisador pode pausar uma sessão (libera a vaga), mudar a ordem da fila ou
iniciar acima do limite, com aviso de memória e temperatura.

### 2. Eventos de progresso

O PostgreSQL é o canal entre o processo da sessão e o terminal, sem infraestrutura nova (ADR 005). Os
eventos de progresso vão para uma **tabela própria, com escrita imediata** (não pelo buffer da
telemetria, que só grava a cada 50 registros, `src/telemetry.py:41`), indexada por sessão e ordem, com
retenção configurável. Cada evento tem tipo, momento e um resumo curto que passa pelos filtros de egresso
e de exibição (nada de dados brutos, ADR 019):

| Evento | Exemplo de linha no terminal |
|---|---|
| plano aprovado | `[iris-01] plano 2 aprovado: 5 subtarefas, 3 hipóteses` |
| subtarefa iniciada / concluída / reprovada | `[iris-01] treinar_rf concluída (acuracia 0,967, validada)` |
| hipótese criada / concluída | `[iris-01] h3 refutada (veredito −0,41)` |
| objetivo atingido | `[iris-01] objetivo atingido: acuracia 1,0 ≥ 0,95 (política: parar)` |
| decisão pendente | `[iris-01] aguarda você: aprovar a hipótese h4 (responda com 'decidir 12')` |
| parada | `[iris-01] encerrada: solucao_encontrada` |
| falha / interrupção | `[iris-01] interrompida: processo parou; use 'retomar iris-01'` |

O terminal lê os eventos novos por consulta periódica ou por notificação do PostgreSQL (a spec escolhe).
Um painel futuro (roadmap de frontend) consome os mesmos eventos.

### 3. O terminal: conversar e acompanhar

O REPL deixa de esperar a sessão terminar. Enquanto as pesquisas rodam:

- **pequenas atualizações** de cada sessão aparecem entre as interações, uma linha por evento, com o
  apelido curto da sessão, sem apagar o que o pesquisador está digitando; o nível de detalhe é
  configurável por sessão;
- **comandos de acompanhamento:** listar pesquisas (estado, tempo, custo, último evento, pedidos
  pendentes, posição na fila); acompanhar uma sessão (visualização detalhada à parte, até o pesquisador
  sair dela); pausar ao fim da subtarefa atual; retomar; parar (fechamento gracioso com checkpoint);
- **ações imediatas que não são decisões reservadas:** cancelar uma subtarefa que ainda não começou;
  pedir replanejamento ao fim da subtarefa atual;
- **conversar com os agentes:** o pesquisador pergunta sobre o projeto, as hipóteses e os resultados
  enquanto a sessão roda. Responde o Researcher em modo consulta, **só leitura** (conexão ao banco em
  transação somente leitura e cliente do Qdrant sem escrita). Quando a conversa vira orientação, o
  terminal propõe transformá-la em mensagem à sessão (§5), e o pesquisador confirma.

### 4. Gate persistente de decisões reservadas

1. **O que passa pelo gate.** Os pedidos de `DECISOES_RESERVADAS` (aprovar Oportunidade, confirmar
   Problema, aprovar termo, autorizar escrita em instrumento, ativar modo sem limite) e os que hoje leem o
   terminal dentro da sessão: aprovar hipótese no `assisted`; escolher encerrar ou continuar ao atingir o
   objetivo (política `perguntar`, ADR 021 §5.3); responder a `ask_researcher` no `assisted`; continuar,
   orientar ou parar em estagnação ou após planos rejeitados no `assisted`/`semi` (ADR 021 §5.5–§5.6).
   Nenhum caminho dentro do processo da sessão lê a entrada padrão.
2. **Persistência.** Os pedidos ficam no banco com estado `pendente` e sobrevivem à queda do processo da
   sessão e à do terminal.
3. **Quem responde.** Só o processo do terminal resolve pedidos. As respostas são gravadas por um **papel
   de banco próprio do terminal**, cujas credenciais o processo da sessão não carrega; a resposta é uma
   transição condicional (de `pendente` para `autorizada`/`negada`, só se ainda estiver `pendente`), o que
   resolve dois terminais respondendo ao mesmo tempo (vale a primeira). Uma mensagem de agente, um
   documento ou a caixa de entrada nunca autorizam (regra atual de `HUMAN_SOURCES`).
   A credencial desse papel fica num arquivo separado do `.env` principal, lido por uma função própria de
   `src/config.py` só no processo do terminal (o carregamento automático do `.env` na importação não a
   inclui), e o processo da sessão é iniciado com um ambiente filtrado, sem ela. Risco residual: os dois
   processos rodam com o mesmo usuário do sistema operacional, e código no host com esse usuário poderia ler
   o arquivo; os agentes não executam código no host (ADR 014: código só no sandbox), o que limita o risco.
   Um usuário de sistema separado para o processo da sessão fica como endurecimento opcional.
4. **A sessão não para por um pedido.** Enquanto um pedido está pendente, a sessão segue com o que não
   depende dele e só espera quando não houver mais nada a fazer. A espera não conta como ciclo ocioso nem
   como estagnação (ADR 021 §5.6). O terminal lembra o pedido periodicamente e o mostra na lista de
   pesquisas. Opcionalmente, depois de um prazo configurável de espera, a sessão pausa com checkpoint e
   libera a vaga.

### 5. Caixa de entrada da sessão

O pesquisador pode mandar uma mensagem a uma sessão em execução (orientação, nova ideia, novo insumo, "não
teste mais SVM"). A mensagem:

- só é gravada pelo processo do terminal, com o mesmo papel de banco do §4.3;
- tem tamanho limitado e é registrada no grafo como orientação do pesquisador, ligada à sessão;
- é entregue ao Researcher no próximo replanejamento, delimitada como dado, junto com o restante do
  contexto (ADR 022); para efeito imediato, o pesquisador usa as ações do §3;
- orienta o plano, mas não substitui as decisões reservadas: rejeitar uma hipótese continua sendo uma
  ação do gate, não uma frase na mensagem.

### 6. Falhas

- **Sessão parada.** O terminal (ao abrir e periodicamente) marca como `interrompida` a sessão cujo
  batimento envelheceu ou cujo PID não existe mais; hoje isso só acontece quando outro orquestrador inicia
  (`src/orchestrator.py:826`). O batimento só é aceito se o laço de eventos da sessão também deu sinal
  recente (não basta a thread do batimento estar viva). A retomada usa o mecanismo existente.
- **Duas instâncias.** Reativar uma sessão que já foi continuada por outra (`continued_by`) é recusado
  (hoje `reassert_active` não confere, `src/session.py:349-361`); o processo antigo que perde a sessão se
  encerra.
- **Terminal fechado:** nada acontece com a sessão; ao abrir de novo, o REPL mostra o resumo do que mudou.

### 7. Segurança e recursos

- O processo da sessão herda as barreiras de hoje: sandbox de código, filtros de egresso, localidade,
  segredos só por variáveis de ambiente.
- Eventos exibidos e respostas da consulta passam pelos filtros de exibição e egresso.
- No Pi 5, o processo da sessão e o do terminal competem por memória: cada um tem um orçamento de memória
  residente medido; o terminal carrega embeddings e clientes LLM só quando a consulta é usada.

### 8. Aprovações necessárias

Este ADR exige **alteração de schema** (tabelas de eventos de progresso, de pedidos do gate e da caixa de
entrada; papel de banco do terminal), que depende de aprovação explícita do pesquisador na mudança
OpenSpec correspondente (AGENTS.md §1.5).

---

## Consideradas e Rejeitadas

### A. Sessão como tarefa assíncrona dentro do processo do REPL
Mais simples (uma `asyncio.Task` por sessão). **Rejeitada:** fechar o terminal mata a pesquisa; uma
exploração de horas precisa sobreviver ao terminal.

### B. Serviço permanente (daemon) com API HTTP
Um servidor local que gerencia as sessões e serve o terminal e um futuro painel. **Não adotada agora:**
abre uma porta e uma API que precisam de autenticação e revisão de segurança; o banco já é um canal comum
e suficiente. Pode voltar quando o painel (frontend) for especificado.

### C. Fila de mensagens externa (Redis, RabbitMQ)
**Rejeitada:** infraestrutura nova no Pi 5 sem ganho sobre o PostgreSQL para o volume de eventos de uma
pesquisa.

### D. Manter o gate em memória e perguntar no terminal
**Rejeitada:** uma sessão sem terminal ficaria parada; um pedido se perderia com a queda do processo.

### E. Gate persistente gravável pelo processo da sessão
**Rejeitada na revisão:** os agentes rodam no processo da sessão; se ele pudesse gravar respostas, a
origem humana viraria uma coluna que qualquer código com as credenciais do banco escreve.

### F. Eventos pela telemetria existente (`agent_events`)
**Rejeitada na revisão:** a telemetria grava em lotes; um pedido "aguarda você" atrasaria ou se perderia
numa queda.

### G. Comando direto em segundo plano por padrão
**Rejeitada na revisão:** o benchmark e scripts esperam o processo terminar; o segundo plano é o padrão
do REPL e opção do comando direto.

---

## Consequências

### Positivas
- O pesquisador conversa com os agentes enquanto a pesquisa roda; explorações longas ficam viáveis.
- Decisões reservadas não se perdem e não travam a sessão inteira.
- A queda do terminal não afeta a pesquisa; a queda da sessão é detectada e retomável.
- Os eventos ficam prontos para um painel futuro.

### Negativas / Trade-offs
- Um processo a mais por sessão, três tabelas novas e um papel de banco a manter.
- O REPL passa a ter saída assíncrona intercalada com o que o pesquisador digita.
- Testes de integração precisam de processos separados.
- No Pi 5, duas pesquisas simultâneas podem não caber em memória; o padrão é uma.

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-background-sessions` | `session-continuity`, `agent-runtime`, `benchmark` | §1, §6, §7: processo da sessão, fila de sessões, PID, batimento com sinal do laço, recusa de reativar sessão continuada, comando direto em primeiro plano, orçamento de memória |
| `v18.7-session-events-terminal` | `session-continuity`, `researcher-consult` | §2, §3: tabela de eventos, atualizações no REPL, comandos e ações imediatas, consulta só leitura ao Researcher |
| `v18.7-persistent-human-gate` | `researcher-consult`, `hypothesis-loop` | §4, §5, §8: gate persistente, papel de banco do terminal, migração de todas as leituras da entrada padrão, caixa de entrada |

---

## Revisão

Revisar depois do primeiro uso com uma exploração de mais de uma hora no Pi 5: memória com o terminal
aberto, atraso das atualizações, pedidos ao gate respondidos e perdidos.
