"""Runner IPC para execução de agentes ADK GeminiClaw em modo container."""

import asyncio
import os
import sys
import struct
import traceback
from typing import Any

from src.logger import get_logger
from src.ipc import Message, HEADER_SIZE, create_message

logger = get_logger(__name__)

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
                    
                    from google.adk.runners import InMemoryRunner
                    from google.genai.types import Content, Part
                    
                    # Inicializa o Runner para esta execução
                    runner = InMemoryRunner(agent=agent)
                    # auto_create_session=True garante que não falhe por falta de sessão no serviço em memória
                    runner.auto_create_session = True
                    
                    # Prepara a mensagem no formato estruturado do ADK
                    new_msg = Content(role="user", parts=[Part(text=prompt)])
                    
                    full_text = ""
                    async for event in runner.run_async(
                        user_id="user",
                        session_id=session_id,
                        new_message=new_msg
                    ):
                        # Coleta texto das partes do conteúdo do evento
                        if event.content and event.content.parts:
                            for part in event.content.parts:
                                if part.text:
                                    full_text += part.text
                    
                    resposta = {"resposta": full_text}
                    
                    # Se não houve texto mas houve erro no evento, loga
                    if not full_text:
                        logger.warning("Agente retornou resposta vazia")

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
        writer.close()
        await writer.wait_closed()
