"""Testes de integração para src/db.py.

Requerem um PostgreSQL real acessível via DATABASE_URL.
Skippados automaticamente se o banco não estiver disponível.

Para rodar:
    docker compose up postgres -d
    uv run pytest tests/integration/test_db_integration.py -v -m integration
"""

import os
import pytest


def _postgres_available() -> bool:
    """Verifica se um PostgreSQL real está disponível via DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        return False
    try:
        import psycopg
        conn = psycopg.connect(url, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _postgres_available()
skip_if_no_postgres = pytest.mark.skipif(
    not POSTGRES_AVAILABLE,
    reason="PostgreSQL não disponível. Suba o container: docker compose up postgres -d",
)


@pytest.mark.integration
@skip_if_no_postgres
class TestPoolIntegration:
    """Testes de integração do pool de conexões."""

    def setup_method(self):
        """Garante que o pool é zerado antes de cada teste."""
        import src.db as db_module
        if db_module._pool is not None:
            db_module.close_pool()

    def teardown_method(self):
        """Encerra o pool após cada teste."""
        import src.db as db_module
        if db_module._pool is not None:
            db_module.close_pool()

    def test_get_pool_cria_pool_real(self):
        """get_pool() deve criar e retornar um pool funcional."""
        from src.db import get_pool, close_pool
        pool = get_pool()
        assert pool is not None

    def test_get_connection_executa_query(self):
        """get_connection() deve permitir executar uma query simples."""
        from src.db import get_connection, close_pool
        with get_connection() as conn:
            row = conn.execute("SELECT 1 AS valor").fetchone()
        assert row is not None
        assert row["valor"] == 1

    def test_connection_retorna_dict_row(self):
        """As rows retornadas devem ser dicionários (dict_row configurado)."""
        from src.db import get_connection
        with get_connection() as conn:
            row = conn.execute("SELECT 42 AS numero, 'teste' AS texto").fetchone()
        assert isinstance(row, dict)
        assert row["numero"] == 42
        assert row["texto"] == "teste"

    def test_close_pool_permite_reconexao(self):
        """Após close_pool(), uma nova chamada a get_pool() deve funcionar."""
        from src import db as db_module
        pool1 = db_module.get_pool()
        db_module.close_pool()
        assert db_module._pool is None
        pool2 = db_module.get_pool()
        assert pool2 is not None

    def test_multiplas_conexoes_simultaneas(self):
        """O pool deve suportar múltiplas conexões simultâneas."""
        from src.db import get_connection
        results = []

        # Abre 3 conexões simultaneamente (abaixo do min_size=2 para não bloquear)
        with get_connection() as conn1:
            with get_connection() as conn2:
                r1 = conn1.execute("SELECT 1 AS n").fetchone()
                r2 = conn2.execute("SELECT 2 AS n").fetchone()
                results.extend([r1["n"], r2["n"]])

        assert results == [1, 2]

    def test_tabelas_do_projeto_existem(self):
        """Verifica que as 6 tabelas do projeto foram criadas pelo init_db.sql."""
        from src.db import get_connection

        expected_tables = {
            "agent_sessions",
            "execution_history",
            "llm_cache",
            "llm_cache_stats",
            "long_term_memory",
            "deep_search_cache",
        }

        with get_connection() as conn:
            rows = conn.execute("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
            """).fetchall()

        actual_tables = {row["tablename"] for row in rows}
        missing = expected_tables - actual_tables
        assert not missing, f"Tabelas ausentes no PostgreSQL: {missing}"

    def test_transacao_com_rollback(self):
        """Uma exceção dentro do bloco with deve causar rollback automático."""
        from src.db import get_connection

        with get_connection() as conn:
            # Cria uma tabela temporária para o teste
            conn.execute("CREATE TEMP TABLE test_rollback (val TEXT)")
            conn.execute("INSERT INTO test_rollback VALUES ('antes')")
            conn.commit()

        # Tenta inserir e força rollback via exceção
        try:
            with get_connection() as conn:
                conn.execute("INSERT INTO test_rollback VALUES ('rollback_test')")
                raise ValueError("Forçando rollback")
        except ValueError:
            pass

        # A linha 'rollback_test' não deve existir
        with get_connection() as conn:
            rows = conn.execute("SELECT val FROM test_rollback").fetchall()

        vals = [r["val"] for r in rows]
        assert "rollback_test" not in vals
        assert "antes" in vals
