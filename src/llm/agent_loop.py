import os
import json
import asyncio
import traceback
from typing import Any, List, Dict, Callable, Optional, AsyncGenerator
from dataclasses import dataclass, field

from src.llm.base import LLMProvider, ToolCall, LLMResponse
from src.llm.factory import get_provider
from src.llm.context_compression import compress_messages
from src.logger import get_logger
from src.telemetry import get_telemetry

logger = get_logger(__name__)

@dataclass
class AgentState:
    """Estado interno do agente, compatível com ADK callbacks."""
    state: Dict[str, Any] = field(default_factory=dict)


# Padrões heurísticos de respostas declarativas (V12.2.2)
_DECLARATIVE_PATTERNS = (
    "vou criar",
    "vou fazer",
    "vou gerar",
    "vou executar",
    "vou processar",
    "irei criar",
    "irei fazer",
    "irei gerar",
    "irei executar",
    "vou usar",
    "vou tentar",
)


class ErrorTracker:
    """Rastreia erros consecutivos por ferramenta para ativar recuperação (V12.2.1).

    Attributes:
        threshold: Número de erros consecutivos na mesma ferramenta/tipo
                   para acionar o alerta.
    """

    def __init__(self, threshold: int = 3) -> None:
        """Inicializa o rastreador com limiar configurável.

        Args:
            threshold: Número de erros consecutivos para acionar alerta.
        """
        self.threshold = threshold
        self._last_tool: Optional[str] = None
        self._last_error_type: Optional[str] = None
        self._count: int = 0

    def track(self, tool_name: str, error_type: str) -> bool:
        """Registra um erro e verifica se o limiar foi atingido.

        Args:
            tool_name: Nome da ferramenta que falhou.
            error_type: Tipo da exceção (ex: 'TypeError').

        Returns:
            True se o limiar de erros consecutivos foi atingido, False caso
            contrário.
        """
        if tool_name == self._last_tool and error_type == self._last_error_type:
            self._count += 1
        else:
            self._last_tool = tool_name
            self._last_error_type = error_type
            self._count = 1

        return self._count >= self.threshold

    def get_message(self, tool_name: str, error_type: str, count: int) -> str:
        """Gera a mensagem de alerta a ser injetada no contexto do agente.

        Args:
            tool_name: Nome da ferramenta com erros repetidos.
            error_type: Tipo da exceção.
            count: Número de falhas consecutivas.

        Returns:
            String com a mensagem de recuperação formatada.
        """
        return (
            f"[ATENÇÃO DO SISTEMA]\n"
            f"A ferramenta '{tool_name}' falhou {count} vezes consecutivas com o erro '{error_type}'.\n"
            f"Você DEVE mudar completamente sua abordagem. Opções:\n"
            f"1. Simplificar o código removendo a parte problemática\n"
            f"2. Usar uma estratégia alternativa\n"
            f"3. Gerar a resposta sem usar essa ferramenta\n"
            f"NÃO repita a mesma abordagem."
        )

