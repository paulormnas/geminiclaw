# ADR 023 — Pesquisa em Segundo Plano com Acompanhamento pelo Terminal

**Status:** Proposto
**Data:** 2026-10-15
**Autores:** Arquiteto de Soluções (GeminiClaw)
**Roadmaps relacionados:** `roadmaps/roadmap_V18.7.md` (criado junto com as mudanças OpenSpec)
**ADRs relacionados:** ADR 005 (persistência), ADR 010 (assistente de pesquisa), ADR 012 §8 (decisões reservadas ao pesquisador), ADR 014 (agentes em processo, sandbox de código), ADR 017 (provedores de LLM), ADR 019 (localidade e egresso), ADR 021 §5 (limites e parada pelo objetivo), ADR 022 (contrato de contexto por chamada)

**O que este ADR muda em outros ADRs:**

| ADR | Mudança |
|---|---|
| 010 | A sessão de pesquisa iniciada pelo REPL deixa de ocupar o terminal: roda num processo próprio, e o terminal vira o lugar de conversar e acompanhar (§1–§3). |
| 012 §8 | O gate de decisões reservadas passa a ser persistente e só o terminal o responde (§4); `DECISOES_RESERVADAS` ganha os pedidos que hoje leem o terminal dentro da sessão (§4.1). |
| 014 | Os agentes continuam em processo, mas no processo da sessão, não no do terminal (§1). O controle de recursos do runtime (`ResourceGuard`) deixa de ser específico do Raspberry Pi (§1.1); o texto do ADR 014 não muda. |
| 017 §4 | A prioridade padrão de provedores deixa de depender de `DEPLOYMENT_PROFILE=pi5`, que é removida; quem quiser outra ordem declara `LLM_PROVIDER_PRIORITY` (§1.1, item 10). |
| Spec `session-continuity` | Detecção de sessão parada pelo terminal, recusa de reativar sessão já continuada, verificação do PID e do laço de eventos (§6). |
| Spec `researcher-consult` | O Researcher passa a responder ao pesquisador durante a execução, em modo só leitura (§3), além de responder a `ask_researcher`. |
| Spec `benchmark` | O runner continua usando o comando direto em primeiro plano (§1). |
| Spec `agent-runtime` | Monitor de recursos multiplataforma, limite de agentes pela memória recalculado a cada vaga, espera abaixo do piso sem falha da subtarefa (§1.1). |
| Spec `llm-providers` | Prioridade padrão de provedores sem perfil de máquina (§1.1, item 10). |
| Spec `operation-metrics` | `is_throttled` passa a vir do ponto de disparo passivo; custo de admissão registrado à parte (§1.1). |
| Spec `hypothesis-loop` | A aprovação em lote do `assisted` e a confirmação de solução no `assisted` passam pelo gate persistente (§4.1). |

---

## Contexto

### Decisão do pesquisador (2026-10-15)

A sessão deve ficar livre, mas o trabalho deve ocorrer em segundo plano, como uma visualização à parte, como acontece no Claude Code quando novos subagentes são instanciados. Assim, pequenas atualizações aparecem no terminal enquanto o pesquisador pode continuar trabalhando e conversando com os agentes.

### Por que agora

O ADR 021 §5 remove os tetos de hipóteses e de ciclos e permite, por decisão do pesquisador, desligar os limites de custo, tokens, tempo e egresso: uma exploração pode durar horas. Hoje, `execute_prompt` é aguardado dentro do REPL (`src/cli.py:1249-1318`): enquanto a sessão roda, o pesquisador não digita nada. Várias decisões leem a entrada padrão de dentro da sessão: aprovação de hipóteses no `assisted` (`terminal_approver`, `src/knowledge/hypothesis_cycle.py:577`), confirmação de solução (`src/exploration.py:129-155`), `ask_researcher` no `assisted` (`src/orchestrator.py:1468`). O gate de decisões reservadas (`src/human_gate.py`) guarda os pedidos em memória: uma sessão longa sem ninguém diante do terminal fica parada, e um pedido se perde se o processo cair.

O que já existe e este ADR reaproveita: estado da sessão no PostgreSQL (`agent_sessions`), batimento em thread própria (`src/heartbeat.py`), retomada de sessão interrompida (`resume`, `continue_project`), fechamento gracioso com checkpoint.

