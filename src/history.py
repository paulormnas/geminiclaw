import sqlite3
import os
import uuid
import json
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from src.logger import get_logger
from src.config import SQLITE_DB_PATH

logger = get_logger(__name__)

@dataclass
class ExecutionRecord:
    id: str
    prompt: str
    plan_json: Optional[str]
    status: str
    results_json: Optional[str]
    artifacts_json: Optional[str]
    started_at: str
    finished_at: Optional[str]
    duration_seconds: Optional[float]
    total_subtasks: Optional[int]
    succeeded: Optional[int]
    failed: Optional[int]

class ExecutionHistory:
    """Gerencia a persistência de histórico de execuções do orquestrador."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SQLITE_DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS execution_history (
                        id TEXT PRIMARY KEY,
                        prompt TEXT NOT NULL,
                        plan_json TEXT,
                        status TEXT NOT NULL,
                        results_json TEXT,
                        artifacts_json TEXT,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        duration_seconds REAL,
                        total_subtasks INTEGER,
                        succeeded INTEGER,
                        failed INTEGER
                    );
                """)
                conn.commit()
        except Exception as e:
            logger.error("Erro ao inicializar db de histórico", extra={"error": str(e)})

    def record(self, prompt: str, status: str, started_at: str, 
               finished_at: Optional[str] = None, duration_seconds: Optional[float] = None,
               plan_json: Optional[str] = None, results_json: Optional[str] = None,
               artifacts_json: Optional[str] = None, total_subtasks: int = 0,
               succeeded: int = 0, failed: int = 0) -> str:
        
        exec_id = uuid.uuid4().hex
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO execution_history (
                        id, prompt, plan_json, status, results_json, artifacts_json,
                        started_at, finished_at, duration_seconds, total_subtasks,
                        succeeded, failed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    exec_id, prompt, plan_json, status, results_json, artifacts_json,
                    started_at, finished_at, duration_seconds, total_subtasks,
                    succeeded, failed
                ))
                conn.commit()
                return exec_id
        except Exception as e:
            logger.error("Erro ao gravar histórico", extra={"error": str(e)})
            return ""

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM execution_history WHERE id = ?", (execution_id,))
                row = cursor.fetchone()
                if row:
                    return ExecutionRecord(**dict(row))
        except Exception as e:
            logger.error("Erro ao obter histórico", extra={"error": str(e)})
        return None

    def list_recent(self, limit: int = 10) -> List[ExecutionRecord]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM execution_history ORDER BY started_at DESC LIMIT ?", (limit,))
                rows = cursor.fetchall()
                return [ExecutionRecord(**dict(row)) for row in rows]
        except Exception as e:
            logger.error("Erro ao listar histórico", extra={"error": str(e)})
            return []

    def search(self, query: str) -> List[ExecutionRecord]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Busca simples usando LIKE no prompt
                search_term = f"%{query}%"
                cursor.execute("SELECT * FROM execution_history WHERE prompt LIKE ? ORDER BY started_at DESC", (search_term,))
                rows = cursor.fetchall()
                return [ExecutionRecord(**dict(row)) for row in rows]
        except Exception as e:
            logger.error("Erro ao pesquisar histórico", extra={"error": str(e)})
            return []