async def run_agent_loop(
    prompt: str,
    instruction: str,
    tools: List[Callable],
    history: List[Dict[str, Any]] = None,
    before_callback: Optional[Callable] = None,
    after_callback: Optional[Callable] = None,
    max_iterations: int = 10
) -> str:
    """Executa o loop de pensamento do agente (ReAct).
    
    Args:
        prompt: Pergunta ou tarefa do usuário.
        instruction: Instrução de sistema (system prompt).
        tools: Lista de funções Python que podem ser chamadas como ferramentas.
        history: Histórico da conversa (opcional).
        before_callback: Função chamada antes do loop começar (ex: carregar sessão).
        after_callback: Função chamada após o loop terminar (ex: persistir sessão).
        max_iterations: Limite de chamadas de ferramenta para evitar loops infinitos.
    
    Returns:
        Resposta final do agente como string.
    """
    provider = get_provider()
    history = history or []
    
    # Estado para callbacks
    agent_state = AgentState()
    
    # 1. Callback 'before' (compatível com ADK)
    if before_callback:
        try:
            await before_callback(agent_state)
        except Exception as e:
            logger.error(f"Erro no before_callback: {e}")

    # Prepara mensagens iniciais
    messages = []
    if instruction:
        messages.append({"role": "system", "content": instruction})
    
    # Adiciona histórico se houver
    messages.extend(history)
    
    # Adiciona prompt atual
    messages.append({"role": "user", "content": prompt})
    
    final_response = ""
    iterations = 0

    # V12.2.1/V12.2.3 — Rastreamento de erros por ferramenta
    error_tracker = ErrorTracker(threshold=3)
    tool_failure_count: Dict[str, int] = {}   # conta falhas acumuladas por ferramenta
    _alert_injected = False   # para injetar alerta apenas uma vez por sessão

    while iterations < max_iterations:
        iterations += 1
        
        # Converte ferramentas para formato OpenAI se necessário
        # V12.2.3 — Filtra ferramentas que falharam 4+ vezes
        _failed_tools = {name for name, cnt in tool_failure_count.items() if cnt >= 4}
        openai_tools = []
        for tool in tools:
            tool_name_key = getattr(tool, "__name__", None)
            if tool_name_key and tool_name_key in _failed_tools:
                continue  # Ferramenta banida por excesso de falhas
            if hasattr(tool, "parameters_schema") and tool.parameters_schema:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.__name__,
                        "description": tool.__doc__ or "",
                        "parameters": tool.parameters_schema
                    }
                })
            elif isinstance(tool, dict):
                openai_tools.append(tool)
            else:
                # Fallback simples se não houver schema (não recomendado)
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.__name__,
                        "description": tool.__doc__ or "",
                        "parameters": {"type": "object", "properties": {}}
                    }
                })

        # 2. Chama o LLM (com compressão de contexto para evitar estouro de memória no Pi 5)
        max_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        compressed_messages = await compress_messages(
            messages, 
            max_tokens=max_ctx, 
            system=instruction,
            provider=provider
        )
        was_compressed = len(compressed_messages) < len(messages)

        # V5.7 — Telemetria: llm_request
        import time as _time
        _t_llm_start = _time.monotonic()
        _session_id = os.environ.get("SESSION_ID", "unknown")
        _task_name = os.environ.get("TASK_NAME") or None
        _exec_id = os.environ.get("EXECUTION_ID", _session_id)
        _agent_id = os.environ.get("AGENT_ID", "agent")
        _telemetry = get_telemetry()

        response: LLMResponse = await provider.generate(
            messages=compressed_messages,
            tools=openai_tools if openai_tools else None,
            system=instruction
        )
        _llm_latency_ms = int((_time.monotonic() - _t_llm_start) * 1000)

        # V5.7 — Telemetria: llm_response (token usage)
        # V11.2.1 — Corrigido: lê usage do dict padronizado em vez de getattr direto
        _prompt_tokens = response.usage.get("prompt_tokens", 0) or len(json.dumps(compressed_messages)) // 4
        _completion_tokens = response.usage.get("completion_tokens", 0) or len(response.text or "") // 4
        _provider_name = os.environ.get("LLM_PROVIDER", "unknown")
        _model_name = os.environ.get("LLM_MODEL", "unknown")
        _telemetry.record_token_usage(
            execution_id=_exec_id,
            session_id=_session_id,
            agent_id=_agent_id,
            llm_provider=_provider_name,
            llm_model=_model_name,
            prompt_tokens=_prompt_tokens,
            completion_tokens=_completion_tokens,
            latency_ms=_llm_latency_ms,
            task_name=_task_name,
            context_window_used=_prompt_tokens + _completion_tokens,
            context_window_max=max_ctx,
            was_compressed=was_compressed,
        )
        
        # Adiciona resposta do assistente ao histórico
        messages.append(response.to_message())
        
        # 3. Se houver resposta textual, guardamos (pode ser a final ou parcial)
        if response.text:
            final_response = response.text
            
        # 4. Se não houver tool calls, o loop terminou
        if not response.tool_calls:
            break
            
        # 5. Executa tool calls
        for tool_call in response.tool_calls:
            logger.info(f"Agente chamando ferramenta: {tool_call.name}", extra={"tool_args": tool_call.arguments})
            
            # Encontra a função correspondente
            tool_func = next((t for t in tools if getattr(t, "__name__", "") == tool_call.name), None)
            
            if not tool_func:
                result = f"Erro: Ferramenta '{tool_call.name}' não encontrada."
            else:
                try:
                    # Se for um dicionário de ferramenta OpenAI (raro aqui), não conseguimos executar direto
                    if isinstance(tool_func, dict):
                         result = f"Erro: Ferramenta '{tool_call.name}' é um esquema estático, não executável."
                    else:
                        # V14: Injeção automática de metadados se exigidos pela ferramenta
                        if hasattr(tool_func, "parameters_schema") and tool_func.parameters_schema:
                            required = tool_func.parameters_schema.get("required", [])
                            properties = tool_func.parameters_schema.get("properties", {})
                            
                            # Injetar SESSION_ID se não fornecido
                            if "session_id" in required and "session_id" not in tool_call.arguments:
                                tool_call.arguments["session_id"] = os.environ.get("SESSION_ID", "default_session")
                                logger.debug(f"Injetando session_id automático em {tool_call.name}")
                                
                            # Injetar TASK_NAME se não fornecido
                            if "task_name" in required and "task_name" not in tool_call.arguments:
                                tool_call.arguments["task_name"] = os.environ.get("TASK_NAME", "default_task")
                                logger.debug(f"Injetando task_name automático em {tool_call.name}")

                        # V5.7 — Telemetria: tool_call_start
                        _t_tool_start = _time.monotonic()

                        # Verifica se é async
                        if asyncio.iscoroutinefunction(tool_func):
                            result = await tool_func(**tool_call.arguments)
                        else:
                            result = tool_func(**tool_call.arguments)

                        _tool_duration_ms = int((_time.monotonic() - _t_tool_start) * 1000)
                        
                    # Garante que o resultado seja string
                    if not isinstance(result, str):
                        result = json.dumps(result, ensure_ascii=False)

                    # V5.7 — Telemetria: tool_call_end (sucesso)
                    if not isinstance(tool_func, dict):
                        # V11.2.2 — Corrigido: _start_iso calculado a partir do instante ANTES
                        # da invocação (usando _t_tool_start já capturado antes), não após.
                        import datetime as _dt
                        _finished_dt = _dt.datetime.utcnow()
                        _started_dt = _finished_dt - _dt.timedelta(milliseconds=_tool_duration_ms)
                        _start_iso = _started_dt.isoformat() + "Z"
                        _now_iso = _finished_dt.isoformat() + "Z"
                        _telemetry.record_tool_usage(
                            execution_id=_exec_id,
                            session_id=_session_id,
                            agent_id=_agent_id,
                            tool_name=tool_call.name,
                            started_at=_start_iso,
                            finished_at=_now_iso,
                            duration_ms=_tool_duration_ms if 'result' in dir() else 0,
                            success=True,
                            arguments={k: str(v)[:100] for k, v in tool_call.arguments.items()},
                            result_summary=(result or "")[:500],
                            task_name=_task_name,
                        )

                except Exception as e:
                    logger.error(f"Erro ao executar {tool_call.name}: {e}", extra={"trace": traceback.format_exc()})
                    result = f"Erro ao executar ferramenta: {str(e)}"

                    # V12.2.1 — Rastrear erro; injetar alerta se limiar atingido
                    error_type = type(e).__name__
                    tool_failure_count[tool_call.name] = tool_failure_count.get(tool_call.name, 0) + 1
                    if error_tracker.track(tool_call.name, error_type) and not _alert_injected:
                        alert_msg = error_tracker.get_message(
                            tool_call.name, error_type, error_tracker._count
                        )
                        messages.append({"role": "user", "content": alert_msg})
                        logger.warning(
                            "ErrorTracker: alerta de erros repetitivos injetado",
                            extra={"tool": tool_call.name, "error_type": error_type, "count": error_tracker._count},
                        )
                        _alert_injected = True  # Injeta apenas uma vez por ativação
                    else:
                        _alert_injected = False  # Reseta quando o padrão muda

                    # V12.2.3 — Log quando ferramenta será removida na próxima iteração
                    if tool_failure_count.get(tool_call.name, 0) >= 4:
                        logger.warning(
                            "V12.2.3: Ferramenta removida por excesso de falhas",
                            extra={"tool": tool_call.name, "failures": tool_failure_count[tool_call.name]},
                        )

                    # V5.7 — Telemetria: tool_call_end (falha)
                    try:
                        _now_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"
                        _telemetry.record_tool_usage(
                            execution_id=_exec_id,
                            session_id=_session_id,
                            agent_id=_agent_id,
                            tool_name=tool_call.name,
                            started_at=_now_iso,
                            finished_at=_now_iso,
                            duration_ms=0,
                            success=False,
                            error_message=str(e)[:500],
                            task_name=_task_name,
                        )
                    except Exception:
                        pass
            
            # Adiciona o resultado da ferramenta ao histórico
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": result
            })

    # 6. Callback 'after' (compatível com ADK)
    if after_callback:
        try:
            await after_callback(agent_state)
        except Exception as e:
            logger.error(f"Erro no after_callback: {e}")

    # V12.2.2 — Detecção de resposta declarativa sem resultado concreto.
    # Se a resposta final contém apenas expressões de intenção e não houve
    # tool calls na última iteração, tenta uma última vez com prompt de recuperação.
    if final_response:
        _lower = final_response.lower()
        _is_declarative = (
            any(pat in _lower for pat in _DECLARATIVE_PATTERNS)
            and not response.tool_calls  # sem tool calls na resposta final
        )
        if _is_declarative:
            logger.warning(
                "V12.2.2: Resposta declarativa detectada, iniciando retry de recuperação",
                extra={"preview": final_response[:80]},
            )
            recovery_msg = (
                "[REQUÉRIO DO SISTEMA]\n"
                "Sua resposta anterior descreveu uma intenção, mas não produziu um resultado concreto.\n"
                "Por favor, EXECUTE a tarefa agora e fornecer um resultado concreto ou abordagem alternativa "
                "sem usar ferramentas que estão falhando."
            )
            messages.append({"role": "user", "content": recovery_msg})
            try:
                recovery_response = await provider.generate(
                    messages=messages,
                    tools=None,  # sem ferramentas para forçar resposta direta
                    system=instruction,
                )
                if recovery_response.text:
                    final_response = recovery_response.text
                    logger.info(
                        "V12.2.2: Resposta de recuperação obtida",
                        extra={"preview": final_response[:80]},
                    )
            except Exception as _rec_err:
                logger.warning(
                    "V12.2.2: Falha no retry de recuperação",
                    extra={"error": str(_rec_err)},
                )

    return final_response
