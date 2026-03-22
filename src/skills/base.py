from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

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

    @abstractmethod
    async def run(self, **kwargs) -> SkillResult:
        """Executa a lógica da skill.

        Args:
            **kwargs: Argumentos específicos da skill.

        Returns:
            SkillResult: Objeto contendo o resultado da execução.
        """
        pass
