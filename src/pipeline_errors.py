"""Erros explícitos do pipeline de planejamento e execução (V16 / ``v16-pipeline-robustness``)."""


class PlanningStalled(RuntimeError):
    """O planejamento repetiu a mesma reprovação determinística e foi encerrado."""

    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class AgentRunLimitReached(RuntimeError):
    """Limite de execuções de agente por sessão atingido.

    Attributes:
        kind: Contador que estourou (``planning`` ou ``execution``).
        count: Execuções já feitas.
        limit: Limite efetivo.
    """

    def __init__(self, kind: str, count: int, limit: int, session_id: str = "") -> None:
        self.kind = kind
        self.count = count
        self.limit = limit
        super().__init__(
            f"Limite de execuções de agente por sessão atingido (session={session_id}, "
            f"contador={kind}, execuções={count}, limite={limit}). Execução interrompida pelo circuit breaker."
        )
