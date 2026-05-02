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
    
    while iterations < max_iterations:
        iterations += 1
        
        # Converte ferramentas para formato OpenAI se necessário
        openai_tools = []
        for tool in tools:
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
        _prompt_tokens = getattr(response, "prompt_tokens", 0) or len(json.dumps(compressed_messages)) // 4
        _completion_tokens = getattr(response, "completion_tokens", 0) or len(response.text or "") // 4
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
                        _now_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"
                        _start_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"
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

    return final_response
