"""Cache de respostas do LLM (Gemini) baseado em SQLite."""

import sqlite3
import hashlib
import time
import os
from typing import Optional, Dict, Any

from src.logger import get_logger

logger = get_logger(__name__)

class LLMResponseCache:
    """Implementa um cache SQLite para respostas do LLM.
    
    Usa um hash SHA-256 (prompt + model) como chave.
    Suporta TTL e limite máximo de entradas (FIFO eviction).
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Inicializa o cache.
        
        Args:
            db_path: Caminho para o DB. Se None, lê de LLM_CACHE_DB ou usa default.
        """
        self.db_path = db_path or os.environ.get("LLM_CACHE_DB", "/data/llm_cache.db")
        # Em testes, podemos passar ':memory:'
        self.enabled = str(os.environ.get("LLM_CACHE_ENABLED", "true")).lower() == "true"
        self.ttl_seconds = int(os.environ.get("LLM_CACHE_TTL_SECONDS", "3600"))
        self.max_entries = int(os.environ.get("LLM_CACHE_MAX_ENTRIES", "1000"))
        
        if self.enabled:
            self._init_db()
            
    def _get_connection(self) -> sqlite3.Connection:
        """Cria e retorna uma conexão SQLite."""
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Cria as tabelas necessárias se não existirem."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS llm_cache (
                        hash_key TEXT PRIMARY KEY,
                        prompt TEXT,
                        model TEXT,
                        response TEXT,
                        timestamp REAL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS llm_cache_stats (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        hits INTEGER DEFAULT 0,
                        misses INTEGER DEFAULT 0
                    )
                """)
                cursor.execute("""
                    INSERT OR IGNORE INTO llm_cache_stats (id, hits, misses)
                    VALUES (1, 0, 0)
                """)
                conn.commit()
                logger.info("LLMResponseCache inicializado", extra={"db_path": self.db_path, "ttl": self.ttl_seconds})
        except Exception as e:
            logger.error("Erro ao inicializar db do LLM cache", extra={"error": str(e)})
            self.enabled = False

    def _generate_hash(self, prompt: str, model: str) -> str:
        """Gera o hash SHA-256 normalizado para a chave."""
        raw = f"{model}:{prompt.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, prompt: str, model: str) -> Optional[str]:
        """Obtém uma resposta do cache se existir e estiver válida.
        
        Args:
            prompt: Prompt enviado ao LLM.
            model: Modelo utilizado.
            
        Returns:
            String com a resposta cacheada ou None se não existir/expirado.
        """
        if not self.enabled:
            return None
            
        hash_key = self._generate_hash(prompt, model)
        current_time = time.time()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT response, timestamp FROM llm_cache WHERE hash_key = ?", (hash_key,))
                row = cursor.fetchone()
                
                if row:
                    age = current_time - row["timestamp"]
                    if age <= self.ttl_seconds:
                        cursor.execute("UPDATE llm_cache_stats SET hits = hits + 1 WHERE id = 1")
                        conn.commit()
                        logger.info("LLM Cache HIT", extra={"hash": hash_key[:8], "age_seconds": round(age, 2)})
                        return row["response"]
                    else:
                        # Expirou, apaga
                        cursor.execute("DELETE FROM llm_cache WHERE hash_key = ?", (hash_key,))
                        # Continua para o miss...
                        
                # Miss
                cursor.execute("UPDATE llm_cache_stats SET misses = misses + 1 WHERE id = 1")
                conn.commit()
                logger.info("LLM Cache MISS", extra={"hash": hash_key[:8]})
                return None
        except Exception as e:
            logger.error("Erro ao ler LLM cache", extra={"error": str(e)})
            return None

    def set(self, prompt: str, model: str, response: str) -> None:
        """Armazena ou atualiza uma resposta no cache e aplica eviction se necessário.
        
        Args:
            prompt: Prompt enviado ao LLM.
            model: Modelo utilizado.
            response: Resposta do LLM.
        """
        if not self.enabled:
            return
            
        hash_key = self._generate_hash(prompt, model)
        current_time = time.time()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Inserir ou atualizar
                cursor.execute("""
                    INSERT INTO llm_cache (hash_key, prompt, model, response, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(hash_key) DO UPDATE SET
                        response = excluded.response,
                        timestamp = excluded.timestamp
                """, (hash_key, prompt, model, response, current_time))
                
                # Checar eviction
                cursor.execute("SELECT COUNT(*) FROM llm_cache")
                count = cursor.fetchone()[0]
                
                if count > self.max_entries:
                    # Deletar os mais antigos além do limite
                    to_delete = count - self.max_entries
                    cursor.execute("""
                        DELETE FROM llm_cache 
                        WHERE hash_key IN (
                            SELECT hash_key FROM llm_cache 
                            ORDER BY timestamp ASC 
                            LIMIT ?
                        )
                    """, (to_delete,))
                    logger.debug("LLM Cache Eviction rodou", extra={"removed": to_delete})
                
                conn.commit()
                logger.info("LLM Cache SET", extra={"hash": hash_key[:8]})
        except Exception as e:
            logger.error("Erro ao gravar no LLM cache", extra={"error": str(e)})

    def stats(self) -> Dict[str, Any]:
        """Retorna as estatísticas de hits/misses do cache."""
        if not self.enabled:
            return {"enabled": False}
            
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT hits, misses FROM llm_cache_stats WHERE id = 1")
                row = cursor.fetchone()
                
                if row:
                    hits = row["hits"]
                    misses = row["misses"]
                    total = hits + misses
                    rate = (hits / total) if total > 0 else 0.0
                    return {
                        "enabled": True,
                        "hits": hits,
                        "misses": misses,
                        "hit_rate": round(rate, 4),
                        "total_requests": total
                    }
        except Exception:
            pass
        return {"enabled": False}
