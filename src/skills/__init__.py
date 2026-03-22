from typing import Dict, List, Optional, Any
from .base import BaseSkill
from .search_quick.skill import QuickSearchSkill
from .search_deep.skill import DeepSearchSkill

class SkillRegistry:
    """Registro centralizado de skills disponíveis para os agentes."""
    
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """Registra uma nova skill no sistema.

        Args:
            skill: Instância da skill a ser registrada.

        Raises:
            ValueError: Se uma skill com o mesmo nome já estiver registrada.
        """
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' já está registrada.")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[BaseSkill]:
        """Recupera uma skill pelo nome.

        Args:
            name: Nome da skill.

        Returns:
            BaseSkill | None: A instância da skill ou None se não encontrada.
        """
        return self._skills.get(name)

    def list_available(self) -> List[Dict[str, str]]:
        """Lista todas as skills registradas.

        Returns:
            List[Dict[str, str]]: Lista de dicionários com nome e descrição de cada skill.
        """
        return [
            {"name": s.name, "description": s.description}
            for s in self._skills.values()
        ]

    def as_adk_tools(self) -> List[Any]:
        """Converte as skills registradas para o formato de ferramentas do ADK.

        Returns:
            List[Any]: Lista de ferramentas formatadas para o ADK.
        """
        # TODO: Implementar conversão real quando integrarmos com ADK
        return []

# Instância global para facilitar o acesso
registry = SkillRegistry()

# Registrar skills padrão se necessário
try:
    registry.register(QuickSearchSkill())
    registry.register(DeepSearchSkill())
except Exception:
    # Pode falhar se variáveis de ambiente não estiverem setadas, 
    # ou durante testes onde preferimos registro manual.
    pass

__all__ = ["BaseSkill", "SkillRegistry", "registry", "QuickSearchSkill", "DeepSearchSkill"]
