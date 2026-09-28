"""HumanFeedbackSkill — Human-in-the-Loop com autonomia como padrão (Roadmap V15.3 / Spec G5).

Filosofia: o agente investiga por conta própria antes de perguntar; o pesquisador só é
interrompido quando o contexto está genuinamente ausente (modo `assisted`). Nos modos
`semi`/`auto`, a skill nunca bloqueia — documenta a suposição adotada e retorna.

Quando bloqueante (modo `assisted`), a skill executa um round-trip IPC com o host:
envia uma mensagem tipo ``ask_researcher`` na MESMA conexão usada pelo `agents/runner.py`
e aguarda uma mensagem de resposta, sem interferir no protocolo request/response normal
(o container só volta a ler a próxima mensagem de nível superior depois que a chamada
de tool call retorna).
"""

from __future__ import annotations

import os
import struct
from typing import Any, Optional

from src.skills.base import BaseSkill, SkillResult
from src.ipc import Message, HEADER_SIZE, create_message
from src.logger import get_logger

logger = get_logger(__name__)


class HumanFeedbackSkill(BaseSkill):
    """Skill que permite ao Researcher/Developer consultar o pesquisador humano."""

    name = "ask_researcher"
    description = (
        "Use esta ferramenta para perguntar ao pesquisador humano QUANDO houver uma "
        "ambiguidade genuinamente bloqueante no contexto disponível — DEPOIS de investigar "
        "alternativas por conta própria. Sempre preencha 'why_cant_proceed' explicando por "
        "que você não pode decidir sozinho. NUNCA use para dúvidas resolvíveis com um padrão "
        "razoável e documentável (ex: split 80/20, seed=42) — nesses casos, decida e documente "
        "em 'scientific_rationale' em vez de perguntar."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Pergunta objetiva para o pesquisador."},
            "context": {"type": "string", "description": "Contexto relevante para a decisão."},
            "why_cant_proceed": {
                "type": "string",
                "description": "Por que o agente não pode resolver isso sozinho.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Opções numeradas para o pesquisador escolher, se aplicável.",
            },
        },
        "required": ["question"],
    }

    async def run(
        self,
        question: str,
        context: str = "",
        why_cant_proceed: str = "",
        options: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> SkillResult:
        mode = os.environ.get("SESSION_MODE", "assisted")

        if not why_cant_proceed:
            logger.warning(
                "ask_researcher chamado sem 'why_cant_proceed' — agente perguntou sem "
                "justificar por que não pode resolver sozinho",
                extra={"question": question[:200]},
            )

        if mode in ("semi", "auto"):
            assumption = (
                f"[Modo {mode} — suposição documentada, sem consulta ao pesquisador] "
                f"Pergunta: {question} | Prosseguindo com a melhor suposição razoável a "
                "partir do contexto disponível; documente esta decisão em 'scientific_rationale'."
            )
            logger.info(
                "ask_researcher: modo não-bloqueante, documentando suposição",
                extra={"question": question[:200], "mode": mode},
            )
            return SkillResult(success=True, output=assumption, metadata={"mode": mode, "blocked": False})

        # Modo assisted: round-trip IPC bloqueante real com o host.
        from agents.runner import get_active_ipc_connection

        conn = get_active_ipc_connection()
        if conn is None:
            msg = "ask_researcher chamado sem conexão IPC ativa (fora de um container gerenciado)."
            logger.warning(msg)
            return SkillResult(success=False, output="", error=msg)

        reader, writer = conn
        session_id = os.environ.get("SESSION_ID", "")

        ask_msg = create_message(
            "ask_researcher",
            session_id,
            {
                "question": question,
                "context": context,
                "why_cant_proceed": why_cant_proceed,
                "options": options or [],
            },
        )
        writer.write(ask_msg.serialize())
        await writer.drain()

        header = await reader.readexactly(HEADER_SIZE)
        length = struct.unpack(">I", header)[0]
        body = await reader.readexactly(length)
        answer_msg = Message.deserialize(body)

        answer = answer_msg.payload.get("answer", "")
        return SkillResult(success=True, output=answer, metadata={"mode": mode, "blocked": True})
