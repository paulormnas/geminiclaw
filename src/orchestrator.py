"""Orquestrador principal do GeminiClaw.

Coordena a execução de múltiplos agentes em containers Docker,
gerenciando sessões, IPC e tratamento de falhas parciais.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS
from src.session import SessionManager
from src.runner import ContainerRunner
from src.ipc import IPCChannel, create_message, Message
from src.output_manager import OutputManager

logger = get_logger(__name__)

# Registro de agentes disponíveis: tipo → imagem Docker
AGENT_REGISTRY: dict[str, str] = {
    "base": "geminiclaw-base",
    "researcher": "geminiclaw-researcher",
}

@dataclass
class AgentTask:
    """Definição de uma tarefa a ser executada por um agente.

    Args:
        agent_id: Identificador do agente.
        image: Nome da imagem Docker a ser usada.
        prompt: Prompt/solicitação a ser enviada ao agente.
    """

    agent_id: str
    image: str
    prompt: str


@dataclass
class AgentResult:
    """Resultado da execução de um agente.

    Args:
        agent_id: Identificador do agente.
        session_id: ID da sessão associada.
        status: Status da execução ("success", "error", "timeout").
        response: Payload da resposta do agente.
        error: Mensagem de erro, se houver.
    """

    agent_id: str
    session_id: str
    status: str
    response: dict[str, Any]
    error: str | None = None


@dataclass
class OrchestratorResult:
    """Resultado consolidado da orquestração.

    Args:
        results: Lista de resultados individuais dos agentes.
        total: Total de agentes executados.
        succeeded: Quantidade que finalizou com sucesso.
        failed: Quantidade que falhou.
    """

    results: list[AgentResult]
    total: int
    succeeded: int
    failed: int
    artifacts: list[dict[str, Any]] = field(default_factory=list)


class Orchestrator:
    """Orquestrador principal que coordena agentes em containers.

    Recebe uma solicitação, decide quais agentes spawnar,
    e coordena o ciclo de vida completo via IPC.
    """

    def __init__(
        self,
        runner: ContainerRunner,
        ipc: IPCChannel,
        session_manager: SessionManager,
        output_manager: OutputManager | None = None,
    ) -> None:
        """Inicializa o orquestrador com dependências injetadas.

        Args:
            runner: Gerenciador de containers Docker.
            ipc: Canal de comunicação IPC.
            session_manager: Gerenciador de sessões SQLite.
            output_manager: Gerenciador de outputs (opcional).
        """
        self.runner = runner
        self.ipc = ipc
        self.session_manager = session_manager
        self.output_manager = output_manager or OutputManager()

    @staticmethod
    def get_available_agents() -> dict[str, str]:
        """Retorna os agentes disponíveis e suas imagens Docker.

        Returns:
            Dicionário mapeando tipo de agente → imagem Docker.
        """
        return dict(AGENT_REGISTRY)

    async def handle_request(
        self,
        prompt: str,
        agent_tasks: list[AgentTask] | None = None,
    ) -> OrchestratorResult:
        """Processa uma solicitação do usuário, spawnando e coordenando agentes.

        Args:
            prompt: Solicitação do usuário.
            agent_tasks: Lista de tarefas de agentes. Se None, cria uma tarefa
                         padrão com o agente base.

        Returns:
            Resultado consolidado com respostas de todos os agentes.
        """
        if agent_tasks is None:
            agent_tasks = [
                AgentTask(
                    agent_id="base_agent",
                    image="geminiclaw-base",
                    prompt=prompt,
                )
            ]

        prompt_preview = prompt[:100]
        logger.info(
            "Iniciando orquestração",
            extra={
                "prompt_preview": prompt_preview,
                "agent_count": len(agent_tasks),
                "agents": [t.agent_id for t in agent_tasks],
            },
        )

        # Executa todos os agentes em paralelo com tolerância a falhas
        coroutines = [
            self._execute_agent(task)
            for task in agent_tasks
        ]

        raw_results = await asyncio.gather(*coroutines, return_exceptions=True)

        # Processa resultados, convertendo exceções em AgentResult de erro
        results: list[AgentResult] = []
        for i, raw in enumerate(raw_results):
            if isinstance(raw, AgentResult):
                results.append(raw)
            elif isinstance(raw, Exception):
                # Exceção não capturada — cria resultado de erro
                task = agent_tasks[i]
                results.append(
                    AgentResult(
                        agent_id=task.agent_id,
                        session_id="",
                        status="error",
                        response={},
                        error=f"Exceção não tratada: {raw}",
                    )
                )
                logger.error(
                    "Exceção não tratada durante execução de agente",
                    extra={
                        "agent_id": task.agent_id,
                        "error": str(raw),
                    },
                )

        succeeded = sum(1 for r in results if r.status == "success")
        failed = len(results) - succeeded

        # Coleta artefatos de todas as sessões envolvidas
        all_artifacts = []
        unique_sessions = {r.session_id for r in results if r.session_id}
        for sid in unique_sessions:
            all_artifacts.extend(self.output_manager.list_artifacts(sid))

        orchestrator_result = OrchestratorResult(
            results=results,
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            artifacts=all_artifacts,
        )

        logger.info(
            "Orquestração concluída",
            extra={
                "total": orchestrator_result.total,
                "succeeded": orchestrator_result.succeeded,
                "failed": orchestrator_result.failed,
                "artifacts_count": len(all_artifacts),
            },
        )

        return orchestrator_result

    async def _execute_agent(self, task: AgentTask) -> AgentResult:
        """Executa o ciclo de vida completo de um único agente.

        Ciclo: cria sessão → cria socket IPC → spawna container →
        aguarda conexão → envia prompt → recebe resposta → cleanup.

        Args:
            task: Definição da tarefa do agente.

        Returns:
            Resultado da execução do agente.
        """
        session = self.session_manager.create(task.agent_id)
        container_id: str | None = None
        ipc_id = f"{task.agent_id}_{session.id}"
        result: AgentResult

        try:
            logger.info(
                "Executando agente",
                extra={
                    "agent_id": task.agent_id,
                    "session_id": session.id,
                    "image": task.image,
                },
            )

            # 0. Inicializa diretório de output para a sessão e para a tarefa
            self.output_manager.init_session(session.id)
            self.output_manager.get_task_dir(session.id, task.agent_id)

            # 1. Cria socket IPC
            await self.ipc.create_socket(ipc_id)

            # 2. Spawna container
            ipc_port = self.ipc.get_port(ipc_id)
            container_id = await self.runner.spawn(
                task.agent_id, task.image, session.id, ipc_port=ipc_port
            )

            # 3. Aguarda conexão do container ao socket monitorando saúde
            deadline = AGENT_TIMEOUT_SECONDS
            elapsed = 0.0
            interval = 0.5
            while ipc_id not in self.ipc._connections:
                if elapsed >= deadline:
                    raise TimeoutError(
                        f"Container '{task.agent_id}' não conectou dentro de {deadline}s."
                    )
                
                # Verifica se o container ainda está vivo
                if not await self.runner.is_running(container_id):
                    logs = await self.runner.get_logs(container_id)
                    raise RuntimeError(
                        f"Container '{task.agent_id}' encerrou inesperadamente antes de conectar.\n"
                        f"Logs:\n{logs}"
                    )
                
                await asyncio.sleep(interval)
                elapsed += interval

            # 4. Envia prompt via IPC
            request_msg = create_message(
                "request",
                session.id,
                {"prompt": task.prompt},
            )
            await self.ipc.send(ipc_id, request_msg)

            # 5. Aguarda resposta
            response_msg = await self.ipc.receive(
                ipc_id, timeout=AGENT_TIMEOUT_SECONDS
            )

            # 6. Atualiza sessão com a resposta
            self.session_manager.update(
                session.id, payload=response_msg.payload
            )

            logger.info(
                "Agente executado com sucesso",
                extra={
                    "agent_id": task.agent_id,
                    "session_id": session.id,
                    "response_type": response_msg.type,
                },
            )

            result = AgentResult(
                agent_id=task.agent_id,
                session_id=session.id,
                status="success",
                response=response_msg.payload,
            )

        except TimeoutError as e:
            logger.warning(
                "Agente excedeu timeout",
                extra={
                    "agent_id": task.agent_id,
                    "session_id": session.id,
                    "timeout": AGENT_TIMEOUT_SECONDS,
                    "error": str(e),
                },
            )
            result = AgentResult(
                agent_id=task.agent_id,
                session_id=session.id,
                status="timeout",
                response={},
                error=str(e),
            )

        except Exception as e:
            logger.error(
                "Erro ao executar agente",
                extra={
                    "agent_id": task.agent_id,
                    "session_id": session.id,
                    "error": str(e),
                },
            )
            result = AgentResult(
                agent_id=task.agent_id,
                session_id=session.id,
                status="error",
                response={},
                error=str(e),
            )

        finally:
            # Cleanup: fecha sessão, socket IPC e container
            try:
                self.session_manager.close(session.id)
            except Exception:
                pass

            try:
                await self.ipc.close(ipc_id)
            except Exception:
                pass

            if container_id:
                try:
                    await self.runner.stop(container_id)
                except Exception:
                    pass

        return result
