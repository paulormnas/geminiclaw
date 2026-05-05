from typing import Dict, List, Optional, Any, Callable
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
try:
    from .document_processor.skill import DocumentProcessorSkill
    _HAS_DOC_PROCESSOR = True
except (ImportError, ModuleNotFoundError):
    _HAS_DOC_PROCESSOR = False

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

    def as_tools(self) -> List[Callable]:
        """Converte as skills registradas para o formato de ferramentas padrão.

        Returns:
            List[Callable]: Lista de funções formatadas como ferramentas.
        """
        tools = []
        for skill in self._skills.values():
            # Criamos uma closure para capturar a instância correta da skill
            def create_tool(s: BaseSkill):
                # Usamos a assinatura real da skill
                async def skill_tool(**kwargs) -> str:
                    result = await s.run_with_logging(**kwargs)
                    if result.success:
                        return f"Resultado de {s.name}: {result.output}"
                    return f"Erro em {s.name}: {result.error}"

                # Injetamos o nome e a descrição da skill na função
                skill_tool.__name__ = s.name
                skill_tool.__doc__ = s.description
                skill_tool.parameters_schema = s.parameters_schema
                return skill_tool

            tools.append(create_tool(skill))

        return tools

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        """Converte as skills para o formato OpenAI Tool Calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.parameters_schema,
                },
            }
            for skill in self._skills.values()
        ]


# Instância global para facilitar o acesso
registry = SkillRegistry()

# Registrar skills padrão respeitando as flags de ativação
def _safe_register(skill_class, enabled: bool = True):
    if not enabled:
        return
    try:
        registry.register(skill_class())
    except Exception as e:
        from src.logger import get_logger
        get_logger(__name__).error(f"Falha ao registrar skill {skill_class.__name__}: {e}")

from src.config import (
    SKILL_DEEP_SEARCH_ENABLED,
    SKILL_WEB_READER_ENABLED,
    SKILL_CODE_ENABLED,
    SKILL_MEMORY_ENABLED,
    SKILL_DOCUMENT_PROCESSOR_ENABLED
)

_safe_register(QuickSearchSkill)
if _HAS_DEEP_SEARCH:
    _safe_register(DeepSearchSkill, enabled=SKILL_DEEP_SEARCH_ENABLED)
_safe_register(CodeSkill, enabled=SKILL_CODE_ENABLED)
_safe_register(MemorySkill, enabled=SKILL_MEMORY_ENABLED)
_safe_register(WebReaderSkill, enabled=SKILL_WEB_READER_ENABLED)
if _HAS_DOC_PROCESSOR:
    _safe_register(DocumentProcessorSkill, enabled=SKILL_DOCUMENT_PROCESSOR_ENABLED)

__all__ = ["BaseSkill", "SkillRegistry", "registry", "QuickSearchSkill", "DeepSearchSkill", "CodeSkill", "MemorySkill", "WebReaderSkill", "DocumentProcessorSkill"]
