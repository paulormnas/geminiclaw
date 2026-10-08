import os
import json
import asyncio
import traceback
import pathlib
from typing import Any, List, Dict, Callable, Optional, AsyncGenerator
from dataclasses import dataclass, field

from src.agent_runtime.context import get_agent_context_optional
from src.egress.fragments import ContentOrigin, PromptFragment, dumps_messages, labeled, tool_result_fragment
from src.llm.base import LLMProvider, ToolCall, LLMResponse
from src.llm.metering import bound_execution_id, provider_name, record_llm_call
from src.llm.pricing import estimate_cost
from src.llm.factory import get_provider
from src.llm.context_compression import compress_messages
from src.llm.context_injection import build_workspace_context_fragments
from src.logger import get_logger
from src.telemetry import get_telemetry

logger = get_logger(__name__)


def _task_env() -> Dict[str, str]:
    """Resolve o estado por tarefa (sessão, papel, diretório de output, etc.).

    Roadmap V16/ADR 014: dentro do ``AgentRuntime``, esse estado vem do ``AgentContext``
    vinculado à ``Task`` asyncio corrente (``contextvars``), nunca de ``os.environ`` (global
    ao processo e portanto inseguro com múltiplas tarefas concorrentes). Fora dele (chamadas
    diretas ao laço, como os planejamentos do Researcher), não há ``AgentContext`` e o estado
    vem de ``os.environ``.

    Returns:
        Dicionário com as mesmas chaves antes lidas diretamente de
        ``os.environ`` (``SESSION_ID``, ``TASK_NAME``, ``OUTPUT_BASE_DIR``,
        ``AGENT_ID``, ``EXECUTION_ID``, ``PROVIDER_NAME``, ``MODEL_ID``).
    """
    ctx = get_agent_context_optional()
    if ctx is not None:
        return {
            "SESSION_ID": ctx.session_id,
            "TASK_NAME": ctx.task_name,
            "OUTPUT_BASE_DIR": str(ctx.output_dir.parent) if ctx.output_dir else "",
            "AGENT_ID": ctx.agent_id,
            "EXECUTION_ID": ctx.execution_id or ctx.session_id,
            "PROVIDER_NAME": "",  # resolvido pelo ModelRouter; provider já é explícito aqui
            "MODEL_ID": ctx.model,
        }
    return {
        # SESSION_ID sem default "truthy": código a jusante (override de
        # session_id em tool calls) depende de string vazia == "ausente" para
        # decidir se sobrescreve o argumento gerado pelo LLM (V13.1.1). Um
        # default como "unknown" aqui faria esse código achar que sempre há
        # um SESSION_ID canônico definido. O fallback "unknown" para exibição/
        # telemetria é aplicado no ponto de uso (``_session_id or "unknown"``).
        "SESSION_ID": os.environ.get("SESSION_ID", ""),
        "TASK_NAME": os.environ.get("TASK_NAME", ""),
        "OUTPUT_BASE_DIR": os.environ.get("OUTPUT_BASE_DIR", ""),
        "AGENT_ID": os.environ.get("AGENT_ID", "agent"),
        "EXECUTION_ID": os.environ.get("EXECUTION_ID", os.environ.get("SESSION_ID", "")) or bound_execution_id(),
        "PROVIDER_NAME": "unknown",
        "MODEL_ID": "unknown",
    }

def _label_history_message(message: Dict[str, Any], produced_tainted: bool) -> Dict[str, Any]:
    """Rotula uma mensagem de histórico sem rótulo: assistente = produto deste modelo; demais = instrução."""
    content = message.get("content")
    if "_fragments" in message or not isinstance(content, str) or not content:
        return message
    tainted = message.get("role") == "assistant" and produced_tainted
    labeled_message = labeled(
        message.get("role", "user"),
        PromptFragment(content, ContentOrigin.INSTRUCAO, tainted=tainted, source="historico"),
    )
    labeled_message.update({k: v for k, v in message.items() if k not in labeled_message})
    return labeled_message


