"""Runtime de agentes em processo no host (Roadmap V16 / ADR 014).

Este pacote implementa a execução de agentes dentro do processo do
orquestrador, como alternativa ao modelo de containers efêmeros por agente
com IPC (``src/runner.py`` + ``src/ipc.py`` + ``agents/runner.py``).

Módulos:
    context: ``AgentContext`` por tarefa via ``contextvars`` (substitui o uso
        de variáveis de ambiente para estado por tarefa).
    definitions: Registro ``AGENT_DEFINITIONS`` (papel → instrução,
        ferramentas, callbacks), equivalente em processo ao ``AGENT_REGISTRY``
        (papel → imagem Docker) usado pelo modo container.
    runtime: ``AgentRuntime``, responsável por executar uma ``AgentTask`` em
        processo com supervisão de timeout e isolamento de falhas.

Fase 1 (atual): o runtime em processo coexiste com o modo container, seleção
via ``AGENT_RUNTIME=inprocess|container`` (``src/config.py``). A remoção do
modo container é a Fase 2, sujeita a aprovação explícita (ver
``openspec/changes/v16-in-process-agents/``).
"""
