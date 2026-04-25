from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from src.logger import get_logger

_base_logger = get_logger(__name__)


@dataclass
class SkillResult:
    """Resultado da execução de uma skill."""
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    """Classe base para todas as skills do GeminiClaw."""
    name: str
    description: str
    parameters_schema: Dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    async def run(self, **kwargs) -> SkillResult:
        """Executa a lógica da skill.

        Args:
            **kwargs: Argumentos específicos da skill.

        Returns:
            SkillResult: Objeto contendo o resultado da execução.
        """
        pass

    async def run_with_logging(self, **kwargs) -> SkillResult:
        """Envolve run() emitindo os log events estruturados.

        Emite:
            - ``skill_invoked`` antes da execução.
            - ``skill_completed`` se success=True.
            - ``skill_failed`` se success=False ou se uma exceção ocorrer.

        Args:
            **kwargs: Argumentos repassados para run().

        Returns:
            SkillResult: Resultado da execução da skill.
        """
        _base_logger.info(
            "Skill invocada",
            extra={"event": "skill_invoked", "skill": self.name, "kwargs_keys": list(kwargs.keys())},
        )

        try:
            result = await self.run(**kwargs)
        except Exception as exc:
            _base_logger.error(
                "Skill falhou com exceção",
                extra={"event": "skill_failed", "skill": self.name, "error": str(exc)},
            )
            raise

        if result.success:
            _base_logger.info(
                "Skill concluída com sucesso",
                extra={"event": "skill_completed", "skill": self.name},
            )
        else:
            _base_logger.warning(
                "Skill concluída com erro",
                extra={"event": "skill_failed", "skill": self.name, "error": result.error},
            )

        return result

