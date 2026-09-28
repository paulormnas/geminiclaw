# Proposta: Agentes em Processo no Host; Containers Apenas como Sandbox

**ID:** `v16-in-process-agents` · **Versão:** V16 · **Capacidade:** `agent-runtime`
**ADRs de origem:** [ADR 014](../../../docs/decisions/adr_014_agentes_em_processo_sandbox_codigo.md)
(revisa ADR 003 §1/§3 e ADR 004)

## Por quê

Cada agente roda hoje em um container efêmero (`src/runner.py::ContainerRunner.spawn`,
chamado por `Orchestrator._execute_agent`) e conversa com o orquestrador por IPC
(`src/ipc.py`, `agents/runner.py::run_ipc_loop`). Isso gera latência de 1–3 s por
subtarefa, consumo de 256–384 MB por agente no Pi 5, imagens por papel e um protocolo de IPC
para manter — e não protege contra o risco real, que é o código gerado pelo LLM, já isolado no
sandbox (`src/skills/code/sandbox.py`). O Validator já roda como corrotina no host.

## O que muda

- **Novo:** runtime de agentes em processo (`src/agent_runtime/`), com contexto por tarefa em
  `contextvars` (substitui as variáveis de ambiente por container), supervisão com timeout e
  isolamento de falhas.
- **Modificado:** `Orchestrator._execute_agent` executa o agente em processo; o `ask_researcher`
  passa a ser uma chamada direta ao orquestrador, sem IPC.
- **Modificado:** ferramentas que rodam no host ganham salvaguardas: escrita confinada ao
  diretório da sessão, bloqueio de endereços de rede privados na leitura web, nenhuma
  ferramenta aceita código ou comando de shell.
- **Modificado:** instalação de pacotes só pelo parâmetro `packages` da skill de código
  (dentro do sandbox); o prompt base deixa de instruir `subprocess`.
- **Removido:** busca do Researcher via subprocesso do Gemini CLI
  (`agents/researcher/tools.py::search`) — substituída pela skill de busca rápida existente.
- **Removido (fase 2, com aprovação):** spawn de containers de agente, IPC de agentes
  (`src/ipc.py`, `agents/runner.py`, `SessionContainerRunner`), imagens por papel e a rede de
  agentes.
- **Mantido:** sandbox de código (ADR 003 §2) sem alteração de comportamento.

## Impacto

- **Código:** `src/orchestrator.py`, `src/autonomous_loop.py`, `src/runner.py`, `src/ipc.py`,
  `agents/runner.py`, `agents/base/agent.py`, `agents/base/tools.py`,
  `agents/*/agent.py`, `agents/researcher/tools.py`, `src/llm/agent_loop.py`,
  `src/skills/web_reader/`, `src/skills/human_feedback/skill.py`, `src/telemetry.py`,
  `src/config.py`.
- **Infra:** `docker-compose.yml`, `containers/Dockerfile*` (imagens de agente deixam de ser
  construídas; imagem do sandbox permanece).
- **Contratos:** o protocolo IPC de agentes deixa de existir; mensagens `ask_researcher` e
  `ask_researcher_answer` viram chamadas de função com o mesmo conteúdo.
- **Config:** `MAX_CONTAINERS_PER_SESSION` passa a contar apenas containers de sandbox; novo
  `MAX_AGENT_RUNS_PER_SESSION` conta execuções de agentes.

## Aprovações necessárias

1. **Alteração de `docker-compose.yml` e Dockerfiles** (fase 2) — aprovação explícita.
2. **Remoção de arquivos** `src/ipc.py`, `agents/runner.py` e partes de `src/runner.py`
   (fase 2) — aprovação explícita.
3. **Avaliação do Analista de Segurança** (`security-analyst.md`) antes do merge da fase 1: a
   superfície do host aumenta.
