# Tarefas: v16-in-process-agents

## Fase 1 — Runtime em processo

### 1. Contexto por tarefa
- [ ] 1.1 Criar `src/agent_runtime/context.py` (`AgentContext`, `current_context`, `get_agent_context`).
- [ ] 1.2 Substituir leituras por tarefa de `os.environ` em `agents/base/agent.py`, `agents/base/tools.py`, `agents/developer/agent.py`, `agents/researcher/agent.py` e skills.
- [ ] 1.3 Teste: duas tarefas concorrentes veem cada uma o seu contexto.

### 2. Runtime e supervisão
- [ ] 2.1 `run_agent_loop` recebe o provedor por parâmetro; remover `get_provider()` interno.
- [ ] 2.2 Criar `AGENT_DEFINITIONS` (papel → instrução, ferramentas, callbacks) e `AgentRuntime.run`.
- [ ] 2.3 `Orchestrator._execute_agent` usa `AgentRuntime` quando `AGENT_RUNTIME=inprocess`.
- [ ] 2.4 Testes: timeout vira `AgentResult(status="timeout")`; exceção vira `status="error"`; orquestrador segue executando outras tarefas.

### 3. ask_researcher
- [ ] 3.1 Callback `ask_researcher` no `AgentContext`, ligado a `_handle_ask_researcher`.
- [ ] 3.2 Skill `human_feedback` usa o callback; manter o caminho IPC só no modo container.
- [ ] 3.3 Testes existentes de G5 passam no modo em processo.

### 4. Salvaguardas no host
- [ ] 4.1 `write_artifact` confinado ao diretório da sessão (resolve, descendente, sem symlink).
- [ ] 4.2 Bloqueio de IPs privados/loopback/link-local/metadados no `web_reader` e scrapers.
- [ ] 4.3 Prompt base: remover instrução de `subprocess`; orientar o parâmetro `packages`.
- [ ] 4.4 Researcher: substituir `agents/researcher/tools.py::search` (Gemini CLI) pela skill `search_quick`.
- [ ] 4.5 Testes: path traversal (`../../etc/passwd`), symlink, URL `http://127.0.0.1:5432`, `http://169.254.169.254/`, `file://`.

### 5. Circuit breakers e config
- [ ] 5.1 `MAX_AGENT_RUNS_PER_SESSION` e novo significado de `MAX_CONTAINERS_PER_SESSION`; `.env.example`.
- [ ] 5.2 `AGENT_RUNTIME` em `src/config.py`.

### 6. Validação
- [ ] 6.1 **Revisão do Analista de Segurança** (STRIDE sobre as ferramentas do host).
- [ ] 6.2 Sessão completa no Pi 5 comparando tempo e RAM com o modo container (registrar no PR).
- [ ] 6.3 Ruff, testes, revisão nos 7 eixos, PR da fase 1.

## Fase 2 — Remoção do modo container (após aprovação explícita)
- [ ] 7.1 **Aprovação do pesquisador** para remover arquivos e alterar Dockerfiles/compose.
- [ ] 7.2 Remover `src/ipc.py`, `agents/runner.py`, `SessionContainerRunner`, `AGENT_RUNTIME=container`.
- [ ] 7.3 `ContainerRunner`: remover spawn e imagens de agente; manter infraestrutura.
- [ ] 7.4 Ajustar `docker-compose.yml` e `containers/Dockerfile*` (manter imagem do sandbox).
- [ ] 7.5 Marcar ADR 003 §1/§3 e ADR 004 como Deprecados e ADR 014 como Aceito.
- [ ] 7.6 Ruff, testes, revisão, PR da fase 2.
