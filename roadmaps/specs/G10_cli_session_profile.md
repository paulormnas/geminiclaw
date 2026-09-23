# Spec G10 — CLI Session Profile: Modos de Operação e Interface de Ajuda

**Versão:** V15.6
**Status:** Proposta aprovada — implementar antes ou junto com G5 (é pré-requisito do HITL)
**Gap:** G10 — Sem controle de modo de operação por sessão
**ADRs relacionados:**
  - [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md) — Propósito do sistema
  - [ADR 004](../../docs/decisions/adr_004_protocolo_ipc_unix_sockets.md) — IPC (modo influencia comportamento IPC)

---

## Objetivo

Implementar o controle explícito de **nível de autonomia por sessão** via flag `--mode` no CLI,
acompanhado de um `--help` completo e de um resumo de inicialização que informa o pesquisador
sobre o estado atual da sessão antes de começar.

Esta spec é **pré-requisito do G5 (HITL)** — o `ask_researcher` precisa saber em qual modo está
operando para decidir se bloqueia aguardando resposta ou documenta e continua.

---

## Dependências

- **V14 concluído:** CLI operacional com `geminiclaw run` funcional
- Sem dependência de G5, G8, G9 — esta spec deve ser implementada primeiro

---

## Contexto e Problema

O sistema atual não tem conceito de modo de operação. Toda sessão é "totalmente autônoma"
por acidente — não por design. O pesquisador não sabe quais modos existem, não tem como
descobrir sem ler a documentação, e não tem feedback de qual modo está ativo durante a sessão.

---

## Tarefas

### Tarefa 1: Adicionar `--mode` ao CLI e definir `SessionMode`

- **Módulos afetados:** `src/cli.py`, `src/config.py`, `src/session_manager.py`
- **Complexidade estimada:** Baixa-Média
- **Critérios de aceite:**
  - [ ] `SessionMode` enum definido:
        ```python
        from enum import Enum

        class SessionMode(str, Enum):
            ASSISTED = "assisted"  # padrão
            SEMI = "semi"
            AUTO = "auto"
        ```
  - [ ] `geminiclaw run [--mode assisted|semi|auto] "<tarefa>"` funciona
  - [ ] Default: `--mode assisted` quando nenhuma flag fornecida
  - [ ] `SESSION_DEFAULT_MODE` em `src/config.py` configurável via `.env`
        para ambientes que queiram mudar o padrão (ex: servidores headless usam `semi`)
  - [ ] `SessionMode` persistido no `SessionManager` e incluído em `session_metadata.json`
  - [ ] Testes: `geminiclaw run "..."` sem `--mode` → modo `assisted` no manifest
  - [ ] Testes: `geminiclaw run --mode auto "..."` → modo `auto` no manifest

### Tarefa 2: Implementar `--help` completo

- **Módulos afetados:** `src/cli.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] `geminiclaw --help`, `geminiclaw -h`, e `geminiclaw` sem argumentos exibem help completo:
        ```
        ╔══════════════════════════════════════════════════════════════╗
        ║           GeminiClaw — Harness de Pesquisa Científica        ║
        ╚══════════════════════════════════════════════════════════════╝

        USO:
          geminiclaw run [opções] "<tarefa>"
          geminiclaw sessions
          geminiclaw stop [--session <id>]
          geminiclaw convert --session <id> --format <fmt>
          geminiclaw clear-context

        MODOS DE OPERAÇÃO:
          --mode assisted   Padrão. Consulta pesquisador apenas quando contexto
                            está genuinamente ausente. Divergências investigadas
                            autonomamente; pesquisador notificado com diagnóstico.

          --mode semi       Nunca bloqueia. Faz suposições razoáveis, documenta
                            todas as decisões e continua. Ideal para execuções
                            longas sem supervisão ativa.

          --mode auto       Totalmente autônomo. Consulta web para resolver
                            incertezas. Use apenas sem pesquisador disponível.

        CONTEXTO DE ENTRADA:
          Deposite arquivos em input_context/ antes de executar:
            context.md   → objetivo, hipóteses, instruções
            artigo.pdf   → artigos de referência
            dados.csv    → datasets
            imagem.tif   → imagens para análise

        EXEMPLOS:
          geminiclaw run "Reproduza a Tabela 3 do artigo"
          geminiclaw run --mode semi "Análise exploratória"
          geminiclaw run --mode auto "Execute sem interrupção"
          geminiclaw convert --session 20260922_iris --format latex
          geminiclaw sessions --status running

        RELATÓRIO:
          Sempre gerado em /outputs/<session>/relatorio_final.md
          Use 'geminiclaw convert' para LaTeX, DOCX ou HTML.
        ```
  - [ ] `geminiclaw run --help` exibe help específico do subcomando com todas as flags disponíveis
  - [ ] `geminiclaw convert --help` exibe formatos suportados e exemplos
  - [ ] Implementado via `argparse` ou `click` (verificar qual já é usado no projeto)

### Tarefa 3: Implementar banner de inicialização de sessão

- **Módulos afetados:** `src/cli.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] Antes de iniciar qualquer processamento, CLI exibe banner com:
        - Modo de operação ativo
        - Número de arquivos em `input_context/` (e nomes se ≤ 3; caso contrário "N arquivos")
        - Instrução de ajuda (`-h para ajuda` / `Ctrl+C para suspender`)
        ```
        ┌──────────────────────────────────────────────────────────────┐
        │  GeminiClaw  │  Modo: assistido  │  Contexto: 3 arquivo(s)  │
        │  Pressione Ctrl+C para suspender │  -h para ajuda           │
        └──────────────────────────────────────────────────────────────┘
        ```
  - [ ] Se `input_context/` está vazio → banner inclui aviso: `"⚠ Nenhum contexto detectado"`
  - [ ] Se modo `auto` → banner exibe aviso amarelo: `"⚠ Modo autônomo ativo — sem consulta ao pesquisador"`
  - [ ] Banner exibido sem bloqueio — pesquisador não precisa confirmar para continuar
  - [ ] Testes: CLI capturado com `capsys` → banner contém modo correto e número de arquivos

