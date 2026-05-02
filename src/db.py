"""Módulo centralizado de conexão ao PostgreSQL.

Fornece um connection pool singleton (psycopg v3) compartilhado por todos
os módulos do projeto. As conexões são obtidas via context manager e
automaticamente devolvidas ao pool ao sair do bloco ``with``.

Uso::

    from src.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_sessions WHERE id = %s", (session_id,)
        ).fetchone()
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from src.logger import get_logger

logger = get_logger(__name__)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Retorna o pool de conexões singleton, inicializando-o na primeira chamada.

    O pool é configurado com ``row_factory=dict_row`` para que todas as queries
    retornem dicionários em vez de tuplas.

    Returns:
        ConnectionPool configurado e pronto para uso.
    """
    global _pool
    if _pool is None:
        from src.config import DATABASE_URL  # import tardio para evitar ciclos
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=2,
            max_size=10,
            open=True,
            kwargs={"row_factory": dict_row},
        )
        logger.info(
            "Pool PostgreSQL inicializado",
            extra={"extra": {"min_size": 2, "max_size": 10}},
        )
    return _pool


def get_connection():
    """Context manager para obter uma conexão do pool.

    A conexão é automaticamente devolvida ao pool ao sair do bloco ``with``.
    Erros levantados dentro do bloco causam rollback automático.

    Uso::

        with get_connection() as conn:
            conn.execute("SELECT 1")

    Returns:
        Context manager que produz uma ``psycopg.Connection`` com ``dict_row``.
    """
    return get_pool().connection()


def close_pool() -> None:
    """Encerra o pool de conexões e libera todos os recursos.

    Deve ser chamado no shutdown da aplicação. Após isso, ``get_pool()``
    criará um novo pool na próxima chamada.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("Pool PostgreSQL encerrado")
