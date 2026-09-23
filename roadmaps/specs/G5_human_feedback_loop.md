# Spec G5 — Human-in-the-Loop: Feedback do Pesquisador e Notificações Operacionais

**Versão:** V15.3
**Status:** Proposta aprovada — aguardando implementação de V14
**Gap:** G5 — Ausência de feedback loop com o pesquisador humano
**ADRs relacionados:**
  - [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md) — Propósito como harness
  - [ADR 002](../../docs/decisions/adr_002_arquitetura_multi_agent_system.md) — MAS e loop de execução

---

## Objetivo

Implementar um mecanismo de Human-in-the-Loop (HITL) que preserva a **autonomia como comportamento
padrão** enquanto permite ao sistema pausar em pontos verdadeiramente bloqueantes e notificar o
pesquisador sobre limites operacionais sem interromper o fluxo.

**Filosofia central:**
- O agente investiga divergências por conta própria antes de qualquer consulta
- O pesquisador só é interrompido quando o contexto está genuinamente ausente
- Notificações de limites (tokens, custo, tempo) são não-bloqueantes por padrão
- Meta: máximo 2-3 consultas bloqueantes por sessão no modo assistido

---

## Dependências

- **V14 concluído:** Researcher Agent, Developer Agent e CLI básico operacionais
- **G9 implementado:** `input_context/` pipeline para contexto estruturado
- **G10 implementado:** Session Profile com modos `assisted/semi/auto`

---

## Contexto e Problema

O sistema atual não tem mecanismo para:
1. Pausar e perguntar ao pesquisador quando o contexto está genuinamente ausente
2. Reportar divergências de resultado com diagnóstico estruturado
3. Notificar sobre proximidade de limites operacionais (tokens, custo, tempo)
4. Persistir as respostas do pesquisador para rastreabilidade e reutilização

Sem isso, o agente inventa informações ausentes ou falha silenciosamente, e o pesquisador
não tem visibilidade do que aconteceu durante a sessão.

---

## Tarefas

### Tarefa 1: Implementar tool `ask_researcher` nos agentes

- **Módulos afetados:** `agents/researcher/agent.py`, `agents/developer/agent.py`,
  `src/skills/human_feedback/skill.py` (novo)
- **Complexidade estimada:** Alta
- **Critérios de aceite:**
  - [ ] `HumanFeedbackSkill` criada em `src/skills/human_feedback/skill.py` com método
        `ask_researcher(question, context, why_cant_proceed, options=None) -> str`
  - [ ] A skill envia a pergunta via IPC para o orquestrador, que a exibe no CLI
  - [ ] Orquestrador aguarda resposta do pesquisador (stdin bloqueante)
  - [ ] Resposta é retornada via IPC para o agente e injetada na `ShortTermMemory`
  - [ ] Se o agente invocar `ask_researcher` sem campo `why_cant_proceed`, o orquestrador
        loga um aviso: "agente perguntou sem justificar por que não pode resolver sozinho"
  - [ ] System prompt do Researcher e Developer incluem seção `QUANDO USAR ask_researcher`
        com exemplos válidos e inválidos (ver análise G5)
  - [ ] Testes: `ask_researcher` com `options=["Opção A", "Opção B"]` exibe lista numerada no CLI
  - [ ] Testes: resposta do pesquisador é salva no `SessionManager` com timestamp

### Tarefa 2: Implementar fluxo de investigação autônoma de divergências

- **Módulos afetados:** `agents/developer/agent.py` (system prompt),
  `agents/researcher/agent.py` (método `replan`), `src/agents/validator_agent.py`
- **Complexidade estimada:** Média (principalmente prompt engineering)
- **Critérios de aceite:**
  - [ ] Developer Agent tem instrução explícita: antes de reportar divergência ao pesquisador,
        tentar ao menos 2 abordagens alternativas documentadas em `metrics.json["investigation_notes"]`
  - [ ] Quando todas as tentativas falham, Validator detecta padrão de falha recorrente e
        gera `DivergenceReport` estruturado (não pergunta simples)
  - [ ] `DivergenceReport` contém: esperado, obtido em cada tentativa, hipótese de causa,
        e lista de opções concretas numeradas para o pesquisador escolher
  - [ ] CLI exibe `DivergenceReport` com formatação clara (modo `assisted`) ou
        apenas registra em `session_metadata.json` (modos `semi`/`auto`)
  - [ ] Testes: subtarefa falha 3x com métricas distintas → `DivergenceReport` gerado com
        `investigation_notes` preenchidos para cada tentativa

### Tarefa 3: Implementar monitoramento e notificação de limites operacionais

