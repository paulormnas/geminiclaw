from typing import List, Optional
from src.skills.base import BaseSkill, SkillResult
from src.skills.memory.short_term import ShortTermMemory
from src.logger import get_logger

logger = get_logger(__name__)

class MemorySkill(BaseSkill):
    """Skill para gerenciamento de memória de curto prazo por sessão."""
    
    name = "memory_skill"
    description = (
        "Use 'remember' para registrar descobertas durante a tarefa. "
        "Use 'recall' ou 'recall_by_tags' para recuperar o que foi registrado anteriormente na mesma sessão."
    )

    def __init__(self):
        self.memory = ShortTermMemory()

    async def run(self, action: str, **kwargs) -> SkillResult:
        """Executa ações de memória.
        
        Args:
            action: 'remember', 'recall', ou 'recall_by_tags'
            **kwargs: Argumentos específicos da ação.
        """
        session_id = kwargs.get("session_id")
        if not session_id:
            return SkillResult(success=False, output="", error="session_id é obrigatório")

        try:
            if action == "remember":
                key = kwargs.get("key")
                value = kwargs.get("value")
                source = kwargs.get("source", "agent")
                tags = kwargs.get("tags", [])
                
                if not key or not value:
                    return SkillResult(success=False, output="", error="key e value são obrigatórios")
                
                entry = self.memory.write(session_id, key, value, source, tags)
                return SkillResult(success=True, output=f"Informação registrada com chave '{key}'")

            elif action == "recall":
                key = kwargs.get("key")
                if not key:
                    return SkillResult(success=False, output="", error="key é obrigatória")
                
                entry = self.memory.read(session_id, key)
                if not entry:
                    return SkillResult(success=True, output=f"Nenhuma memória encontrada para chave '{key}'", metadata={"found": False})
                
                return SkillResult(success=True, output=entry.value, metadata={"found": True, "entry": entry.__dict__})

            elif action == "recall_by_tags":
                tags = kwargs.get("tags", [])
                if not tags:
                    return SkillResult(success=False, output="", error="tags são obrigatórias")
                
                entries = self.memory.search(session_id, tags)
                output = f"Encontradas {len(entries)} entradas: " + ", ".join([e.key for e in entries])
                return SkillResult(success=True, output=output, metadata={"entries": [e.__dict__ for e in entries]})

            else:
                return SkillResult(success=False, output="", error=f"Ação desconhecida: {action}")

        except Exception as e:
            logger.error(f"Erro na MemorySkill: {str(e)}")
            return SkillResult(success=False, output="", error=str(e))
