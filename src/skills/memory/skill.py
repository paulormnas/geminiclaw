import os
from typing import List, Optional, Any
from src.skills.base import BaseSkill, SkillResult
from src.skills.memory.short_term import ShortTermMemory
from src.skills.memory.long_term import LongTermMemory, LongTermMemoryEntry
from src.logger import get_logger

logger = get_logger(__name__)

class MemorySkill(BaseSkill):
    """Skill para gerenciamento de memória de curto e longo prazo."""
    
    name = "memory"
    description = (
        "Gerencia memórias do agente. Ações:\n"
        "- 'remember': registra na memória de curto prazo (sessão atual).\n"
        "- 'memorize': registra na memória de longo prazo (persistente entre sessões).\n"
        "- 'recall': recupera da memória de curto prazo por chave.\n"
        "- 'recall_by_tags': recupera da memória de curto prazo por lista de tags.\n"
        "- 'retrieve': recupera por chave (busca curto prazo primeiro, depois longo prazo).\n"
        "- 'remember_forever': promove uma memória de curto prazo para longo prazo."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["remember", "memorize", "recall", "recall_by_tags", "retrieve", "remember_forever"],
                "description": "Ação de memória a ser executada."
            },
            "key": {
                "type": "string",
                "description": "Chave identificadora da memória."
            },
            "value": {
                "type": "string",
                "description": "Conteúdo da memória a ser gravado (obrigatório para remember/memorize)."
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de tags para categorização ou busca."
            },
            "importance": {
                "type": "number",
                "description": "Nível de importância (0.0 a 1.0) para memórias de longo prazo.",
                "default": 0.5
            },
            "session_id": {
                "type": "string",
                "description": "ID da sessão atual (obrigatório para ações de curto prazo)."
            }
        },
        "required": ["action", "key", "session_id"]
    }

    def __init__(self, db_path: Optional[str] = None):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()

    async def run(self, action: Optional[str] = None, **kwargs) -> SkillResult:
        """Executa ações de memória.
        
        Args:
            action: 'remember', 'memorize', 'recall', 'recall_by_tags', 'retrieve', 'remember_forever'
            **kwargs: Argumentos específicos da ação (key, value, source, tags, importance, etc.).
        """
        if not action:
            return SkillResult(success=False, output="", error="O parâmetro 'action' é obrigatório.")
        # Removemos session_id de kwargs para evitar passar duas vezes para os handlers
        session_id = kwargs.pop("session_id", None)
        
        if not session_id and action in ["remember", "recall", "remember_forever"]:
            return SkillResult(success=False, output="", error="session_id é obrigatório para esta ação")

        try:
            if action == "remember":
                return self._handle_remember(session_id, **kwargs)
            elif action == "memorize":
                return self._handle_memorize(**kwargs)
            elif action == "recall":
                return self._handle_recall(session_id, **kwargs)
            elif action == "retrieve":
                return self._handle_retrieve(session_id, **kwargs)
            elif action == "recall_by_tags":
                return self._handle_recall_by_tags(session_id, **kwargs)
            elif action == "remember_forever":
                return self._handle_remember_forever(session_id, **kwargs)
            else:
                return SkillResult(success=False, output="", error=f"Ação desconhecida: {action}")

        except Exception as e:
            logger.error(f"Erro na MemorySkill: {str(e)}")
            return SkillResult(success=False, output="", error=str(e))

    def _handle_remember(self, session_id: str, **kwargs) -> SkillResult:
        key = kwargs.get("key")
        value = kwargs.get("value")
        source = kwargs.get("source", "agent")
        tags = kwargs.get("tags", [])

        if not key or not value:
            return SkillResult(success=False, output="", error="key e value são obrigatórios")

        self.short_term.write(session_id, key, value, source, tags)
        logger.info(
            "Memória gravada em curto prazo",
            extra={"event": "memory_written", "store": "short_term", "key": key, "session_id": session_id},
        )
        return SkillResult(success=True, output=f"Informação registrada em curto prazo: '{key}'")

    def _handle_memorize(self, **kwargs) -> SkillResult:
        key = kwargs.get("key")
        value = kwargs.get("value")
        source = kwargs.get("source", "agent")
        importance = float(kwargs.get("importance", 0.5))
        tags = kwargs.get("tags", [])

        if not key or not value:
            return SkillResult(success=False, output="", error="key e value são obrigatórios")

        self.long_term.write(key, value, source, importance, tags)
        logger.info(
            "Memória gravada em longo prazo",
            extra={"event": "memory_written", "store": "long_term", "key": key},
        )
        return SkillResult(success=True, output=f"Informação registrada em longo prazo: '{key}'")

    def _handle_recall(self, session_id: str, **kwargs) -> SkillResult:
        key = kwargs.get("key")
        if not key:
            return SkillResult(success=False, output="", error="key é obrigatória")
        
        entry = self.short_term.read(session_id, key)
        if not entry:
            return SkillResult(success=True, output=f"Nenhuma memória de curto prazo encontrada para '{key}'", metadata={"found": False})
        
        return SkillResult(success=True, output=entry.value, metadata={"found": True, "entry": entry.__dict__})

    def _handle_retrieve(self, session_id: Optional[str], **kwargs) -> SkillResult:
        key = kwargs.get("key")
        if not key:
            return SkillResult(success=False, output="", error="key é obrigatória")
        
        # Tenta curto prazo primeiro
        if session_id:
            entry = self.short_term.read(session_id, key)
            if entry:
                return SkillResult(success=True, output=entry.value, metadata={"found": True, "source": "short_term", "entry": entry.__dict__})
        
        # Tenta longo prazo
        lt_entry = self.long_term.read(key)
        if lt_entry:
            return SkillResult(success=True, output=lt_entry.value, metadata={"found": True, "source": "long_term", "entry": lt_entry.__dict__})
        
        return SkillResult(success=True, output=f"Nenhuma memória encontrada para '{key}'", metadata={"found": False})

    def _handle_recall_by_tags(self, session_id: str, **kwargs) -> SkillResult:
        tags = kwargs.get("tags", [])
        if not tags:
            return SkillResult(success=False, output="", error="tags são obrigatórias para busca por tags")
        
        entries = self.short_term.search(session_id, tags)
        if not entries:
            return SkillResult(success=True, output=f"Nenhuma memória encontrada com as tags {tags}", metadata={"found": False})
        
        output = f"Memórias encontradas ({len(entries)}):\n"
        for entry in entries:
            output += f"- {entry.key}: {entry.value}\n"
            
        return SkillResult(success=True, output=output, metadata={"found": True, "count": len(entries)})

    def _handle_remember_forever(self, session_id: str, **kwargs) -> SkillResult:
        key = kwargs.get("key")
        importance = float(kwargs.get("importance", 0.5))

        if not key:
            return SkillResult(success=False, output="", error="key é obrigatória")

        st_entry = self.short_term.read(session_id, key)
        if not st_entry:
            return SkillResult(success=False, output="", error=f"Memória de curto prazo '{key}' não encontrada na sessão")

        self.long_term.write(st_entry.key, st_entry.value, st_entry.source, importance, st_entry.tags)
        logger.info(
            "Memória promovida de curto para longo prazo",
            extra={"event": "memory_promoted", "key": key, "importance": importance, "session_id": session_id},
        )
        return SkillResult(success=True, output=f"Memória '{key}' promovida para longo prazo.")