---

## Decisão

### 1. A sessão iniciada pelo REPL roda num processo próprio

No REPL, iniciar uma pesquisa cria um **processo de sessão** separado do terminal, que executa o orquestrador, os agentes e o laço autônomo como hoje. O processo:

- não depende do terminal: fechar o REPL não interrompe a pesquisa;
- registra o PID, o início e o batimento na própria sessão;
- grava o progresso como eventos (§2);
- nunca lê da entrada padrão: tudo o que hoje pergunta no terminal passa a ser pedido ao gate (§4).

O que precisa de confirmação **antes** de a pesquisa começar (editar e confirmar o Problema, confirmar o modo sem limite) continua no terminal, antes de criar o processo.

O **comando direto** (`geminiclaw "tarefa"`) continua em primeiro plano por padrão, como hoje, para scripts e para o benchmark (`scripts/benchmark/run_benchmark.py` espera o subprocesso terminar); uma opção o manda para o segundo plano. Em primeiro plano, o comando direto não entra na fila nem chama o agente de admissão, mas passa pela mesma transição condicional, sob a trava e com reserva (§1.1, item 6), e respeita o piso (§1.1, item 3.1). Abaixo dele, espera para começar com aviso e prazo próprio; vencido o prazo, falha com código de saída explícito, sem pausar nem ir para a fila. Enquanto espera, o comando fica registrado no banco com PID e batimento, e o avaliador não admite sessões da fila à frente dele; o registro de um comando que morreu expira pela detecção do §6. Em execução, vencido o prazo de espera abaixo do piso dentro da sessão (§1.1, item 4), o comando em primeiro plano grava checkpoint e sai com código de saída explícito, em vez de pausar e voltar à fila. Enquanto roda, conta como sessão ativa para as demais admissões. O benchmark roda uma sessão por vez, para que os tempos sejam comparáveis.

**Sessões simultâneas.** Quantas pesquisas rodam ao mesmo tempo não é um número fixo: o sistema roda em máquinas de configurações diferentes, e o que cabe depende da máquina e da carga de cada pesquisa. A admissão de uma nova sessão depende do uso medido dos recursos e, quando há disputa, da decisão de um agente (§1.1). Uma sessão não admitida espera na fila, e o terminal mostra a posição e o motivo. O pesquisador pode pausar uma sessão (libera recursos e a fila é reavaliada), mudar a ordem da fila ou admitir uma sessão manualmente: contra a decisão `aguardar` do agente, com confirmação explícita e aviso do risco; abaixo do piso (§1.1, item 3.1), nunca.

### 1.1 Admissão de sessões por leitura de recursos

1. **Monitor de recursos multiplataforma.** A leitura atual (`src/health.py`, usada por `src/agent_runtime/resources.py` e `src/autonomous_loop.py`) é específica do Raspberry Pi: lê `/proc` e `thermal_zone0`, chama `vcgencmd` por subprocesso em `is_throttled` e, fora do Linux, devolve valores fixos (temperatura 45,0, memória 8192/4096 MB, sem limitação), o que é um dado inventado (AGENTS.md §1.6). Ela passa a ser um monitor multiplataforma (`HealthMonitor`) para Linux e macOS, por uma biblioteca de leitura de recursos declarada como dependência pela spec, sem chamar comandos externos. Um valor que a plataforma não expõe vem como desconhecido, nunca estimado nem fixo. A limitação térmica deixa de usar `vcgencmd` e passa a ser a temperatura frente ao ponto de disparo passivo que o sistema operacional informa (o de redução de frequência, não os do ventilador nem o crítico); sem ele, fica desconhecida, e a coluna `is_throttled` da telemetria (`scripts/init_db.sql`, `src/telemetry.py`) passa a registrar essa comparação. Fontes de cada leitura: memória e CPU do processo pelo PID; contêineres de sandbox pela API do Docker (o SDK já é dependência), filtrados pelo rótulo da sessão; no macOS, a memória disponível ao Docker é a da máquina virtual do Docker Desktop, calculada como o total da máquina virtual menos o uso medido dos contêineres (a API do Docker não informa a disponível), informada à parte e verificada também pelo piso; temperatura no macOS, desconhecida.
2. **Ferramentas de recursos.** O orquestrador registra, sobre o monitor do item 1, ferramentas só de leitura, implementadas como funções fixas, sem execução de comandos no host (ADR 014):
   - `recursos_do_sistema`: memória total e disponível, uso de CPU, número de núcleos e carga média, temperatura e ponto de disparo quando expostos, espaço livre no diretório de dados, plataforma;
   - `uso_das_sessoes`: para cada sessão ativa, PID, memória residente atual e pico, uso de CPU, contêineres de sandbox ativos e a soma dos seus limites de memória frente à memória total, tempo e custo;
   - `historico_de_consumo`: pico de memória e de CPU de sessões anteriores, com o tipo de objetivo, para estimar a carga de uma sessão nova;
   - `estado_dos_provedores`: erros recentes de cota ou de limite de taxa (por exemplo, 429) por provedor, já que sessões simultâneas somam chamadas na mesma chave.
