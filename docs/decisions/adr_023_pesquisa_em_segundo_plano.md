# ADR 023 — Pesquisa em Segundo Plano com Acompanhamento pelo Terminal

**Status:** Aprovado (2026-10-15)
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md`
**ADRs relacionados:** ADR 005 (persistência), ADR 010 (assistente de pesquisa), ADR 012 §8 (decisões reservadas ao pesquisador), ADR 014 (agentes em processo, sandbox de código), ADR 017 (provedores de LLM), ADR 019 (localidade e egresso), ADR 021 §5 (limites e parada pelo objetivo), ADR 022 (contrato de contexto por chamada)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 010 | A sessão de pesquisa iniciada pelo REPL deixa de ocupar o terminal: roda num processo próprio, e o terminal vira o lugar de conversar e acompanhar (§1–§3). |
| 012 §8 | O gate de decisões reservadas passa a ser persistente e só o terminal o responde (§4); `DECISOES_RESERVADAS` ganha os pedidos que hoje leem o terminal dentro da sessão (§4.1). |
| 014 | Os agentes continuam em processo, mas no processo da sessão, não no do terminal (§1). O monitor de recursos do runtime deixa de ser específico do Raspberry Pi (§1.1); o texto do ADR 014 não muda. |
| 017 §4 | A prioridade padrão de provedores deixa de depender de `DEPLOYMENT_PROFILE=pi5`, que é removida; quem quiser outra ordem declara `LLM_PROVIDER_PRIORITY` (§1.1, item 3). |
| Spec `session-continuity` | Processo da sessão, fim da sessão conforme o modo, estados `aguarda_pesquisador` e `suspensa_sem_pesquisador`, presença do terminal, pergunta de retomada ao abrir o REPL (§1, §1.2); detecção de sessão parada, recusa de reativar sessão já continuada (§6). |
| Spec `researcher-consult` | O Researcher passa a responder ao pesquisador durante a execução, em modo só leitura (§3), além de responder a `ask_researcher`. |
| Spec `hypothesis-loop` | A aprovação em lote do `assisted` e a confirmação de solução no `assisted` passam pelo gate persistente (§4.1). |
| Spec `agent-runtime` | Monitor de recursos multiplataforma, sem valores fixos fora do Linux (§1.1). |
| Spec `llm-providers` | Prioridade padrão de provedores sem perfil de máquina (§1.1, item 3). |
| Spec `benchmark` | O runner continua usando o comando direto em primeiro plano (§1). |

---

## Contexto

### Decisões do pesquisador (2026-10-15)

A sessão deve ficar livre, mas o trabalho deve ocorrer em segundo plano, como uma visualização à parte, como acontece no Claude Code quando novos subagentes são instanciados. Assim, pequenas atualizações aparecem no terminal enquanto o pesquisador pode continuar trabalhando e conversando com os agentes.

Nos modos autônomos, o laço deve executar toda a exploração e encerrar o processo ao terminar. Numa pesquisa acompanhada pelo pesquisador, quando o terminal estiver fechado, a sessão registra o estado da pesquisa no banco e, quando o pesquisador voltar à aplicação, ele é avisado e perguntado se deseja retomar a exploração que não foi finalizada.

Os limites de recursos não podem ser específicos do Raspberry Pi: o sistema roda em máquinas de configurações diferentes, e as variáveis de ambiente perdem a designação do Pi.

Na revisão deste ADR, o pesquisador decidiu adiar tudo o que só serve a várias pesquisas simultâneas disputando a máquina (agente de admissão, fila, reservas, mais de um terminal): hoje há um pesquisador e uma pesquisa por vez. O desenho adiado está em "Evolução prevista".

### Por que agora

O ADR 021 §5 remove os tetos de hipóteses e de ciclos e permite, por decisão do pesquisador, desligar os limites de custo, tokens, tempo e egresso: uma exploração pode durar horas. Hoje, `execute_prompt` é aguardado dentro do REPL (`src/cli.py:1249-1318`): enquanto a sessão roda, o pesquisador não digita nada. Várias decisões leem a entrada padrão de dentro da sessão: aprovação de hipóteses no `assisted` (`terminal_approver`, `src/knowledge/hypothesis_cycle.py:577`), confirmação de solução (`src/exploration.py:129-155`), `ask_researcher` no `assisted` (`src/orchestrator.py:1468`). O gate de decisões reservadas (`src/human_gate.py`) guarda os pedidos em memória: uma sessão longa sem ninguém diante do terminal fica parada, e um pedido se perde se o processo cair.

O que já existe e este ADR reaproveita: estado da sessão no PostgreSQL (`agent_sessions`), batimento em thread própria (`src/heartbeat.py`), retomada de sessão interrompida (`resume`, `continue_project`), fechamento gracioso com checkpoint.

---

## Decisão

### 1. A sessão iniciada pelo REPL roda num processo próprio

No REPL, iniciar uma pesquisa cria um **processo de sessão** separado do terminal, que executa o orquestrador, os agentes e o laço autônomo como hoje. O processo:

- nos modos `semi` e `auto`, não depende do terminal: fechar o REPL não interrompe a pesquisa, que roda até o fim e encerra o processo; no `assisted`, a sessão se suspende quando o pesquisador sai (§1.2);
- registra o PID, o início e o batimento na própria sessão;
- grava o progresso como eventos (§2);
- nunca lê da entrada padrão: tudo o que hoje pergunta no terminal passa a ser pedido ao gate (§4).

O que precisa de confirmação **antes** de a pesquisa começar (editar e confirmar o Problema, confirmar o modo sem limite) continua no terminal, antes de criar o processo.

**Antes de iniciar ou retomar uma pesquisa,** o terminal confere a memória disponível medida (§1.1). Abaixo de `MIN_AVAILABLE_MEMORY_MB`, avisa quanto há disponível e quais pesquisas estão rodando, e o pesquisador decide se inicia mesmo assim ou desiste. Não há fila nem número fixo de pesquisas simultâneas.

O **comando direto** (`geminiclaw "tarefa"`) continua em primeiro plano por padrão, como hoje, para scripts e para o benchmark (`scripts/benchmark/run_benchmark.py` espera o subprocesso terminar); uma opção o manda para o segundo plano. Abaixo do mínimo de memória, o comando direto falha antes de começar, com mensagem e código de saída explícitos, porque não há ninguém para decidir. O benchmark roda uma sessão por vez, para que os tempos sejam comparáveis.

### 1.1 Monitor de recursos e configuração sem designação de máquina

1. **Monitor multiplataforma.** A leitura atual (`src/health.py`, usada por `src/agent_runtime/resources.py` e `src/autonomous_loop.py`) é específica do Raspberry Pi: lê `/proc` e `thermal_zone0`, chama `vcgencmd` por subprocesso em `is_throttled` e, fora do Linux, devolve valores fixos (temperatura 45,0, memória 8192/4096 MB, sem limitação), o que é um dado inventado (AGENTS.md §1.6). Ela passa a ser um monitor multiplataforma (`HealthMonitor`) para Linux e macOS, por uma biblioteca de leitura de recursos declarada como dependência pela spec, sem chamar comandos externos. Um valor que a plataforma não expõe (por exemplo, a temperatura no macOS) vem como desconhecido, nunca estimado nem fixo, e quem o consome trata o desconhecido explicitamente.
2. **Limites.** `MIN_AVAILABLE_MEMORY_MB` mantém o padrão de 512 MB: é o mínimo para iniciar uma pesquisa (§1) e para iniciar um agente dentro da sessão, como hoje. `TEMPERATURE_LIMIT` não tem padrão: sem valor, a temperatura não entra nas verificações; com valor, vale como hoje o limite do Pi. A limitação térmica registrada na telemetria (`is_throttled`) deixa de usar `vcgencmd` e passa a ser a temperatura frente a `TEMPERATURE_LIMIT`; sem limite ou sem leitura, fica desconhecida. O aviso de temperatura fixo em 70 °C (`src/agent_runtime/resources.py:89`) passa a derivar de `TEMPERATURE_LIMIT`. O limite de agentes simultâneos (`calculate_dynamic_limit`) mantém as faixas atuais, mas deixa de usar o padrão silencioso de 3 quando não lê a memória: sem leitura, vale `MAX_CONCURRENT_AGENTS`, com aviso explícito.
3. **Variáveis sem designação de máquina.**

   | Hoje | Passa a ser |
   |---|---|
   | `PI_TEMPERATURE_LIMIT` | `TEMPERATURE_LIMIT` |
   | `PI_MIN_AVAILABLE_MEMORY_MB` | `MIN_AVAILABLE_MEMORY_MB` |
   | `DEPLOYMENT_PROFILE` (`default` ou `pi5`) | removida |

   O perfil `pi5` mudava quatro padrões (`src/config.py:135-153`, `src/llm/availability.py:32-35`): `MAX_SUBTASKS_PER_TASK` (5 em vez de 10), `MAX_CONCURRENT_AGENTS` (2 em vez de 3), `AGENT_TIMEOUT_SECONDS` (sem limite em vez de 300) e a ordem de `LLM_PROVIDER_PRIORITY` (provedores locais primeiro). Sem o perfil, valem os padrões gerais, e cada máquina declara no próprio `.env` o que quiser diferente. Para que o "sem limite" possa ser declarado, `AGENT_TIMEOUT_SECONDS=0` passa a significar sem tempo limite (hoje o valor lido do ambiente é convertido com `int` e não há como expressá-lo). `parse_priority` deixa de receber o perfil (`src/llm/session.py:256,279`).

   Sem nomes antigos aceitos como sinônimo: se um nome removido estiver definido no ambiente, a inicialização falha com a mensagem do nome novo, em vez de ignorá-lo em silêncio. Como o `.env.example` traz hoje `DEPLOYMENT_PROFILE=default` e as duas variáveis `PI_*`, todo `.env` derivado dele precisa ser migrado, em qualquer máquina; a mensagem de erro diz o que fazer em cada caso (com `DEPLOYMENT_PROFILE=default`, só remover a linha). O `.env` do Raspberry Pi usado nos testes é migrado junto com a mudança, declarando explicitamente os quatro valores do antigo perfil, `TEMPERATURE_LIMIT` e `MIN_AVAILABLE_MEMORY_MB` com os valores efetivos de hoje. A classe `PiHealthMonitor` passa a se chamar `HealthMonitor`. Continuam, por não serem configuração: a detecção de plataforma para escolher imagens (`src/platform_info.py`, `scripts.platform_images`) e os scripts de instalação no Pi (`scripts/setup_pi.sh`, `scripts/setup_ollama_pi5.sh`).

### 1.2 Fim da sessão e ausência do pesquisador, conforme o modo

1. **Modos `semi` e `auto`: a exploração roda até o fim e o processo se encerra.** O laço executa a exploração inteira sem depender do terminal. Ao chegar a um motivo de parada do ADR 021 §5 (objetivo atingido com a política `parar`, limite de custo, tokens, tempo ou egresso, saturação, planos rejeitados), a sessão grava o motivo de parada, o relatório e o evento final e encerra o processo. O processo nunca fica vivo sem trabalho: se só restarem pedidos ao pesquisador (por exemplo, a política `perguntar` ao atingir o objetivo, intervenções esgotadas ou uma decisão reservada), a sessão grava checkpoint, passa ao estado `aguarda_pesquisador` e encerra o processo, em vez de esperar com ele vivo. A resposta do pesquisador no terminal reabre a sessão pelo mecanismo de retomada (item 3).
2. **Modo `assisted`: a sessão acompanha a presença do pesquisador.** O processo do terminal registra a presença no banco com batimento próprio, gravado pelo papel de banco do terminal (§4.3). Quando o terminal fecha, seja pela saída normal (que avisa a sessão) ou por queda (o batimento de presença envelhece além de um prazo configurável), a sessão `assisted` termina a subtarefa em curso, sem interrompê-la no meio, grava checkpoint e o estado da pesquisa (plano, hipóteses e seus estados, pedidos pendentes, último evento, custo até ali), passa ao estado `suspensa_sem_pesquisador` e encerra o processo.
3. **Ao abrir a aplicação.** O REPL mostra o resumo do que mudou desde a última vez e lista as pesquisas não finalizadas (`suspensa_sem_pesquisador`, `aguarda_pesquisador`, `interrompida`), com os pedidos pendentes de cada uma, e pergunta se o pesquisador deseja retomar cada exploração. Retomar cria um novo processo de sessão pelo mecanismo existente (`resume`), com a verificação de memória do §1. Não retomar mantém a sessão como está; o pesquisador pode também encerrá-la explicitamente, com relatório. Pesquisas autônomas concluídas aparecem só no resumo.
4. **Comando direto em primeiro plano.** O próprio comando é o terminal: a sessão termina quando a exploração termina, como no item 1, e interromper o comando (Ctrl+C) faz o fechamento gracioso com checkpoint, como hoje.
5. **Um terminal por vez.** Abrir o REPL com outro terminal já presente é recusado com aviso; o adiamento de vários terminais está em "Evolução prevista".

### 2. Eventos de progresso

O PostgreSQL é o canal entre o processo da sessão e o terminal, sem infraestrutura nova (ADR 005). Os eventos de progresso vão para uma **tabela própria, com escrita imediata** (não pelo buffer da telemetria, que só grava a cada 50 registros, `src/telemetry.py:41`), indexada por sessão e ordem, com retenção configurável. Cada evento tem tipo, momento e um resumo curto que passa pelos filtros de egresso e de exibição (nada de dados brutos, ADR 019):

| Evento | Exemplo de linha no terminal |
|---|---|
| plano aprovado | `[iris-01] plano 2 aprovado: 5 subtarefas, 3 hipóteses` |
| subtarefa iniciada / concluída / reprovada | `[iris-01] treinar_rf concluída (acuracia 0,967, validada)` |
| hipótese criada / concluída | `[iris-01] h3 refutada (veredito −0,41)` |
| objetivo atingido | `[iris-01] objetivo atingido: acuracia 1,0 ≥ 0,95 (política: parar)` |
| decisão pendente | `[iris-01] aguarda você: aprovar a hipótese h4 (responda com 'decidir 12')` |
| parada | `[iris-01] encerrada: solucao_encontrada` |
| suspensão | `[iris-01] suspensa: terminal fechado; retome ao abrir a aplicação` |
| falha / interrupção | `[iris-01] interrompida: processo parou; use 'retomar iris-01'` |

O terminal lê os eventos novos por consulta periódica ou por notificação do PostgreSQL (a spec escolhe). Um painel futuro (roadmap de frontend) consome os mesmos eventos.

### 3. O terminal: conversar e acompanhar

O REPL deixa de esperar a sessão terminar. Enquanto a pesquisa roda:

- **pequenas atualizações** aparecem entre as interações, uma linha por evento, com o apelido curto da sessão, sem apagar o que o pesquisador está digitando; o nível de detalhe é configurável;
- **comandos de acompanhamento:** listar pesquisas (estado, tempo, custo, último evento, pedidos pendentes); acompanhar uma sessão (visualização detalhada à parte, até o pesquisador sair dela); pausar ao fim da subtarefa atual; retomar; parar (fechamento gracioso com checkpoint);
- **ações imediatas que não são decisões reservadas:** cancelar uma subtarefa que ainda não começou; pedir replanejamento ao fim da subtarefa atual;
- **conversar com os agentes:** o pesquisador pergunta sobre o projeto, as hipóteses e os resultados enquanto a sessão roda. Responde o Researcher em modo consulta, **só leitura** (conexão ao banco em transação somente leitura e cliente do Qdrant sem escrita). Quando a conversa vira orientação, o terminal propõe transformá-la em mensagem à sessão (§5), e o pesquisador confirma.

### 4. Gate persistente de decisões reservadas

1. **O que passa pelo gate.** Os pedidos de `DECISOES_RESERVADAS` (aprovar Oportunidade, confirmar Problema, aprovar termo, autorizar escrita em instrumento, ativar modo sem limite) e os que hoje leem o terminal dentro da sessão: aprovar hipótese no `assisted`; escolher encerrar ou continuar ao atingir o objetivo (política `perguntar`, ADR 021 §5.3); responder a `ask_researcher` no `assisted`; continuar, orientar ou parar em estagnação no `assisted`, em saturação, intervenções esgotadas ou planos rejeitados (ADR 021 §5.5–§5.6); restringir uma direção (ADR 021 §5.5). Nenhum caminho dentro do processo da sessão lê a entrada padrão.
2. **Persistência.** Os pedidos ficam no banco com estado `pendente` e sobrevivem à queda do processo da sessão e à do terminal.
3. **Quem responde.** Só o processo do terminal resolve pedidos. As respostas são gravadas por um **papel de banco próprio do terminal**, cujas credenciais o processo da sessão não carrega; a resposta é uma transição condicional (de `pendente` para `autorizada`/`negada`, só se ainda estiver `pendente`). Uma mensagem de agente, um documento ou a caixa de entrada nunca autorizam (regra atual de `HUMAN_SOURCES`). A credencial desse papel fica num arquivo separado do `.env` principal, lido por uma função própria de `src/config.py` só no processo do terminal (o carregamento automático do `.env` na importação não a inclui), e o processo da sessão é iniciado com um ambiente filtrado, sem ela. Risco residual: os dois processos rodam com o mesmo usuário do sistema operacional, e código no host com esse usuário poderia ler o arquivo; os agentes não executam código no host (ADR 014: código só no sandbox), o que limita o risco. Um usuário de sistema separado para o processo da sessão fica como endurecimento opcional.
4. **A sessão não para por um pedido.** Enquanto um pedido está pendente, a sessão segue com o que não depende dele e só espera quando não houver mais nada a fazer. A espera não conta como ciclo ocioso nem como estagnação (ADR 021 §5.6). O terminal lembra o pedido periodicamente e o mostra na lista de pesquisas. Quando só restam pedidos pendentes: nos modos `semi` e `auto`, a sessão passa a `aguarda_pesquisador` e encerra o processo (§1.2, item 1); no `assisted`, com o terminal aberto, espera.

### 5. Caixa de entrada da sessão

O pesquisador pode mandar uma mensagem a uma sessão em execução (orientação, nova ideia, novo insumo, "não teste mais SVM"). A mensagem:

- só é gravada pelo processo do terminal, com o mesmo papel de banco do §4.3;
- tem tamanho limitado e é registrada no grafo como orientação do pesquisador, ligada à sessão;
- é entregue ao Researcher no próximo replanejamento, delimitada como dado, junto com o restante do contexto (ADR 022); para efeito imediato, o pesquisador usa as ações do §3;
- orienta o plano, mas não substitui as decisões reservadas: rejeitar uma hipótese continua sendo uma ação do gate, não uma frase na mensagem.

### 6. Falhas

- **Sessão parada.** O terminal (ao abrir e periodicamente) marca como `interrompida` a sessão cujo batimento envelheceu ou cujo PID não existe mais; hoje isso só acontece quando outro orquestrador inicia (`src/orchestrator.py:826`). O batimento só é aceito se o laço de eventos da sessão também deu sinal recente (não basta a thread do batimento estar viva). A retomada usa o mecanismo existente.
- **Duas instâncias.** Reativar uma sessão que já foi continuada por outra (`continued_by`) é recusado (hoje `reassert_active` não confere, `src/session.py:349-361`); o processo antigo que perde a sessão se encerra.
- **Terminal fechado:** nos modos `semi` e `auto`, nada acontece com a sessão; no `assisted`, a sessão se suspende (§1.2, item 2). Ao abrir de novo, o REPL mostra o resumo e pergunta sobre as pesquisas não finalizadas (§1.2, item 3).

### 7. Segurança e recursos

- O processo da sessão herda as barreiras de hoje: sandbox de código, filtros de egresso, localidade, segredos só por variáveis de ambiente.
- Eventos exibidos e respostas da consulta passam pelos filtros de exibição e egresso.
- O processo da sessão e o do terminal competem por memória na mesma máquina; o terminal carrega embeddings e clientes LLM só quando a consulta os usa.

### 8. Aprovações necessárias

Este ADR exige **alteração de schema** (tabelas de eventos de progresso, de pedidos do gate e da caixa de entrada; PID e os estados `aguarda_pesquisador` e `suspensa_sem_pesquisador` na sessão; presença do terminal; papel de banco do terminal), que depende de aprovação explícita do pesquisador na mudança OpenSpec correspondente (AGENTS.md §1.5).

---

## Consideradas e Rejeitadas

### A. Sessão como tarefa assíncrona dentro do processo do REPL
Mais simples (uma `asyncio.Task` por sessão). **Rejeitada:** fechar o terminal mata a pesquisa; uma exploração de horas precisa sobreviver ao terminal.

### B. Serviço permanente (daemon) com API HTTP
Um servidor local que gerencia as sessões e serve o terminal e um futuro painel. **Não adotada agora:** abre uma porta e uma API que precisam de autenticação e revisão de segurança; o banco já é um canal comum e suficiente. Pode voltar quando o painel (frontend) for especificado.

### C. Fila de mensagens externa (Redis, RabbitMQ)
**Rejeitada:** infraestrutura nova sem ganho sobre o PostgreSQL para o volume de eventos de uma pesquisa.

### D. Manter o gate em memória e perguntar no terminal
**Rejeitada:** uma sessão sem terminal ficaria parada; um pedido se perderia com a queda do processo.

### E. Gate persistente gravável pelo processo da sessão
**Rejeitada na revisão:** os agentes rodam no processo da sessão; se ele pudesse gravar respostas, a origem humana viraria uma coluna que qualquer código com as credenciais do banco escreve.

### F. Eventos pela telemetria existente (`agent_events`)
**Rejeitada na revisão:** a telemetria grava em lotes; um pedido "aguarda você" atrasaria ou se perderia numa queda.

### G. Comando direto em segundo plano por padrão
**Rejeitada na revisão:** o benchmark e scripts esperam o processo terminar; o segundo plano é o padrão do REPL e opção do comando direto.

### H. Número fixo de sessões simultâneas
Um `MAX_CONCURRENT_SESSIONS` com padrão 1. **Rejeitada:** o padrão vinha de uma suposição sobre o Raspberry Pi 5, não de medição, e o sistema roda em máquinas diferentes. A verificação de memória do §1 cobre o uso atual sem número fixo.

### I. Agente de admissão com fila, reservas e vários terminais
Desenhada na revisão deste ADR (ver "Evolução prevista"). **Adiada por decisão do pesquisador:** só serve a várias pesquisas disputando a máquina, o que ainda não acontece, e concentrava quase todos os modos de falha achados na revisão adversarial.

---

## Consequências

### Positivas
- O pesquisador conversa com os agentes enquanto a pesquisa roda; explorações longas ficam viáveis.
- Decisões reservadas não se perdem e não travam a sessão inteira.
- Nos modos autônomos, a queda do terminal não afeta a pesquisa, que roda até o fim e libera a máquina ao terminar; no `assisted`, nada roda sem o pesquisador, e a pesquisa é retomada de onde parou; a queda da sessão é detectada e retomável.
- O monitor de recursos deixa de inventar valores fora do Linux, e nenhuma configuração fica atrelada a uma máquina.
- Os eventos ficam prontos para um painel futuro.

### Negativas / Trade-offs
- Um processo a mais por pesquisa, três tabelas novas, colunas novas na sessão e um papel de banco a manter.
- O REPL passa a ter saída assíncrona intercalada com o que o pesquisador digita.
- Testes de integração precisam de processos separados.
- Pesquisas simultâneas são possíveis, mas sem coordenação: a verificação de memória só acontece ao iniciar, e o pesquisador decide o que fazer abaixo do mínimo.
- Todo `.env` derivado do `.env.example` precisa ser migrado; a inicialização falha se encontrar os nomes antigos.

---

## Evolução prevista

Quando o uso real mostrar várias pesquisas disputando a mesma máquina, o desenho adiado na revisão deste ADR é o ponto de partida: ferramentas só de leitura do orquestrador (`recursos_do_sistema`, `uso_das_sessoes`, `historico_de_consumo`, `estado_dos_provedores`), com que o Researcher decide admitir ou aguardar uma nova pesquisa; fila de sessões sem processo próprio; admissão como transição condicional no banco, sob trava, com reserva de memória para as sessões recém-admitidas; espera abaixo do mínimo sem falhar a subtarefa, com pausa automática depois de um prazo; mais de um terminal aberto. As funções seriam fixas, sem acesso livre do agente ao terminal do host (ADR 014). O histórico do desenho está no histórico deste arquivo.

---

## Casos de uso e testes de aceite

Cada caso vira ao menos um cenário na spec da mudança OpenSpec correspondente e um teste. Os testes de integração rodam o processo da sessão de verdade, em processo separado, com PostgreSQL real e provedores LLM simulados por respostas gravadas (sem chamadas pagas); o sandbox de código só entra onde o caso exige.

| # | Caso | Como o teste verifica | Tipo |
|---|---|---|---|
| 1 | Pesquisa `auto` em segundo plano chega ao objetivo com a política `parar` | Inicia pelo REPL, fecha o terminal; o processo da sessão grava `solucao_encontrada`, o relatório e o evento final, e o PID deixa de existir sem intervenção | integração |
| 2 | Pesquisa `auto` para por limite (custo, tokens ou tempo) | Limite baixo; motivo de parada correto, checkpoint gravado, processo encerrado | integração |
| 3 | Pesquisa `semi` ou `auto` fica só com pedidos pendentes (política `perguntar`) | Estado `aguarda_pesquisador`, checkpoint gravado, processo encerrado; a resposta no terminal reabre a sessão e ela continua do checkpoint | integração |
| 4 | Pesquisa `assisted`: o terminal sai normalmente | A subtarefa em curso termina; estado `suspensa_sem_pesquisador` com plano, hipóteses e pedidos gravados; processo encerrado | integração |
| 5 | Pesquisa `assisted`: o terminal cai (processo morto) | O batimento de presença envelhece; a sessão se suspende como no caso 4, sem interromper a subtarefa no meio | integração |
| 6 | Segundo terminal aberto com um já presente | Recusado com aviso | unidade |
| 7 | Reabrir a aplicação com pesquisas não finalizadas | O REPL lista as sessões `suspensa_sem_pesquisador`, `aguarda_pesquisador` e `interrompida`, com os pedidos pendentes, e pergunta sobre a retomada de cada uma; pesquisas concluídas aparecem só no resumo | unidade (REPL com entrada simulada) |
| 8 | Retomar a exploração | Cria um processo novo pelo `resume`, segue do checkpoint sem repetir subtarefas concluídas; a sessão antiga fica com `continued_by` | integração |
| 9 | Não retomar, ou encerrar explicitamente | Não retomar mantém o estado; encerrar grava relatório e motivo de parada | unidade |
| 10 | Processo da sessão morre no meio (SIGKILL) | O terminal marca `interrompida` pelo PID ou pelo batimento e oferece a retomada (caso 7) | integração |
| 11 | Reativar uma sessão já continuada | Recusado; o processo antigo se encerra | unidade |
| 12 | Comando direto em primeiro plano | Termina quando a exploração termina, com o código de saída do motivo de parada; Ctrl+C faz o fechamento gracioso com checkpoint | integração |
| 13 | Decisão reservada respondida pelo terminal | Só o papel do terminal grava a resposta; o processo da sessão não consegue gravar; resposta a pedido já resolvido é recusada | integração |
| 14 | Iniciar pesquisa pelo REPL com memória abaixo do mínimo | O terminal avisa a memória disponível e as pesquisas em execução; o pesquisador inicia mesmo assim ou desiste | unidade (leituras simuladas) |
| 15 | Comando direto com memória abaixo do mínimo | Falha antes de começar, com mensagem e código de saída explícitos | unidade |
| 16 | Nomes antigos de configuração no ambiente (`PI_*`, `DEPLOYMENT_PROFILE`) | A inicialização falha com a mensagem do nome novo | unidade |
| 17 | Monitor de recursos em plataforma sem uma leitura (temperatura no macOS) | O valor vem como desconhecido, nunca fixo, e as verificações ignoram a temperatura | unidade |

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-resource-monitor-config` | `agent-runtime`, `llm-providers`, `operation-metrics` | §1.1: monitor multiplataforma (substitui `PiHealthMonitor` em `src/health.py`, `src/agent_runtime/resources.py` e `src/autonomous_loop.py`; remove os valores fixos fora do Linux e o `vcgencmd`), `TEMPERATURE_LIMIT` opcional, remoção de `DEPLOYMENT_PROFILE` e do prefixo `PI_`, `AGENT_TIMEOUT_SECONDS=0`, migração do `.env.example`, do `.env` do Pi e dos testes |
| `v18.7-background-sessions` | `session-continuity`, `benchmark` | §1, §1.2, §6, §7: processo da sessão, verificação de memória ao iniciar, fim da sessão conforme o modo, presença do terminal, suspensão do `assisted`, pergunta de retomada ao abrir o REPL, PID, batimento com sinal do laço, recusa de reativar sessão continuada, comando direto em primeiro plano |
| `v18.7-session-events-terminal` | `session-continuity`, `researcher-consult` | §2, §3: tabela de eventos, atualizações no REPL, comandos e ações imediatas, consulta só leitura ao Researcher |
| `v18.7-persistent-human-gate` | `researcher-consult`, `hypothesis-loop` | §4, §5, §8: gate persistente, papel de banco do terminal, migração de todas as leituras da entrada padrão, caixa de entrada |

---

## Revisão

Revisar depois do primeiro uso com uma exploração de mais de uma hora, no Raspberry Pi 5 e em outra máquina: memória com o terminal aberto, atraso das atualizações, pedidos ao gate respondidos e perdidos, suspensões e retomadas do `assisted`, e se o uso real pede a evolução prevista.
