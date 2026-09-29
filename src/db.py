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

from psycopg.errors import UndefinedFile
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.logger import get_logger

logger = get_logger(__name__)

_pool: ConnectionPool | None = None


def _configure_age_session(conn) -> None:
    """Prepara uma conexão recém-aberta do pool para uso com Apache AGE (Roadmap V17).

    Carrega a extensão e ajusta o ``search_path`` para que ``cypher()`` e os
    demais objetos de ``ag_catalog`` fiquem disponíveis sem qualificação em
    toda conexão do pool — inclusive para código que não usa o grafo, o custo
    é desprezível (``LOAD`` é idempotente por conexão).

    Se a extensão ``age`` ainda não estiver instalada no banco (ambientes que
    não rodaram a migração ``v17_001`` — ex.: antes da aprovação de infra
    desta mudança), a falha é registrada e ignorada: o restante do projeto
    continua funcionando normalmente sem o grafo de conhecimento.

    Apenas ``psycopg.errors.UndefinedFile`` (SQLSTATE ``58P01`` — "could not
    access file", o erro que o PostgreSQL emite quando ``LOAD 'age'`` não
    encontra a biblioteca compartilhada da extensão) é tratado como "extensão
    ainda não instalada". Qualquer outra falha (permissão, conectividade,
    erro de sintaxe, etc.) é propagada — mascará-la aqui esconderia problemas
    reais em toda conexão do pool (AGENTS.md §1.6, fail-fast).

    Args:
        conn: Conexão recém-aberta pelo ``ConnectionPool``.

    Raises:
        psycopg.Error: Qualquer falha de configuração que não seja a
            extensão ``age`` ausente é propagada sem tratamento.
    """
    try:
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
    except UndefinedFile as exc:  # extensão ainda não instalada — grafo é opcional até a migração
        conn.rollback()
        logger.debug(
            "Extensão Apache AGE indisponível nesta conexão (grafo de conhecimento desativado).",
            extra={"extra": {"error": str(exc)}},
        )


def get_pool() -> ConnectionPool:
    """Retorna o pool de conexões singleton, inicializando-o na primeira chamada.

    O pool é configurado com ``row_factory=dict_row`` para que todas as queries
    retornem dicionários em vez de tuplas, e com um callback ``configure`` que
    prepara cada conexão para uso com Apache AGE (``LOAD 'age'`` e
    ``search_path``) — ver ``src.knowledge.graph_store.AgeGraphStore``.

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
            configure=_configure_age_session,
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
