import sqlite_utils
import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from src.config import SQLITE_DB_PATH

class DeepSearchCache:
    """Cache persistente para consultas ao índice vetorial."""

    def __init__(self, db_path: str = SQLITE_DB_PATH):
        self.db = sqlite_utils.Database(db_path)
        self._ensure_table()

    def _ensure_table(self):
        """Cria a tabela de cache se não existir."""
        if "deep_search_cache" not in self.db.table_names():
            self.db["deep_search_cache"].create(
                {
                    "query_hash": str,
                    "query": str,
                    "results": str,
                    "expires_at": str,
                    "created_at": str
                },
                pk="query_hash"
            )
            self.db["deep_search_cache"].create_index(["expires_at"])

    def get(self, query: str, filters: Optional[Dict[str, Any]] = None) -> Optional[List[Dict[str, Any]]]:
        """Recupera resultados do cache se existirem e não estiverem expirados."""
        query_hash = self._generate_hash(query, filters)
        
        try:
            row = self.db["deep_search_cache"].get(query_hash)
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at > datetime.utcnow():
                return json.loads(row["results"])
            else:
                self.db["deep_search_cache"].delete(query_hash)
        except sqlite_utils.db.NotFoundError:
            pass
        return None

    def set(self, query: str, results: List[Dict[str, Any]], ttl_seconds: int = 86400, filters: Optional[Dict[str, Any]] = None):
        """Armazena resultados no cache."""
        query_hash = self._generate_hash(query, filters)
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        
        self.db["deep_search_cache"].upsert(
            {
                "query_hash": query_hash,
                "query": query,
                "results": json.dumps(results),
                "expires_at": expires_at.isoformat(),
                "created_at": now.isoformat()
            },
            pk="query_hash"
        )

    def _generate_hash(self, query: str, filters: Optional[Dict[str, Any]] = None) -> str:
        """Gera um hash único para a query e filtros."""
        data = {"query": query.strip().lower(), "filters": filters or {}}
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def clear_expired(self):
        """Remove entradas expiradas."""
        now = datetime.utcnow().isoformat()
        self.db.execute("DELETE FROM deep_search_cache WHERE expires_at < ?", (now,))
