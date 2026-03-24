"""Orquestrador principal do GeminiClaw.

Coordena a execução de múltiplos agentes em containers Docker,
gerenciando sessões, IPC e tratamento de falhas parciais.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS
from src.session import SessionManager
from src.runner import ContainerRunner
from src.ipc import IPCChannel, create_message, Message
from src.output_manager import OutputManager
from src.autonomous_loop import AutonomousLoop

logger = get_logger(__name__)

# Registro de agentes disponíveis: tipo → imagem Docker
AGENT_REGISTRY: dict[str, str] = {
    "base": "geminiclaw-base",
    "researcher": "geminiclaw-researcher",
    "planner": "geminiclaw-planner",
    "validator": "geminiclaw-validator",
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

    def _clean_json_text(self, text: str) -> str:
        """Limpa o texto da resposta para extrair apenas o conteúdo JSON.
        
        Tenta encontrar o primeiro '[' ou '{' e o último ']' ou '}' 
        para extrair o JSON mesmo com texto ao redor.
        """
        if not text:
            return ""
            
        # 1. Tenta remover blocos de código markdown
        text = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", text, flags=re.DOTALL)
        
        # 2. Busca pelo conteúdo entre o primeiro [ ou { e o último ] ou }
        # Isso ajuda se o agente incluir texto fora do markdown
        match = re.search(r"([\[{].*[\]}])", text, re.DOTALL)
        if match:
            text = match.group(1)
            
        return text.strip()

    async def handle_request(
        self,
        prompt: str,
        agent_tasks: list[AgentTask] | None = None,
    ) -> OrchestratorResult:
        """Processa uma solicitação do usuário via loop autônomo.

        Args:
            prompt: Solicitação do usuário.
            agent_tasks: Lista de tarefas de agentes (se fornecido, pula o loop autônomo).

        Returns:
            Resultado consolidado com respostas de todos os agentes.
        """
        # Cria a sessão mestra para a orquestração
        master_session = self.session_manager.create("orchestrator")
        
        # Se tarefas explícitas forem fornecidas, executa sequencialmente (compatibilidade)
        if agent_tasks:
            logger.info("Executando tarefas explícitas fornecidas (bypass autonomous loop)")
            results = []
            for task in agent_tasks:
                result = await self._execute_agent(task, master_session.id)
                results.append(result)
            
            succeeded = sum(1 for r in results if r.status == "success")
            failed = len(results) - succeeded
            all_artifacts = self.output_manager.list_artifacts(master_session.id)
            
            self.session_manager.close(master_session.id)
            return OrchestratorResult(
                results=results,
                total=len(results),
                succeeded=succeeded,
                failed=failed,
                artifacts=all_artifacts,
            )

        # Caso contrário, usa o loop autônomo (Etapa S7)
        loop = AutonomousLoop(self)
        result = await loop.run(prompt, master_session.id)
        
        # Atualiza a sessão mestra com o resultado consolidado
        final_status = "success" if result.succeeded == result.total and result.total > 0 else "failed"
        self.session_manager.update(
            master_session.id, 
            status=final_status,
            payload={
                "prompt": prompt,
                "summary": {
                    "total": result.total,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "artifacts_count": len(result.artifacts)
                }
            }
        )
        self.session_manager.close(master_session.id)
        
        return result

    async def _execute_agent(self, task: AgentTask, master_session_id: str | None = None) -> AgentResult:
        """Executa o ciclo de vida completo de um único agente.

        Ciclo: cria sessão → cria socket IPC → spawna container →
        aguarda conexão → envia prompt → recebe resposta → cleanup.

        Args:
            task: Definição da tarefa do agente.
            master_session_id: ID da sessão mestra para compartilhamento de estado.

        Returns:
            Resultado da execução do agente.
        """
        # Delay anti-429
        await asyncio.sleep(2)
        
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

            # 0. Inicializa diretórios de output e logs únicos para esta execução de agente
            # Etapa 9: Usa a sessão mestra se disponível para compartilhamento de arquivos
            effective_session_id = master_session_id or session.id
            unique_task_id = f"{task.agent_id}_{session.id[:8]}"
            
            self.output_manager.init_session(effective_session_id)
            self.output_manager.get_task_dir(effective_session_id, unique_task_id)
            self.output_manager.get_logs_dir(effective_session_id, unique_task_id)

            # 1. Cria socket IPC
            await self.ipc.create_socket(ipc_id)

            # 2. Spawna container mapeando diretórios específicos para /outputs e /logs
            ipc_port = self.ipc.get_port(ipc_id)
            container_id = await self.runner.spawn(
                task.agent_id, 
                task.image, 
                session.id, 
                ipc_port=ipc_port, 
                output_session_id=f"{effective_session_id}/{unique_task_id}",
                logs_session_id=f"{effective_session_id}/{unique_task_id}"
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

    async def _run_planning_loop(self, prompt: str, master_session_id: str) -> list[AgentTask]:
        """Executa o ciclo de planejamento (Planner -> Validator).

        Args:
            prompt: Solicitação original do usuário.
            master_session_id: ID da sessão mestra para logs.

        Returns:
            Lista de AgentTask aprovadas.
        """
        logger.info(
            "Iniciando ciclo de planejamento", 
            extra={"prompt": prompt, "master_session_id": master_session_id}
        )
        
        feedback = ""
        last_plan_str = ""
        
        for iteration in range(3):
            # 1. Executa o Planner
            planner_prompt = f"Crie um plano para: {prompt}"
            if feedback:
                planner_prompt += f"\n\nO plano anterior foi rejeitado: {feedback}. Por favor, revise."
            
            planner_task = AgentTask(
                agent_id="planner", 
                image=AGENT_REGISTRY["planner"], 
                prompt=planner_prompt
            )
            
            planner_result = await self._execute_agent(planner_task, master_session_id)
            if planner_result.status != "success" or "error" in planner_result.response:
                err = planner_result.error or planner_result.response.get("error", "Erro desconhecido")
                logger.error("Falha no Agente Planejador", extra={"error": err})
                return []
            
            # Tenta extrair JSON da resposta
            plan_text = self._clean_json_text(planner_result.response.get("text", ""))
            try:
                plan_data = json.loads(plan_text)
                last_plan_str = json.dumps(plan_data, indent=2)
            except Exception as e:
                logger.error("Erro ao parsear plano do Planner", extra={"error": str(e), "text": plan_text})
                feedback = f"Erro de formato no JSON: {str(e)}. Envie APENAS o JSON válido."
                continue
            
            # 2. Executa o Validator
            validator_prompt = f"Revise este plano:\n{last_plan_str}\n\nPara a solicitação: {prompt}"
            validator_task = AgentTask(
                agent_id="validator", 
                image=AGENT_REGISTRY["validator"], 
                prompt=validator_prompt
            )
            
            validator_result = await self._execute_agent(validator_task, master_session_id)
            if validator_result.status != "success" or "error" in validator_result.response:
                err = validator_result.error or validator_result.response.get("error", "Erro desconhecido")
                logger.error("Falha no Agente Validador", extra={"error": err})
                return []
            
            val_text = self._clean_json_text(validator_result.response.get("text", ""))
            try:
                val_data = json.loads(val_text)
                
                status = val_data.get("status", "revision_needed")
                reason = val_data.get("reason", "")
                
                if status == "approved":
                    logger.info("Plano aprovado pelo Validador", extra={"iteration": iteration + 1})
                    tasks = []
                    for t in plan_data:
                        tasks.append(AgentTask(
                            agent_id=t.get("agent_id", "base"),
                            image=t.get("image", AGENT_REGISTRY.get(t.get("agent_id", "base"), "geminiclaw-base")),
                            prompt=t.get("prompt", prompt)
                        ))
                    return tasks
                elif status == "rejected":
                    logger.warning("Plano rejeitado definitivamente", extra={"reason": reason})
                    return []
                else:
                    feedback = reason or "Plano precisa de revisão."
                    logger.info("Solicitando revisão do plano", extra={"iteration": iteration + 1, "reason": feedback})
                    
            except Exception as e:
                logger.error("Erro ao parsear resposta do Validador", extra={"error": str(e), "text": val_text})
                feedback = "Erro ao ler sua validação. Por favor, tente novamente com o formato JSON correto."

        logger.error("Máximo de iterações de planejamento atingido")
        return []