3. **Ordem da admissão.** A cada avaliação, para a primeira sessão da fila:
   1. **Piso determinístico.** Recusa quando a memória disponível, descontadas a reserva da sessão candidata e a das sessões já admitidas (item 6), fica abaixo de `MIN_AVAILABLE_MEMORY_MB`, e acima de `TEMPERATURE_LIMIT`, quando a temperatura é legível. O agente não ultrapassa o piso.
   2. **Teto opcional.** `MAX_CONCURRENT_SESSIONS` passa a existir como teto configurável, sem valor por padrão (sem teto); quando definido, vale antes do agente.
   3. **Admissão direta.** Sem nenhuma outra sessão ativa, a sessão é admitida sem chamar o agente: não há disputa a decidir, e esse é o uso mais comum.
   4. **Decisão do agente.** Com outras sessões ativas, o Researcher decide `admitir` ou `aguardar`, com justificativa, porque conhece o Problema confirmado e a carga que ele sugere (por exemplo, treino de modelos pesados no sandbox); a sessão na fila ainda não tem plano. Erro de cota recente no provedor da sessão é motivo de `aguardar` sem chamar o agente.
4. **Valores padrão.** `MIN_AVAILABLE_MEMORY_MB` mantém o padrão de 512 MB e é o mesmo valor que o controle de agentes dentro da sessão usa para esperar antes de iniciar um agente: nas duas situações significa não começar trabalho novo abaixo dessa margem. Dentro da sessão, a espera abaixo do piso deixa de falhar a subtarefa depois de 60 s (`wait_for_health`, `src/agent_runtime/resources.py:68-106`): com sessões simultâneas, uma sessão vizinha pode segurar memória por minutos. A sessão espera sem falhar a subtarefa, emite o evento "aguarda recursos", e a espera não conta como estagnação nem como reprovação (ADR 021 §5.6). Depois de um prazo configurável, com padrão definido na spec, a sessão pausa com checkpoint, como no §4.4, libera a memória e volta à fila; assim, duas sessões esperando uma pela outra não ficam presas. Dentro da sessão, o piso compara só a memória medida, sem as reservas das outras sessões, que valem apenas na admissão. `TEMPERATURE_LIMIT` não tem padrão: sem valor, usa o ponto de disparo passivo informado pelo sistema operacional menos uma margem fixada na spec; sem nenhum dos dois, a temperatura não entra no piso. O aviso de temperatura fixo em 70 °C (`src/agent_runtime/resources.py:89`) passa a derivar desse limite. O limite de agentes simultâneos dentro da sessão (`calculate_dynamic_limit`) perde as faixas fixas de 6 GB e 3 GB e o padrão silencioso de 3 quando não lê a memória: com leitura, o limite é recalculado a cada vaga pedida, a partir da memória disponível acima do piso, descontadas as reservas das outras sessões, dividida pelo limite de memória do sandbox (`CODE_SANDBOX_MEMORY_LIMIT`, convertido de texto como `256m` para MB), entre 1 e `MAX_CONCURRENT_AGENTS`; sem leitura, vale `MAX_CONCURRENT_AGENTS`, com aviso explícito.
5. **Onde e quando se avalia.** A avaliação roda no processo do terminal, quando aberto, ou no processo de uma sessão viva. Acontece:
   - no pedido de uma nova sessão;
   - quando uma sessão termina ou pausa (o processo que encerra avalia a fila antes de sair, descontando da leitura a própria memória e a própria reserva, que estão sendo liberadas);
   - quando o terminal detecta uma sessão interrompida (§6), o que cobre a queda sem encerramento;
   - quando a fila muda;
   - periodicamente, enquanto houver fila ou sessão ativa.

   Um único avaliador roda por vez: cada avaliação tenta uma trava consultiva no banco sem esperar, e quem não a obtém pula a rodada, o que evita chamadas duplicadas ao agente. Na avaliação periódica, o agente só é chamado de novo quando as leituras mudam além de uma margem ou a fila muda, com intervalo mínimo entre chamadas; com a cota do provedor esgotada, o terminal mostra o motivo e não há nova tentativa a cada ciclo. Sessões na fila não têm processo próprio até serem admitidas, então, com o terminal fechado e nenhuma sessão viva, a fila só anda quando o terminal for aberto de novo (trade-off registrado nas Consequências). Quem admite usa o mesmo lançador para criar o processo da sessão, seja o terminal ou uma sessão viva: processo desligado de quem o criou e ambiente filtrado (§4.3). A chamada de admissão usa o modelo configurado para o Researcher, tem o custo registrado à parte como custo de admissão (no evento e no relatório, fora dos limites da sessão do ADR 021 §5), recebe as leituras como dados delimitados (ADR 022) e passa pelos filtros de egresso (ADR 019), embora as leituras sejam números do sistema, sem dados de pesquisa.
