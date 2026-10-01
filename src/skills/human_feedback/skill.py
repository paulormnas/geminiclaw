"""HumanFeedbackSkill — Human-in-the-Loop com autonomia como padrão (Roadmap V15.3 / Spec G5).

Filosofia: o agente investiga por conta própria antes de perguntar; o pesquisador só é
interrompido quando o contexto está genuinamente ausente (modo `assisted`). Nos modos
`semi`/`auto`, a skill nunca bloqueia — documenta a suposição adotada e retorna.

Quando bloqueante (modo `assisted`), a skill chama diretamente o callback ``ask_researcher`` do
``AgentContext`` da tarefa, ligado ao orquestrador (deduplicação, registro e prompt ao
pesquisador). Não há canal de comunicação separado: o agente roda no processo do orquestrador.
"""

from __future__ import annotations

from typing import Any, Optional

from src.agent_runtime.context import get_agent_context_optional
from src.config import SESSION_DEFAULT_MODE
from src.skills.base import BaseSkill, SkillResult
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
        # O modo vem do AgentContext (por tarefa); fora dele, do padrão da sessão.
        ctx = get_agent_context_optional()
        mode = (ctx.mode if ctx is not None and ctx.mode else None) or SESSION_DEFAULT_MODE

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
            # A pergunta nunca chega a um humano nestes modos; registrá-la permite avaliar depois se
            # a consulta era relevante e se o agente decidiria melhor com ajuda.
            from src.llm.metering import bound_execution_id
            from src.telemetry import get_telemetry

            get_telemetry().record_agent_event(
                execution_id=(ctx.execution_id if ctx is not None and ctx.execution_id else "") or bound_execution_id()
                or "unknown",
                session_id=ctx.session_id if ctx is not None else "unknown",
                agent_id=ctx.agent_id if ctx is not None else "unknown",
                event_type="ask_researcher",
                task_name=(ctx.task_name or None) if ctx is not None else None,
                payload={
                    "mode": mode,
                    "blocked": False,
                    "question": question[:600],
                    "context": context[:400],
                    "why_cant_proceed": why_cant_proceed[:400],
                    "options": [str(o)[:120] for o in (options or [])][:6],
                },
            )
            return SkillResult(success=True, output=assumption, metadata={"mode": mode, "blocked": False})

        # Modo assisted: chamada direta e bloqueante ao orquestrador (Roadmap V16/ADR 014).
        if ctx is None or ctx.ask_researcher is None:
            msg = "ask_researcher chamado fora de uma execução de agente (sem AgentContext)."
            logger.warning(msg)
            return SkillResult(success=False, output="", error=msg)

        answer = await ctx.ask_researcher(question, context, why_cant_proceed, options or [])
        return SkillResult(success=True, output=answer, metadata={"mode": mode, "blocked": True})