@dataclass
class AgentState:
    """Estado interno do agente, passado aos callbacks before/after."""
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
    max_iterations: int = 10,
    provider: Optional[LLMProvider] = None,
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
        provider: Provedor LLM a usar (Roadmap V16: resolvido por papel via
            ``ModelRouter`` no runtime em processo). Se omitido, usa o provedor
            do papel ``researcher`` (``get_provider()``, via ``ModelRouter``).

    Returns:
        Resposta final do agente como string.
    """
    provider = provider or get_provider()
    history = history or []
    
    # Estado para callbacks
    agent_state = AgentState()
    
    # 1. Callback 'before'
    if before_callback:
        try:
            await before_callback(agent_state)
        except Exception as e:
            logger.error(f"Erro no before_callback: {e}")

    # v18.5-egress-gate — o produto deste modelo é contaminado se ele aceita dados brutos (ADR 019 §3.8).
    produced_tainted = bool(getattr(provider, "tainted_output", False))

    # Prepara mensagens iniciais (rotuladas por origem; o EgressGate expande as marcas em linha do texto)
    messages = []
    if instruction:
        messages.append(labeled("system", PromptFragment(instruction, ContentOrigin.INSTRUCAO, source="system")))

    # Adiciona histórico se houver (mensagem sem rótulo é rotulada aqui: assistente = produto deste modelo)
    messages.extend(_label_history_message(m, produced_tainted) for m in history)

    # Adiciona prompt atual
    messages.append(labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO, source="prompt")))
    
    final_response = ""
    iterations = 0

    # V12.2.1/V12.2.3 — Rastreamento de erros por ferramenta
    error_tracker = ErrorTracker(threshold=3)
    tool_failure_count: Dict[str, int] = {}   # conta falhas acumuladas por ferramenta
    _alert_injected = False   # para injetar alerta apenas uma vez por sessão

    while iterations < max_iterations:
        iterations += 1

        # V13.4.1/V13.4.2 — Injetar bloco de contexto do workspace antes de cada LLM call.
        # Lê o manifest da sessão atual e inclui artefatos disponíveis, resumo do último
        # step e, quando falhou, o código anterior + erro específico.
        # V16 — estado por tarefa vem do AgentContext (contextvars) ou, fora do
        # AgentRuntime, de os.environ (ver _task_env()).
        _task = _task_env()
        _env_session_id = _task["SESSION_ID"]
        _env_task_name = _task["TASK_NAME"]
        _env_output_base = _task["OUTPUT_BASE_DIR"]
        if _env_session_id and _env_task_name and _env_output_base:
            try:
                _session_dir = pathlib.Path(_env_output_base) / _env_session_id
                _max_lines = int(os.environ.get("MAX_CODE_CONTEXT_LINES", "150"))
                _ctx_fragments = build_workspace_context_fragments(
                    session_dir=_session_dir,
                    session_id=_env_session_id,
                    task_name=_env_task_name,
                    max_code_context_lines=_max_lines,
                    code_tainted=produced_tainted,
                )
                # Inserir como mensagem de sistema imediatamente antes desta iteração
                messages.append(labeled("user", *_ctx_fragments))
                logger.debug(
                    "V13.4.1: Bloco de contexto do workspace injetado",
                    extra={"session_id": _env_session_id, "iteration": iterations},
                )
            except Exception as _ctx_err:
                logger.warning(
                    "V13.4.1: Falha ao construir bloco de contexto; continuando sem ele",
                    extra={"error": str(_ctx_err)},
                )
        
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
        _session_id = _env_session_id or "unknown"
        _task_name = _env_task_name or None
        _exec_id = _task["EXECUTION_ID"] or _session_id
        _agent_id = _task["AGENT_ID"] or "agent"
        _telemetry = get_telemetry()

        response: LLMResponse = await provider.generate(
            messages=compressed_messages,
            tools=openai_tools if openai_tools else None,
            system=instruction
        )
        _llm_latency_ms = int((_time.monotonic() - _t_llm_start) * 1000)

        # V5.7 — Telemetria: llm_response (token usage)
        # V11.2.1 — Corrigido: lê usage do dict padronizado em vez de getattr direto
        _prompt_tokens = response.usage.get("prompt_tokens", 0) or len(dumps_messages(compressed_messages)) // 4
        _completion_tokens = response.usage.get("completion_tokens", 0) or len(response.text or "") // 4
        # V16 — no runtime em processo, o provedor é explícito (parâmetro `provider`,
        # resolvido por papel via ModelRouter); deriva o nome a partir da própria
        # instância em vez de uma variável global (não confiável com múltiplos papéis
        # concorrentes). Mantém fallback em os.environ para chamadas fora do AgentRuntime.
        _provider_name = provider_name(provider) or _task["PROVIDER_NAME"] or "unknown"
        _model_name = provider.model_name or _task["MODEL_ID"] or "unknown"
        # v18.5-model-catalog-locality — versão efetiva servida (rastreia troca de versão na sessão).
        from src.llm.allocation import record_call_version
        from src.llm.versions import normalize_version

        _versao_efetiva = record_call_version(
            _provider_name, _model_name, normalize_version(getattr(response, "versao_efetiva", None))
        )
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
            estimated_cost_usd=estimate_cost(
                _provider_name, _model_name, _prompt_tokens, _completion_tokens,
                response.usage.get("cached_tokens", 0) or 0,
            ),
            context_window_used=_prompt_tokens + _completion_tokens,
            context_window_max=max_ctx,
            was_compressed=was_compressed,
            versao_efetiva=_versao_efetiva,
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

            # V13.1.1 — Forçar session_id canônico para python_interpreter.
            # O LLM pode gerar valores arbitrários ("1", "nova_sessao" etc.). Para
            # garantir que todos os artefatos de uma sessão fiquem no mesmo diretório,
            # sobrescrevemos sempre com o valor de SESSION_ID do ambiente antes de
            # qualquer processamento adicional.
            if tool_call.name == "python_interpreter":
                env_session_id = _env_session_id
                if env_session_id:
                    original_sid = tool_call.arguments.get("session_id", "<ausente>")
                    tool_call.arguments["session_id"] = env_session_id
                    if original_sid != env_session_id:
                        logger.info(
                            "V13.1.1: session_id sobrescrito pelo valor canônico do ambiente",
                            extra={
                                "tool": tool_call.name,
                                "original": original_sid,
                                "canonical": env_session_id,
                            },
                        )
            
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
                                tool_call.arguments["session_id"] = _env_session_id or "default_session"
                                logger.debug(f"Injetando session_id automático em {tool_call.name}")

                            # Injetar TASK_NAME se não fornecido
                            if "task_name" in required and "task_name" not in tool_call.arguments:
                                tool_call.arguments["task_name"] = _env_task_name or "default_task"
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
                        messages.append(
                            labeled("user", PromptFragment(alert_msg, ContentOrigin.INSTRUCAO, source="sistema"))
                        )
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
                            arguments={k: str(v)[:500] for k, v in tool_call.arguments.items()},
                            task_name=_task_name,
                        )
                    except Exception:
                        pass
            
            # Adiciona o resultado da ferramenta ao histórico, rotulado pela origem do conteúdo
            messages.append(
                labeled(
                    "tool",
                    tool_result_fragment(tool_call.name, result, tool_call.arguments),
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                )
            )

    # 6. Callback 'after'
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
            messages.append(labeled("user", PromptFragment(recovery_msg, ContentOrigin.INSTRUCAO, source="sistema")))
            try:
                _t_rec = _time.monotonic()
                recovery_response = await provider.generate(
                    messages=messages,
                    tools=None,  # sem ferramentas para forçar resposta direta
                    system=instruction,
                )
                record_llm_call(provider, recovery_response, int((_time.monotonic() - _t_rec) * 1000), _agent_id, _task_name)
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