6. **Concorrência entre avaliações.** A admissão é uma transição condicional no banco (de `na_fila` para `admitida`, só se ainda estiver `na_fila`), sob trava, para que duas avaliações simultâneas não admitam com base na mesma memória livre. Uma sessão recém-admitida ainda não consome memória, então cada sessão ativa conta com uma reserva igual à estimativa de consumo menos o uso atual dela e dos seus contêineres (nunca negativa). A estimativa vem do `historico_de_consumo`; sem histórico, é o maior pico medido entre as sessões vivas ou, sem nenhuma, o limite de memória do sandbox somado ao consumo medido do processo do terminal. Uma sessão `admitida` cujo processo não registra PID dentro de um prazo volta para `na_fila` e libera a reserva (§6).
7. **Acompanhamento das sessões em execução.** A avaliação periódica vigia as sessões ativas mesmo sem fila: o aviso de recursos abaixo do piso é determinístico, e o agente só é chamado quando as leituras mudam além da margem. O agente pode recomendar pausar uma sessão em execução quando os recursos ficarem críticos. A recomendação vira evento e aviso no terminal; pausar continua sendo ação do pesquisador, exceto as pausas automáticas do item 4 e do §4.4 (§7).
8. **Falha da chamada de admissão.** Se o agente não responder (provedor indisponível, cota esgotada), a sessão segue na fila, o terminal mostra o motivo e oferece a admissão manual, respeitado o piso.
9. **Rastreabilidade.** Cada decisão de admissão (direta, do agente ou manual) vira um evento (§2) com as leituras usadas e a justificativa. Ao fim de cada sessão, o pico de memória e de CPU e o tipo de objetivo são gravados na própria sessão, para o `historico_de_consumo`.
10. **Configuração sem designação de máquina.** Nenhuma variável de ambiente fica atrelada ao Raspberry Pi:

    | Hoje | Passa a ser |
    |---|---|
    | `PI_TEMPERATURE_LIMIT` | `TEMPERATURE_LIMIT` (item 4) |
    | `PI_MIN_AVAILABLE_MEMORY_MB` | `MIN_AVAILABLE_MEMORY_MB` (item 4) |
    | `DEPLOYMENT_PROFILE` (`default` ou `pi5`) | removida |

    O perfil `pi5` mudava quatro padrões (`src/config.py:135-153`, `src/llm/availability.py:32-35`): `MAX_SUBTASKS_PER_TASK` (5 em vez de 10), `MAX_CONCURRENT_AGENTS` (2 em vez de 3), `AGENT_TIMEOUT_SECONDS` (sem limite em vez de 300) e a ordem de `LLM_PROVIDER_PRIORITY` (provedores locais primeiro). Sem o perfil, valem os padrões gerais, e cada máquina declara no próprio `.env` o que quiser diferente. Para que o "sem limite" possa ser declarado, `AGENT_TIMEOUT_SECONDS=0` passa a significar sem tempo limite (hoje o valor lido do ambiente é convertido com `int` e não há como expressá-lo). `parse_priority` deixa de receber o perfil (`src/llm/session.py:256,279`).

    Sem nomes antigos aceitos como sinônimo: se um nome removido estiver definido no ambiente, a inicialização falha com a mensagem do nome novo, em vez de ignorá-lo em silêncio. Como o `.env.example` traz hoje `DEPLOYMENT_PROFILE=default` e as duas variáveis `PI_*`, todo `.env` derivado dele precisa ser migrado, em qualquer máquina; a mensagem de erro diz o que fazer em cada caso (com `DEPLOYMENT_PROFILE=default`, só remover a linha). O `.env` do Raspberry Pi usado nos testes é migrado junto com a mudança, declarando explicitamente os quatro valores do antigo perfil e `TEMPERATURE_LIMIT` e `MIN_AVAILABLE_MEMORY_MB` com os valores efetivos de hoje, para preservar o comportamento atual. A classe `PiHealthMonitor` passa a se chamar `HealthMonitor`. Continuam, por não serem configuração: a detecção de plataforma para escolher imagens (`src/platform_info.py`, `scripts.platform_images`) e os scripts de instalação no Pi (`scripts/setup_pi.sh`, `scripts/setup_ollama_pi5.sh`).

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
| falha / interrupção | `[iris-01] interrompida: processo parou; use 'retomar iris-01'` |

