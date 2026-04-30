"""Histórico de execuções do orquestrador persistido no PostgreSQL.

Substitui a implementação anterior baseada em SQLite (sqlite3).
As execuções são armazenadas na tabela ``execution_history`` criada
pelo ``scripts/init_db.sql``.
"""

import uuid
import json
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from src.logger import get_logger
from src.db import get_connection

logger = get_logger(__name__)


@dataclass
class ExecutionRecord:
    """Registro de uma execução do orquestrador."""

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


def _row_to_record(row: dict) -> ExecutionRecord:
    """Converte uma row do PostgreSQL em ExecutionRecord.

    Args:
        row: Dicionário retornado pela query (dict_row).

    Returns:
        Objeto ExecutionRecord populado.
    """
    def _to_str(v) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    return ExecutionRecord(
        id=row["id"],
        prompt=row["prompt"],
        plan_json=row["plan_json"],
        status=row["status"],
        results_json=row["results_json"],
        artifacts_json=row["artifacts_json"],
        started_at=_to_str(row["started_at"]) or "",
        finished_at=_to_str(row["finished_at"]),
        duration_seconds=row["duration_seconds"],
        total_subtasks=row["total_subtasks"],
        succeeded=row["succeeded"],
        failed=row["failed"],
    )


class ExecutionHistory:
    """Gerencia a persistência de histórico de execuções do orquestrador."""

    def record(
        self,
        prompt: str,
        status: str,
        started_at: str,
        finished_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        plan_json: Optional[str] = None,
        results_json: Optional[str] = None,
        artifacts_json: Optional[str] = None,
        total_subtasks: int = 0,
        succeeded: int = 0,
        failed: int = 0,
    ) -> str:
        """Registra uma execução no histórico.

        Args:
            prompt: Prompt original enviado ao orquestrador.
            status: Status final da execução.
            started_at: Timestamp de início (ISO 8601).
            finished_at: Timestamp de término (opcional).
            duration_seconds: Duração total em segundos (opcional).
            plan_json: Plano serializado como JSON (opcional).
            results_json: Resultados serializados como JSON (opcional).
            artifacts_json: Artefatos gerados serializados como JSON (opcional).
            total_subtasks: Total de subtarefas.
            succeeded: Subtarefas bem-sucedidas.
            failed: Subtarefas que falharam.

        Returns:
            ID hexadecimal da execução registrada, ou string vazia em caso de erro.
        """
        exec_id = uuid.uuid4().hex

        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO execution_history (
                        id, prompt, plan_json, status, results_json, artifacts_json,
                        started_at, finished_at, duration_seconds, total_subtasks,
                        succeeded, failed
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        exec_id,
                        prompt,
                        plan_json,
                        status,
                        results_json,
                        artifacts_json,
                        started_at,
                        finished_at,
                        duration_seconds,
                        total_subtasks,
                        succeeded,
                        failed,
                    ),
                )
            logger.info(
                "Histórico de execução registrado",
                extra={"extra": {"exec_id": exec_id, "status": status}},
            )
            return exec_id
        except Exception as e:
            logger.error("Erro ao gravar histórico", extra={"error": str(e)})
            return ""

    def get(self, execution_id: str) -> Optional[ExecutionRecord]:
        """Recupera uma execução pelo ID.

        Args:
            execution_id: ID da execução.

        Returns:
            ExecutionRecord ou None se não encontrado.
        """
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM execution_history WHERE id = %s",
                    (execution_id,),
                ).fetchone()

            if row:
                return _row_to_record(row)
        except Exception as e:
            logger.error("Erro ao obter histórico", extra={"error": str(e)})
        return None

    def list_recent(self, limit: int = 10) -> List[ExecutionRecord]:
        """Lista as execuções mais recentes.

        Args:
            limit: Quantidade máxima de execuções a retornar.

        Returns:
            Lista de ExecutionRecord ordenados por início decrescente.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM execution_history ORDER BY started_at DESC LIMIT %s",
                    (limit,),
                ).fetchall()
            return [_row_to_record(row) for row in rows]
        except Exception as e:
            logger.error("Erro ao listar histórico", extra={"error": str(e)})
            return []

    def search(self, query: str) -> List[ExecutionRecord]:
        """Busca execuções por conteúdo do prompt.

        Args:
            query: Termo de busca (case-insensitive).

        Returns:
            Lista de ExecutionRecord com o termo no prompt.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM execution_history
                    WHERE prompt ILIKE %s
                    ORDER BY started_at DESC
                    """,
                    (f"%{query}%",),
                ).fetchall()
            return [_row_to_record(row) for row in rows]
        except Exception as e:
            logger.error("Erro ao pesquisar histórico", extra={"error": str(e)})
            return []