- **Módulos afetados:** `src/autonomous_loop.py`, `src/telemetry.py`, `src/cli.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `AutonomousLoop` monitora e compara com thresholds configuráveis em `src/config.py`:
        ```python
        OPERATIONAL_THRESHOLDS = {
            "token_usage_pct": 0.80,
            "cost_usd": 5.0,
            "session_duration_min": 60,
            "container_count_pct": 0.85,
        }
        ```
  - [ ] Quando threshold atingido: CLI exibe aviso formatado e aguarda 30s antes de continuar
  - [ ] Se pesquisador digitar `s` no aviso: sessão suspensa; estado salvo em `session_metadata.json`
  - [ ] `geminiclaw resume --session <id>` retoma sessão suspensa do ponto onde parou
  - [ ] Nos modos `semi` e `auto`: avisos operacionais apenas registrados em log, sem exibição no terminal
  - [ ] Testes: `token_usage_pct` artificialmente forçado para 0.81 → aviso exibido no CLI
  - [ ] Testes: pesquisador digita `s` → sessão marcada como `suspended` no `SessionManager`

### Tarefa 4: Persistência e rastreabilidade das interações com o pesquisador

- **Módulos afetados:** `src/session_manager.py`, `src/workspace_manifest.py`
- **Complexidade estimada:** Baixa-Média
- **Critérios de aceite:**
  - [ ] `SessionManager` persiste no PostgreSQL todas as interações `ask_researcher`:
        `{timestamp, question, why_cant_proceed, options, researcher_response, subtask_name}`
  - [ ] `WorkspaceManifest` inclui campo `researcher_interactions: list[dict]`
  - [ ] Se o mesmo tipo de dúvida surgir novamente na mesma sessão (similaridade semântica > 0.85),
        o agente recebe a resposta anterior automaticamente sem perguntar de novo
  - [ ] Relatório final (G8) inclui seção "Decisões do Pesquisador" populada a partir do
        `SessionManager` — não requer que o Summarizer reconstrua essas informações
  - [ ] Testes: mesma pergunta feita 2x na mesma sessão → segunda vez respondida automaticamente

### Tarefa 5: Testes de integração do fluxo HITL completo

- **Módulos afetados:** `tests/integration/test_hitl_flow.py` (novo)
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] Cenário assistido: subtarefa com contexto ausente → `ask_researcher` invocada uma vez;
        resposta injetada; subtarefa conclui com sucesso
  - [ ] Cenário semi: subtarefa com contexto ausente → suposição documentada; nenhuma pergunta feita
  - [ ] Cenário: divergência após 3 tentativas → `DivergenceReport` exibido com opções numeradas;
        pesquisador escolhe [1] → execução continua com opção escolhida
  - [ ] Cenário: mesmo question feito 2x → segunda ocorrência respondida automaticamente sem CLI
  - [ ] Cenário: threshold de tokens atingido → aviso não-bloqueante; sessão continua após 30s

---

## Validação da Etapa

- [ ] `uv run pytest -m "unit or integration" -v` — todos os testes passam
- [ ] Smoke test modo assistido: sessão com 1 contexto ausente → exatamente 1 pergunta ao pesquisador
- [ ] Smoke test modo semi: sessão com 2 contextos ausentes → zero perguntas, 2 suposições em log
- [ ] Relatório final inclui seção "Decisões do Pesquisador" com todas as interações
- [ ] PR merged em `dev`

---

## Arquivos

| Arquivo | Ação | Descrição |
|---|---|---|
| `src/skills/human_feedback/skill.py` | NEW | `HumanFeedbackSkill` com `ask_researcher()` |
| `agents/researcher/agent.py` | MODIFY | Registrar `ask_researcher` como tool disponível; atualizar system prompt |
| `agents/developer/agent.py` | MODIFY | Registrar `ask_researcher`; instrução de investigação autônoma antes de perguntar |
| `src/autonomous_loop.py` | MODIFY | Adicionar loop de monitoramento de thresholds; handler de suspensão |
| `src/config.py` | MODIFY | Adicionar `OPERATIONAL_THRESHOLDS` configurável via `.env` |
| `src/session_manager.py` | MODIFY | Persistir interações HITL no PostgreSQL |
| `src/workspace_manifest.py` | MODIFY | Campo `researcher_interactions` |
| `src/agents/validator_agent.py` | MODIFY | Detectar padrão de falha recorrente; gerar `DivergenceReport` |
| `src/cli.py` | MODIFY | Exibir `DivergenceReport`; aviso de limites operacionais; suporte a `resume` |
| `tests/integration/test_hitl_flow.py` | NEW | Testes de integração do fluxo HITL completo |