O terminal lê os eventos novos por consulta periódica ou por notificação do PostgreSQL (a spec escolhe). Um painel futuro (roadmap de frontend) consome os mesmos eventos.

### 3. O terminal: conversar e acompanhar

O REPL deixa de esperar a sessão terminar. Enquanto as pesquisas rodam:

- **pequenas atualizações** de cada sessão aparecem entre as interações, uma linha por evento, com o apelido curto da sessão, sem apagar o que o pesquisador está digitando; o nível de detalhe é configurável por sessão;
- **comandos de acompanhamento:** listar pesquisas (estado, tempo, custo, último evento, pedidos pendentes, posição na fila); acompanhar uma sessão (visualização detalhada à parte, até o pesquisador sair dela); pausar ao fim da subtarefa atual; retomar; parar (fechamento gracioso com checkpoint);
- **ações imediatas que não são decisões reservadas:** cancelar uma subtarefa que ainda não começou; pedir replanejamento ao fim da subtarefa atual;
- **conversar com os agentes:** o pesquisador pergunta sobre o projeto, as hipóteses e os resultados enquanto a sessão roda. Responde o Researcher em modo consulta, **só leitura** (conexão ao banco em transação somente leitura e cliente do Qdrant sem escrita). Quando a conversa vira orientação, o terminal propõe transformá-la em mensagem à sessão (§5), e o pesquisador confirma.

### 4. Gate persistente de decisões reservadas

