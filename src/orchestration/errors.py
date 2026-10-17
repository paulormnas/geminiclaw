"""Erros explícitos do pipeline de planejamento e execução (V16 / ``v16-pipeline-robustness``)."""


class PlanningStalled(RuntimeError):
    """O planejamento repetiu a mesma reprovação determinística e foi encerrado."""

    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []

