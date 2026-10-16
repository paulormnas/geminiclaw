"""Processo da sessão para os testes de integração (``python -m tests.support.session_process_recorded --launch <f>``).

Roda o ``src.cli.session_process`` real (arquivo de lançamento, registro de PID/apelido, batimento, fechamento,
checkpoint e código de saída), mas sem chamada paga: a resolução de modelos é offline (catálogo real, todos os modelos
disponíveis) e o laço autônomo é um ``ScriptedLoop`` que executa os passos do cenário em ``GC_SCENARIO`` (JSON):

    {"passos": [{"dorme": 3}, {"tokens": 0}], "motivo": "solucao_encontrada"}

``dorme`` espera N s (consultando o pedido de interrupção graciosa, como o laço real); ``subtarefa`` dá nome ao
passo (registrado em ``payload.subtarefas`` e concluído mesmo com a suspensão pedida); ``motivo`` é o
``motivo_parada`` gravado no fim. Um pedido de suspensão (ausência do terminal) impede o passo seguinte. Nenhum gancho de teste entra no código de produção: tudo é substituído aqui, no
módulo de teste (design §4, "Como os testes de integração rodam sem chamada paga").
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import src.cli.session_process as session_process


class ScriptedLoop:
    """Substituto do ``AutonomousLoop``: o ciclo de vida da requisição (sessão, batimento, fechamento) é o real."""

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    async def run(self, prompt: str, exec_id: str, mode: str | None = None, budget: Any = None) -> Any:
        from src.orchestration.orchestrator import OrchestratorResult
        from src.orchestration.usage import (
            clear_interrupt,
            interrupt_requested,
            set_session_active,
            suspension_requested,
        )
        from src.session.states import STATUS_AWAITING_RESEARCHER, STATUS_SUSPENDED_NO_RESEARCHER

        scenario = json.loads(open(os.environ["GC_SCENARIO"], encoding="utf-8").read())
        master_id = list(self.orchestrator._session_modes)[-1]
        manager = self.orchestrator.session_manager
        clear_interrupt()
        set_session_active(True)
        motivo = scenario.get("motivo", "solucao_encontrada")
        status: str | None = None
        subtarefas: list[dict[str, str]] = []
        try:
            for passo in scenario.get("passos", []):
                if suspension_requested():  # a sessão assisted sem o terminal não despacha subtarefa nova
                    motivo, status = "suspensa_sem_pesquisador", STATUS_SUSPENDED_NO_RESEARCHER
                    break
                nome = passo.get("subtarefa")
                if nome:
                    subtarefas.append({"nome": nome, "status": "em_andamento"})
                    self._publish(manager, master_id, subtarefas)
                remaining = float(passo.get("dorme", 0))
                while remaining > 0:
                    if interrupt_requested():
                        motivo = "interrompida_pesquisador"
                        break
                    await asyncio.sleep(min(0.1, remaining))
                    remaining -= 0.1
                if nome:  # o que está em curso termina mesmo com a suspensão pedida
                    subtarefas[-1]["status"] = "concluida"
                    self._publish(manager, master_id, subtarefas)
                if motivo == "interrompida_pesquisador":
                    break
            if motivo == "aguarda_pesquisador":
                status = STATUS_AWAITING_RESEARCHER
        finally:
            set_session_active(False)
        session = manager.get(master_id)
        payload = {**(session.payload if session else {}), "motivo_parada": motivo, "subtarefas": subtarefas}
        manager.update(master_id, status=status, payload=payload)
        return OrchestratorResult(results=[], total=0, succeeded=0, failed=0, artifacts=[])

    @staticmethod
    def _publish(manager: Any, master_id: str, subtarefas: list[dict[str, str]]) -> None:
        session = manager.get(master_id)
        manager.update(master_id, payload={**(session.payload if session else {}), "subtarefas": list(subtarefas)})


def _offline_routing() -> Any:
    from src import config
    from src.llm import session as llm_session
    from src.llm.availability import Availability
    from src.llm.routing import validate_policy, validate_routing_mode

    catalog = llm_session.get_catalog()
    return llm_session._resolve(
        catalog,
        {},
        validate_policy(config.LLM_DATA_POLICY),
        validate_routing_mode(config.LLM_ROUTING),
        {model_id: Availability(True) for model_id in catalog.modelos},
    )


def install() -> None:
    import src.llm.session as llm_session
    import src.orchestration.orchestrator as orchestrator_module

    async def build_session_routing(*_args: Any, **_kwargs: Any) -> Any:
        return _offline_routing()

    llm_session.build_session_routing = build_session_routing  # type: ignore[assignment]
    orchestrator_module.AutonomousLoop = ScriptedLoop  # type: ignore[assignment,misc]


if __name__ == "__main__":
    install()
    sys.exit(session_process.main())
