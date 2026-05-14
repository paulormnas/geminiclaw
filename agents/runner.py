"""Runner IPC para execução de agentes ADK GeminiClaw em modo container."""

import asyncio
import os
import sys
import struct
import traceback
from typing import Any

from src.logger import get_logger
from src.ipc import Message, HEADER_SIZE, create_message
from src.llm_cache import LLMResponseCache
from src.telemetry import get_telemetry

logger = get_logger(__name__)


def _build_response_payload(text: str, telemetry: Any) -> dict:
    """Monta o payload de resposta IPC incluindo snapshot de telemetria (V12.3.1).

    O campo ``_telemetry`` transporta o buffer não-gravado do container para
    o orquestrador, que o injeta em seu próprio singleton. Funciona mesmo
    quando o container não tem acesso direto ao PostgreSQL.

    O ``flush()`` normal é o mecanismo primário (executado no ``finally``);
    este canal é o fallback para garantir zero loss.

    Args:
        text: Texto de resposta do agente.
        telemetry: Instância de TelemetryCollector com o buffer atual.

    Returns:
        Dict com ``text`` e ``_telemetry``.
    """
    return {
        "text": text,
        "_telemetry": telemetry.drain_buffer(),
    }

async def run_ipc_loop(agent: Any) -> None:
    """Inicia o loop IPC para receber tarefas e executá-las usando o agente.

    Args:
        agent: A instância do google.adk.agents.Agent configurada.
    """
    session_id = os.environ.get("SESSION_ID", "")
    agent_id = os.environ.get("AGENT_ID", "")

    if not session_id or not agent_id:
        logger.error("Variaveis de ambiente SESSION_ID ou AGENT_ID não definidas.")
        sys.exit(1)

    # O volume Docker sempre mapeia o socket para este caminho fixo internamente (se não for TCP)
    socket_name = os.environ.get("AGENT_SOCKET_NAME", "agent.sock")
    socket_path = f"/tmp/geminiclaw-ipc/{socket_name}"
    
    # Verifica se deve usar TCP (Mac compatibility)
    ipc_port = os.environ.get("AGENT_IPC_PORT")
    ipc_host = os.environ.get("AGENT_IPC_HOST", "host.docker.internal")

    # Aguardar até que possamos conectar ao socket/servidor
    max_retries = 60
    for attempt in range(max_retries):
        try:
            if ipc_port:
                if attempt == 0:
                    logger.info("Tentando conexão IPC via TCP", extra={"host": ipc_host, "port": ipc_port})
                reader, writer = await asyncio.open_connection(ipc_host, int(str(ipc_port)))
            else:
                if attempt == 0:
                    logger.info("Aguardando socket IPC (UNIX)", extra={"socket": socket_path})
                reader, writer = await asyncio.open_unix_connection(socket_path)
            
            logger.info("Conectado ao socket IPC do orquestrador")
            break
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            if attempt == 0:
                msg = "Servidor IPC não pronto, aguardando..."
                logger.info(msg, extra={"socket": socket_path, "port": ipc_port})
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error("Erro inesperado ao tentar conectar no IPC", extra={"error": str(e)})
            sys.exit(1)
    else:
        logger.error("Timeout ao aguardar conexão IPC", extra={"port": ipc_port, "socket": socket_path})
        sys.exit(1)

    try:
        while True:
            # Ler cabeçalho (4 bytes length-prefix)
            try:
                header = await reader.readexactly(HEADER_SIZE)
            except asyncio.IncompleteReadError:
                logger.info("Conexão IPC encerrada pelo orquestrador.")
                break

            msg_length = struct.unpack(">I", header)[0]

            # Ler corpo da mensagem (JSON payload)
            body = await reader.readexactly(msg_length)
            message = Message.deserialize(body)

            if message.type == "request":
                prompt = message.payload.get("prompt", "")
                
                try:
                    logger.info("Executando agente via Runner", extra={"prompt_preview": prompt[:50]})
                    
                    llm_cache = LLMResponseCache()
                    cached_text = llm_cache.get(prompt, agent.model)
                    
                    if cached_text is not None:
                        full_text = cached_text
                        logger.info("Retornando resposta instantânea do cache LLM")
                    else:
                        from src.llm.agent_loop import run_agent_loop
                        
                        full_text = await run_agent_loop(
                            prompt=prompt,
                            instruction=agent.instruction,
                            tools=agent.tools,
                            before_callback=agent.before_agent_callback,
                            after_callback=agent.after_agent_callback
                        )
                        
                        if full_text:
                            llm_cache.set(prompt, agent.model, full_text)
                    

                    logger.info("Agente finalizou execução", extra={"full_text_length": len(full_text), "full_text_preview": full_text[:100]})
                    
                    # Se não houve texto mas houve erro no evento, loga
                    if not full_text:
                        logger.warning("Agente retornou resposta vazia")

                    # V12.3.1 — Inclui snapshot do buffer de telemetria no payload
                    # para garantir que dados de containers sem acesso direto ao
                    # PostgreSQL sejam propagados ao orquestrador via IPC.
                    telemetry_instance = get_telemetry()
                    resposta = _build_response_payload(full_text, telemetry_instance)
                    
                    # Enviar a resposta de volta ao orquestrador
                    resp_msg = create_message("response", session_id, resposta)


                    
                except Exception as e:
                    logger.error("Erro durante execução do agente", extra={"error": str(e), "trace": traceback.format_exc()})
                    resp_msg = create_message("response", session_id, {"error": str(e), "status": "error"})

                data = resp_msg.serialize()
                writer.write(data)
                await writer.drain()
            else:
                logger.warning(f"Tipo de mensagem inesperado: {message.type}")
    
    except asyncio.CancelledError:
        logger.info("Processo interrompido.")
    except Exception as e:
        logger.error("Erro no loop IPC", extra={"error": str(e), "trace": traceback.format_exc()})
    finally:
        # V11.1.1 — Flush explícito antes de encerrar o container para garantir
        # que todos os eventos de telemetria sejam persistidos, mesmo quando o
        # buffer não atingiu o limiar automático de 50 itens.
        try:
            await get_telemetry().flush()
            logger.info("Flush de telemetria concluído antes do encerramento.")
        except Exception as _flush_err:
            logger.error(
                "Erro no flush de telemetria no encerramento",
                extra={"error": str(_flush_err)},
            )
        writer.close()
        await writer.wait_closed()
