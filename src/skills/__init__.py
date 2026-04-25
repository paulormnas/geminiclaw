from typing import Dict, List, Optional, Any
from .base import BaseSkill
from .search_quick.skill import QuickSearchSkill
try:
    from .search_deep.skill import DeepSearchSkill
    _HAS_DEEP_SEARCH = True
except (ImportError, ModuleNotFoundError):
    _HAS_DEEP_SEARCH = False

from .code.skill import CodeSkill
from .memory.skill import MemorySkill
from .web_reader.skill import WebReaderSkill

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
        tools = []
        for skill in self._skills.values():
            # Criamos uma closure para capturar a instância correta da skill
            def create_tool(s: BaseSkill):
                # Usamos a assinatura real da skill para o ADK
                async def skill_tool(**kwargs) -> str:
                    result = await s.run_with_logging(**kwargs)
                    if result.success:
                        return f"Resultado de {s.name}: {result.output}"
                    return f"Erro em {s.name}: {result.error}"

                # Injetamos o nome e a descrição da skill na função
                skill_tool.__name__ = s.name
                skill_tool.__doc__ = s.description
                return skill_tool

            tools.append(create_tool(skill))

        return tools


# Instância global para facilitar o acesso
registry = SkillRegistry()

# Registrar skills padrão se necessário
def _safe_register(skill_class):
    try:
        registry.register(skill_class())
    except Exception as e:
        from src.logger import get_logger
        get_logger(__name__).error(f"Falha ao registrar skill {skill_class.__name__}: {e}")

_safe_register(QuickSearchSkill)
if _HAS_DEEP_SEARCH:
    _safe_register(DeepSearchSkill)
_safe_register(CodeSkill)
_safe_register(MemorySkill)
_safe_register(WebReaderSkill)

__all__ = ["BaseSkill", "SkillRegistry", "registry", "QuickSearchSkill", "DeepSearchSkill", "CodeSkill", "MemorySkill", "WebReaderSkill"]