### Tarefa 4: Propagar `SessionMode` para os agentes e comportamentos dependentes

- **Módulos afetados:** `src/autonomous_loop.py`, `agents/researcher/agent.py`,
  `agents/developer/agent.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `SessionMode` passado via IPC payload para todos os agentes na inicialização da sessão
  - [ ] Researcher Agent recebe o modo e adapta seu system prompt:
        - `assisted`: inclui instrução "use `ask_researcher` quando contexto ausente"
        - `semi`: inclui instrução "documente suposições; nunca bloqueie aguardando resposta"
        - `auto`: inclui instrução "resolva autonomamente via web search quando possível"
  - [ ] Developer Agent recebe o modo e adapta o comportamento de `DivergenceReport`:
        - `assisted`: aguarda instrução do pesquisador
        - `semi/auto`: documenta e continua com opção [1] (menor disrupção)
  - [ ] `AutonomousLoop` usa o modo para decidir se exibe avisos operacionais no terminal
        ou apenas registra em log
  - [ ] Testes: mock de Researcher com modo `semi` → nenhuma chamada a `ask_researcher`

### Tarefa 5: Comando `geminiclaw sessions` e `geminiclaw stop`

- **Módulos afetados:** `src/cli.py`, `src/session_manager.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] `geminiclaw sessions` lista sessões ativas com: session_id, modo, tarefa, duração, status
  - [ ] `geminiclaw sessions --status running|suspended|completed` filtra por status
  - [ ] `geminiclaw stop` encerra containers da sessão mais recente com confirmação
  - [ ] `geminiclaw stop --session <id>` encerra sessão específica
  - [ ] Status da sessão persistido no `SessionManager` (running → completed/suspended)

---

## Validação da Etapa

- [ ] `uv run pytest -m "unit or integration" -v` — todos os testes passam
- [ ] `geminiclaw --help` exibe todas as seções sem erro
- [ ] `geminiclaw run "tarefa"` sem `--mode` → modo `assisted` confirmado no manifest
- [ ] Banner de inicialização exibido corretamente para cada modo
- [ ] `SessionMode` propagado corretamente para system prompts dos agentes (verificável via log)
- [ ] PR merged em `dev`

---

## Arquivos

| Arquivo | Ação | Descrição |
|---|---|---|
| `src/cli.py` | MODIFY | Adicionar `--mode`, `--help` completo, banner de inicialização, `sessions`, `stop`, `convert`, `clear-context` |
| `src/config.py` | MODIFY | `SESSION_DEFAULT_MODE`, `SessionMode` enum |
| `src/session_manager.py` | MODIFY | Persistir `session_mode` no PostgreSQL e `session_metadata.json` |
| `src/autonomous_loop.py` | MODIFY | Receber e propagar `SessionMode`; adaptar exibição de avisos por modo |
| `agents/researcher/agent.py` | MODIFY | Receber modo via IPC e adaptar system prompt dinamicamente |
| `agents/developer/agent.py` | MODIFY | Receber modo via IPC; adaptar `DivergenceReport` por modo |
| `.env.example` | MODIFY | Adicionar `SESSION_DEFAULT_MODE=assisted` com comentário |
| `tests/unit/test_cli_session_mode.py` | NEW | Testes unitários de `--mode` e banner |
| `tests/integration/test_session_profile.py` | NEW | Testes de propagação do modo para agentes |
