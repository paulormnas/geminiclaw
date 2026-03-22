from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from src.logger import get_logger

logger = get_logger(__name__)

@dataclass
class MemoryEntry:
    """Uma entrada na memória do agente."""
    key: str
    value: str
    source: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tags: List[str] = field(default_factory=list)

class ShortTermMemory:
    """Implementa memória de curto prazo (RAM) isolada por sessão."""
    
    # Armazenamento em nível de classe para persistir enquanto o processo rodar
    # Dict[session_id, List[MemoryEntry]]
    _storage: Dict[str, List[MemoryEntry]] = {}

    def write(self, session_id: str, key: str, value: str, source: str, tags: List[str] = []) -> MemoryEntry:
        """Escreve uma nova entrada na memória da sessão."""
        if session_id not in self._storage:
            self._storage[session_id] = []
        
        entry = MemoryEntry(
            key=key,
            value=value,
            source=source,
            tags=tags
        )
        self._storage[session_id].append(entry)
        logger.debug(f"Memória escrita: {key} na sessão {session_id}")
        return entry

    def read(self, session_id: str, key: str) -> Optional[MemoryEntry]:
        """Lê a entrada mais recente com a chave especificada na sessão."""
        session_entries = self._storage.get(session_id, [])
        # Percorrer de trás para frente para pegar o mais recente
        for entry in reversed(session_entries):
            if entry.key == key:
                return entry
        return None

    def search(self, session_id: str, tags: List[str]) -> List[MemoryEntry]:
        """Busca todas as entradas que contenham TODAS as tags fornecidas."""
        session_entries = self._storage.get(session_id, [])
        results = []
        target_tags = set(tags)
        
        for entry in session_entries:
            if target_tags.issubset(set(entry.tags)):
                results.append(entry)
        return results

    def list_all(self, session_id: str) -> List[MemoryEntry]:
        """Lista todas as entradas da sessão ordenadas por criação."""
        return self._storage.get(session_id, [])

    def clear(self, session_id: str) -> None:
        """Limpa toda a memória da sessão especificada."""
        if session_id in self._storage:
            del self._storage[session_id]
            logger.info(f"Memória da sessão {session_id} limpa.")