1. **O que passa pelo gate.** Os pedidos de `DECISOES_RESERVADAS` (aprovar Oportunidade, confirmar Problema, aprovar termo, autorizar escrita em instrumento, ativar modo sem limite) e os que hoje leem o terminal dentro da sessão: aprovar hipótese no `assisted`; escolher encerrar ou continuar ao atingir o objetivo (política `perguntar`, ADR 021 §5.3); responder a `ask_researcher` no `assisted`; continuar, orientar ou parar em estagnação no `assisted`, em saturação, intervenções esgotadas ou planos rejeitados (ADR 021 §5.5–§5.6); restringir uma direção (ADR 021 §5.5). Nenhum caminho dentro do processo da sessão lê a entrada padrão.
2. **Persistência.** Os pedidos ficam no banco com estado `pendente` e sobrevivem à queda do processo da sessão e à do terminal.
3. **Quem responde.** Só o processo do terminal resolve pedidos. As respostas são gravadas por um **papel de banco próprio do terminal**, cujas credenciais o processo da sessão não carrega; a resposta é uma transição condicional (de `pendente` para `autorizada`/`negada`, só se ainda estiver `pendente`), o que resolve dois terminais respondendo ao mesmo tempo (vale a primeira). Uma mensagem de agente, um documento ou a caixa de entrada nunca autorizam (regra atual de `HUMAN_SOURCES`). A credencial desse papel fica num arquivo separado do `.env` principal, lido por uma função própria de `src/config.py` só no processo do terminal (o carregamento automático do `.env` na importação não a inclui), e o processo da sessão é iniciado com um ambiente filtrado, sem ela. Risco residual: os dois processos rodam com o mesmo usuário do sistema operacional, e código no host com esse usuário poderia ler o arquivo; os agentes não executam código no host (ADR 014: código só no sandbox), o que limita o risco. Um usuário de sistema separado para o processo da sessão fica como endurecimento opcional.
4. **A sessão não para por um pedido.** Enquanto um pedido está pendente, a sessão segue com o que não depende dele e só espera quando não houver mais nada a fazer. A espera não conta como ciclo ocioso nem como estagnação (ADR 021 §5.6). O terminal lembra o pedido periodicamente e o mostra na lista de pesquisas. Opcionalmente, depois de um prazo configurável de espera, a sessão pausa com checkpoint, libera recursos e a fila é reavaliada.

### 5. Caixa de entrada da sessão

O pesquisador pode mandar uma mensagem a uma sessão em execução (orientação, nova ideia, novo insumo, "não teste mais SVM"). A mensagem:

- só é gravada pelo processo do terminal, com o mesmo papel de banco do §4.3;
- tem tamanho limitado e é registrada no grafo como orientação do pesquisador, ligada à sessão;
- é entregue ao Researcher no próximo replanejamento, delimitada como dado, junto com o restante do contexto (ADR 022); para efeito imediato, o pesquisador usa as ações do §3;
- orienta o plano, mas não substitui as decisões reservadas: rejeitar uma hipótese continua sendo uma ação do gate, não uma frase na mensagem.

### 6. Falhas

- **Sessão parada.** O terminal (ao abrir e periodicamente) marca como `interrompida` a sessão cujo batimento envelheceu ou cujo PID não existe mais; hoje isso só acontece quando outro orquestrador inicia (`src/orchestrator.py:826`). O batimento só é aceito se o laço de eventos da sessão também deu sinal recente (não basta a thread do batimento estar viva). A retomada usa o mecanismo existente.
- **Comando direto morto na espera.** O registro de espera de um comando direto em primeiro plano cujo PID não existe mais ou cujo batimento envelheceu é removido, e a fila volta a andar (§1).
- **Admitida sem processo.** Uma sessão `admitida` cujo processo não registra PID dentro de um prazo volta para `na_fila` e libera a reserva (§1.1, item 6).
- **Duas instâncias.** Reativar uma sessão que já foi continuada por outra (`continued_by`) é recusado (hoje `reassert_active` não confere, `src/session.py:349-361`); o processo antigo que perde a sessão se encerra.
- **Terminal fechado:** nada acontece com a sessão; ao abrir de novo, o REPL mostra o resumo do que mudou.

### 7. Segurança e recursos

- O processo da sessão herda as barreiras de hoje: sandbox de código, filtros de egresso, localidade, segredos só por variáveis de ambiente.
- Eventos exibidos e respostas da consulta passam pelos filtros de exibição e egresso.
- O processo da sessão e o do terminal competem por memória na mesma máquina: o uso de cada um é medido (§1.1), e o terminal carrega embeddings e clientes LLM só quando a consulta ou a admissão os usa.
- As ferramentas de recursos só leem; não executam comandos no host nem alteram processos. Pausar ou parar uma sessão continua sendo ação do pesquisador ou do fechamento gracioso, com duas exceções: a pausa automática depois do prazo de espera abaixo do piso (§1.1, item 4) e a pausa opcional depois do prazo de um pedido pendente no gate (§4.4).

### 8. Aprovações necessárias

