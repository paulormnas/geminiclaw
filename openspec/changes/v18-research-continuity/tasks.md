# Tarefas: v18-research-continuity

## 1. Checkpoint
- [x] 1.1 `src/continuity.py`: modelo do checkpoint, gravação atômica com `.bak`, leitura com validação de versão.
- [x] 1.2 Chamadas de gravação nos momentos do design (plano, subtarefas, abandono, Curator, fechamento).

## 2. Paradas inesperadas
- [x] 2.1 `SessionManager.heartbeat` e tarefa periódica durante a sessão.
- [x] 2.2 Detecção de sessões obsoletas na inicialização; marcação `interrompida`; ingestão das falhas de infraestrutura.

## 3. Retomada
- [x] 3.1 `geminiclaw resume --session` a partir do checkpoint; `geminiclaw continue --project`.
- [x] 3.2 Nova sessão com `continues_session_id`, orçamento novo, aresta `CONTINUA`.
- [x] 3.3 `AgentContext.readable_dirs` com sessões anteriores do projeto.
- [x] 3.4 Contexto de retomada do Researcher e replanejamento em `REPLAN`.
- [x] 3.5 Curator pendente executado antes do novo plano.
- [x] 3.6 Remover o texto de limitação e o reinício a partir do prompt em `resume_session`.

## 4. Testes
- [x] 4.1 Checkpoint gravado após cada subtarefa; conteúdo válido.
- [x] 4.2 Escrita interrompida (simulada) mantém o último checkpoint válido.
- [x] 4.3 Sessão com batimento antigo é marcada `interrompida`; subtarefa em andamento vira falha de infraestrutura.
- [x] 4.4 Retomada não reexecuta subtarefas concluídas e reaproveita seus artefatos.
- [x] 4.5 Retomada após `limite_tokens` recebe orçamento novo.
- [x] 4.6 Developer na sessão retomada lê artefato da anterior e não consegue escrever nela.
- [x] 4.7 Sessão com `solucao_encontrada` pede confirmação para continuar.

## 5. Fechamento
- [x] 5.1 Ruff, testes, revisão nos 7 eixos, PR.

## 6. Correções da revisão do PR #108 (2026-10-07)
- [x] 6.0 Achados I-1 a I-6, I-8 e S-1 a S-9 corrigidos com teste (ver `tests/unit/continuity/test_review_fixes.py`).
- [ ] 6.1 **Pendente (decisão do pesquisador: fora da condição de merge):** smoke do SQL novo de `src/session.py`
  (`heartbeat`, `mark_stale`, `claim_continuation`, `release_continuation`, `reassert_active`, `find_continuation`,
  `list_by_project`) contra PostgreSQL real no Raspberry Pi, incluindo a atomicidade de `claim_continuation` com duas
  conexões simultâneas e a semântica de `payload || jsonb` / `?` e de `TIMESTAMPTZ`. Hoje o SQL só é coberto por mock
  de DB que modela as cláusulas em Python (`tests/conftest.py`).
- [ ] 6.2 **Pendente:** validar com Apache AGE real as consultas do contexto de retomada (`find_nodes` por
  `tipo`/`sessao_id`, `related_experience`).
- [ ] 6.3 **Pendente (débito):** fatos de falha de infraestrutura ingeridos por um falso positivo de obsolescência não são
  retirados do grafo quando a sessão viva se reafirma (o batimento em thread torna isso raro).

