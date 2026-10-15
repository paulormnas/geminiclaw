# Tarefas: v18.7-session-events-terminal

**Estado (2026-10-15):** não iniciada.

## 0. Pré-requisitos
- [ ] 0.1 `v18.7-background-sessions` e `v18.7-persistent-human-gate` mergeadas; revisar esta mudança contra o código de `dev` (referências de linha de 2026-10-15).
- [ ] 0.2 Aprovação do pesquisador para o schema e respostas às Questões em aberto 1 a 4 do design (1 e 2 decididas pelo pesquisador em 2026-10-15; ficam abertas a 3 e a 4).

- [ ] 0.3 Testes reaproveitam as ajudas de `v18.7-background-sessions` (tasks §3.4: harness do processo da sessão, provedor gravado, `FakeClock`, fixture de PostgreSQL com `terminal_writer`, REPL com entrada simulada e em pseudo-terminal) e o `FakeGate` de `v18.7-persistent-human-gate`; nenhuma ajuda nova. Cada teste de integração em até 15 s (marcador `pytest-timeout`), com `SESSION_EVENTS_POLL_SECONDS=1`, `SESSION_INBOX_POLL_SECONDS=1` e os valores reduzidos de `v18.7-background-sessions` definidos pelo harness por variável de ambiente; os padrões (2 s etc.) só em testes de unidade com `FakeClock`.
- [ ] 0.9 Divisão do módulo grande antes do comportamento novo (ADR 024 §5), só movendo código, com a suíte verde antes de seguir: `src/cli/main.py`: extrair para módulos próprios em `src/cli/` os comandos de acompanhamento e a exibição de eventos. Os caminhos citados nesta mudança valem pela tabela de `v18.7-source-layout`.

## 1. Eventos
- [ ] 1.1 `scripts/init_db.sql` e `scripts/migrations/v18_7_003_session_events.sql` (idempotente) com o DDL do design §2.1.
- [ ] 1.2 `src/session_events.py`: `EventWriter` (resumo por modelo, saneamento, filtro de exibição, limite, nova tentativa, `seq` recuperado na retomada), `EventReader`, `purge`.
- [ ] 1.3 Pontos de emissão em `src/session_process.py`, `src/autonomous_loop.py`, `src/orchestrator.py` e no gate persistente (`decisao_pendente`); evento `falha` gravado pela varredura do terminal.
- [ ] 1.4 Testes de unidade: resumo sem caminho, traceback e valor bruto; métrica validada no resumo; limite de 300; falha de gravação não derruba; retenção 0 e 30 dias.
- [ ] 1.5 Testes de integração (processo real, provedor gravado): evento final antes do status (caso 1), `seq` sem lacuna, `decisao_pendente` sem `flush` da telemetria, suspensão (caso 4), falha pelo terminal (caso 10).

## 2. Impressão no REPL
- [ ] 2.1 `src/terminal/`: thread de leitura, impressão com `readline` sob trava, níveis de detalhe, modo sem TTY.
- [ ] 2.2 Testes: pseudo-terminal com texto parcial preservado (`pexpect`, de `v18.7-background-sessions`); nível silencioso; atraso máximo com `FakeClock`.
- [ ] 2.3 Saneamento na exibição (`sanitize_text` e limite de 300) em eventos, `pesquisas`, `acompanhar` e resposta da consulta; lista fechada de chaves de `dados` por `tipo`. Testes: "Sequência de controle gravada direto na tabela", "Chave fora da lista em dados", "Resposta da consulta com sequência de controle".

## 3. Comandos
- [ ] 3.1 `pesquisas`, `acompanhar`, `retomar` (sobre a retomada de `v18.7-background-sessions`); `nova-pesquisa <tarefa>` com confirmação ao iniciar pesquisa com outra em execução; texto livre sem comando roteado à consulta (task 4.1) ou recusado com a dica de `nova-pesquisa` quando não há pesquisa. Testes: "Texto livre é conversa", "Nova pesquisa por comando", "Nova com outra em execução", "Texto livre sem pesquisa".
- [ ] 3.2 `pausar`, `parar`, `cancelar`, `replanejar`: gravação pela caixa de entrada (`tipo='comando'`, JSON validado); consumo na sessão; motivo de parada `pausada_pesquisador` no enum de `Sessao.motivo_parada`, em `MOTIVOS_RETOMAVEIS` (retomada sem confirmação), em `describe_stop_reason` e na tabela de `src/exit_codes.py` (código 4, tabela única de `v18.7-background-sessions`, design §1.4); `stop_class` do benchmark já o trata como `interrupcao` pela regra dos motivos `*_pesquisador`; `cancelada_pesquisador` é motivo de retirada de subtarefa, não de parada.
- [ ] 3.3 Testes de unidade: lista de pesquisas; recusa para sessão sem processo; acompanhar com histórico; comando desconhecido ignorado e registrado.
- [ ] 3.4 Testes de integração: pausar e retomar; parar; cancelar pendente e recusa para subtarefa em curso; replanejar com nova versão de plano.

## 4. Consulta só leitura
- [ ] 4.0 Processo filho da consulta: criado pelo terminal com `stdin` fechado e `filtered_env` (lista fixa de credenciais do terminal e `SESSION_ENV_DENYLIST`), retorno só do JSON da resposta validado como dado; gravação da orientação no terminal. Teste de integração "Consulta em processo filho sem a credencial".
- [ ] 4.1 `src/terminal_consult.py`: contexto delimitado, escolha da sessão, conexão somente leitura, invólucro do Qdrant, ferramentas restritas, `EgressGate` da sessão, registro em `token_usage` com o `execution_id` da sessão consultada (conta no orçamento dela), carga sob demanda.
- [ ] 4.2 Proposta de orientação com confirmação, gravada pela caixa de entrada.
- [ ] 4.3 Testes de unidade sobre a função `ask` (provedor simulado, sem processo filho): contexto com hipóteses; escrita recusada nas três bases; ferramentas exatas; recusa por localidade; consumo registrado e somado ao uso, ao custo e aos limites da sessão ("Consumo da consulta conta no orçamento"); orientação confirmada e recusada.

## 5. Configuração e documentação
- [ ] 5.1 `src/config.py` com as variáveis do design §3 e validações; `.env.example`.
- [ ] 5.2 `README.md`: comandos do REPL e níveis de detalhe.

## 6. Validação final
- [ ] 6.1 `uv run ruff check .`; `uv run pytest -m "unit or integration" -v` verde com PostgreSQL real.
- [ ] 6.2 Revisão nos 7 eixos; PR para `dev` citando esta mudança; atualizar a linha **Estado** deste arquivo.