Este ADR exige **alteração de schema** (tabelas de eventos de progresso, de pedidos do gate e da caixa de entrada; estado de fila, PID, momento e custo da admissão, reserva e consumo de pico na sessão; papel de banco do terminal), que depende de aprovação explícita do pesquisador na mudança OpenSpec correspondente (AGENTS.md §1.5).

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
Um `MAX_CONCURRENT_SESSIONS` com padrão 1. **Rejeitada:** o padrão vinha de uma suposição sobre o Raspberry Pi 5, não de medição, e o sistema roda em máquinas diferentes. Fica como teto opcional (§1.1, item 3.2).

### I. Agente com acesso livre ao terminal do host para medir recursos
O agente rodaria comandos como `free` ou `top`. **Rejeitada:** os agentes não executam código no host (ADR 014); funções fixas entregam as mesmas leituras sem abrir execução arbitrária, e funcionam igual em cada plataforma.

---

## Consequências

### Positivas
- O pesquisador conversa com os agentes enquanto a pesquisa roda; explorações longas ficam viáveis.
- Decisões reservadas não se perdem e não travam a sessão inteira.
- A queda do terminal não afeta a pesquisa; a queda da sessão é detectada e retomável.
- Os eventos ficam prontos para um painel futuro.

### Negativas / Trade-offs
- Um processo a mais por sessão, três tabelas novas, colunas novas na sessão e um papel de banco a manter.
- O REPL passa a ter saída assíncrona intercalada com o que o pesquisador digita.
- Testes de integração precisam de processos separados.
- Sessões simultâneas disputam memória, CPU, temperatura e a cota dos provedores; com outras sessões ativas, a admissão depende de uma chamada ao Researcher, que tem custo.
- O uso de memória de uma sessão ainda não foi medido; o `historico_de_consumo` começa vazio, e as primeiras admissões se apoiam só nas leituras do momento e na reserva pelo limite do sandbox.
- Com o terminal fechado e nenhuma sessão viva, a fila não anda até o terminal ser aberto; um processo supervisor permanente resolveria, mas é a alternativa B, não adotada agora.
- Quem usa o Raspberry Pi precisa declarar no `.env` os valores que o perfil `pi5` dava; a inicialização falha se encontrar os nomes antigos.

---

## Mudanças OpenSpec exigidas

| Mudança | Capacidade | O que cobre |
|---|---|---|
| `v18.7-background-sessions` | `session-continuity`, `agent-runtime`, `benchmark` | §1, §6, §7: processo da sessão, fila de sessões, PID, batimento com sinal do laço, recusa de reativar sessão continuada, comando direto em primeiro plano |
| `v18.7-resource-admission` | `agent-runtime`, `researcher-consult`, `llm-providers`, `operation-metrics` | §1.1: monitor de recursos multiplataforma (substitui a leitura específica do Pi em `src/health.py`, `src/agent_runtime/resources.py` e `src/autonomous_loop.py`; remove os valores fixos fora do Linux e o `vcgencmd`), ferramentas só de leitura, ordem da admissão (piso, teto, direta, agente), admissão condicional com reserva, limite de agentes pela memória, histórico de consumo, remoção de `DEPLOYMENT_PROFILE` e do prefixo `PI_`, `AGENT_TIMEOUT_SECONDS=0`, migração do `.env.example`, do `.env` do Pi e dos testes (`tests/unit/test_config.py`, `tests/unit/llm/test_availability.py`, `tests/unit/test_health.py`, `tests/unit/test_agent_runtime_resources.py`) |
| `v18.7-session-events-terminal` | `session-continuity`, `researcher-consult` | §2, §3: tabela de eventos, atualizações no REPL, comandos e ações imediatas, consulta só leitura ao Researcher |
| `v18.7-persistent-human-gate` | `researcher-consult`, `hypothesis-loop` | §4, §5, §8: gate persistente, papel de banco do terminal, migração de todas as leituras da entrada padrão, caixa de entrada |

---

## Revisão

Revisar depois do primeiro uso com uma exploração de mais de uma hora, em pelo menos duas máquinas de configurações diferentes (por exemplo, o Raspberry Pi 5 e um computador de mesa): memória com o terminal aberto, decisões de admissão e se foram adequadas, se o piso de 512 MB é folgado demais nas máquinas grandes, atraso das atualizações, pedidos ao gate respondidos e perdidos.
