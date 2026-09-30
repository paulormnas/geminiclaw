"""Runtime de agentes em processo no host (Roadmap V16 / ADR 014).

Este pacote implementa a execução de agentes dentro do processo do
orquestrador. O modelo anterior, de containers efêmeros por agente com IPC, foi removido
na Fase 2 da mudança ``v16-in-process-agents``; o único uso de container que resta é o
sandbox de código (``src/skills/code/``).

Módulos:
    context: ``AgentContext`` por tarefa via ``contextvars`` (substitui o uso
        de variáveis de ambiente para estado por tarefa).
    definitions: Registro ``AGENT_DEFINITIONS`` (papel → instrução,
        ferramentas, callbacks).
    resources: ``ResourceGuard``, com o limite de agentes simultâneos, a vaga extra para
        inferência local e a espera por temperatura e memória.
    runtime: ``AgentRuntime``, responsável por executar uma ``AgentTask`` em
        processo com supervisão de timeout e isolamento de falhas.

Ver ``openspec/changes/v16-in-process-agents/``.
"""
