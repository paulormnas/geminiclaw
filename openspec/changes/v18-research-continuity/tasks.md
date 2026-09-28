# Tarefas: v18-research-continuity

## 1. Checkpoint
- [ ] 1.1 `src/continuity.py`: modelo do checkpoint, gravação atômica com `.bak`, leitura com validação de versão.
- [ ] 1.2 Chamadas de gravação nos momentos do design (plano, subtarefas, abandono, Curator, fechamento).

## 2. Paradas inesperadas
- [ ] 2.1 `SessionManager.heartbeat` e tarefa periódica durante a sessão.
- [ ] 2.2 Detecção de sessões obsoletas na inicialização; marcação `interrompida`; ingestão das falhas de infraestrutura.

## 3. Retomada
- [ ] 3.1 `geminiclaw resume --session` a partir do checkpoint; `geminiclaw continue --project`.
- [ ] 3.2 Nova sessão com `continues_session_id`, orçamento novo, aresta `CONTINUA`.
- [ ] 3.3 `AgentContext.readable_dirs` com sessões anteriores do projeto.
- [ ] 3.4 Contexto de retomada do Researcher e replanejamento em `REPLAN`.
- [ ] 3.5 Curator pendente executado antes do novo plano.
- [ ] 3.6 Remover o texto de limitação e o reinício a partir do prompt em `resume_session`.

## 4. Testes
- [ ] 4.1 Checkpoint gravado após cada subtarefa; conteúdo válido.
- [ ] 4.2 Escrita interrompida (simulada) mantém o último checkpoint válido.
- [ ] 4.3 Sessão com batimento antigo é marcada `interrompida`; subtarefa em andamento vira falha de infraestrutura.
- [ ] 4.4 Retomada não reexecuta subtarefas concluídas e reaproveita seus artefatos.
- [ ] 4.5 Retomada após `limite_tokens` recebe orçamento novo.
- [ ] 4.6 Developer na sessão retomada lê artefato da anterior e não consegue escrever nela.
- [ ] 4.7 Sessão com `solucao_encontrada` pede confirmação para continuar.

## 5. Fechamento
- [ ] 5.1 Ruff, testes, revisão nos 7 eixos, PR.
