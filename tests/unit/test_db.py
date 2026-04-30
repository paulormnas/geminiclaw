"""Testes unitários para src/db.py.

Usa mock para não exigir um PostgreSQL real.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


@pytest.mark.unit
class TestGetPool:
    """Testes para a função get_pool()."""

    def setup_method(self):
        """Garante que o pool singleton é resetado antes de cada teste."""
        import src.db as db_module
        db_module._pool = None

    def teardown_method(self):
        """Garante limpeza do estado após cada teste."""
        import src.db as db_module
        db_module._pool = None

    def test_get_pool_retorna_singleton(self):
        """get_pool() deve retornar a mesma instância em chamadas subsequentes."""
        mock_pool = MagicMock()

        with patch("src.db.ConnectionPool", return_value=mock_pool):
            from src.db import get_pool
            pool1 = get_pool()
            pool2 = get_pool()

        assert pool1 is pool2
        # ConnectionPool deve ser instanciado apenas uma vez
        # (segunda chamada reutiliza o singleton)

    def test_get_pool_inicializa_com_min_max_size(self):
        """ConnectionPool deve ser criado com min_size=2 e max_size=10."""
        mock_pool = MagicMock()

        with patch("src.db.ConnectionPool", return_value=mock_pool) as mock_cls:
            from src.db import get_pool
            get_pool()

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["min_size"] == 2
        assert call_kwargs["max_size"] == 10

    def test_get_pool_usa_dict_row(self):
        """ConnectionPool deve ser configurado com dict_row como row_factory."""
        from psycopg.rows import dict_row
        mock_pool = MagicMock()

        with patch("src.db.ConnectionPool", return_value=mock_pool) as mock_cls:
            from src.db import get_pool
            get_pool()

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["kwargs"]["row_factory"] is dict_row


@pytest.mark.unit
class TestClosePool:
    """Testes para a função close_pool()."""

    def setup_method(self):
        import src.db as db_module
        db_module._pool = None

    def teardown_method(self):
        import src.db as db_module
        db_module._pool = None

    def test_close_pool_chama_close_no_pool(self):
        """close_pool() deve chamar .close() no pool existente."""
        mock_pool = MagicMock()

        with patch("src.db.ConnectionPool", return_value=mock_pool):
            from src import db as db_module
            db_module.get_pool()
            db_module.close_pool()

        mock_pool.close.assert_called_once()

    def test_close_pool_zera_singleton(self):
        """Após close_pool(), _pool deve ser None."""
        mock_pool = MagicMock()

        with patch("src.db.ConnectionPool", return_value=mock_pool):
            from src import db as db_module
            db_module.get_pool()
            db_module.close_pool()

        assert db_module._pool is None

    def test_close_pool_sem_pool_ativo_nao_levanta(self):
        """close_pool() não deve levantar exceção se o pool ainda não foi inicializado."""
        from src import db as db_module
        db_module._pool = None  # garante estado inicial
        # Não deve lançar exceção
        db_module.close_pool()

    def test_close_pool_permite_reinicializacao(self):
        """Após close_pool(), get_pool() deve criar um novo pool."""
        mock_pool_1 = MagicMock()
        mock_pool_2 = MagicMock()

        with patch("src.db.ConnectionPool", side_effect=[mock_pool_1, mock_pool_2]):
            from src import db as db_module
            pool_a = db_module.get_pool()
            db_module.close_pool()
            pool_b = db_module.get_pool()

        assert pool_a is mock_pool_1
        assert pool_b is mock_pool_2
        assert pool_a is not pool_b


@pytest.mark.unit
class TestGetConnection:
    """Testes para a função get_connection()."""

    def setup_method(self):
        import src.db as db_module
        db_module._pool = None

    def teardown_method(self):
        import src.db as db_module
        db_module._pool = None

    def test_get_connection_delega_ao_pool(self):
        """get_connection() deve retornar o context manager do pool."""
        mock_conn_ctx = MagicMock()
        mock_pool = MagicMock()
        mock_pool.connection.return_value = mock_conn_ctx

        with patch("src.db.ConnectionPool", return_value=mock_pool):
            from src import db as db_module
            result = db_module.get_connection()

        mock_pool.connection.assert_called_once()
        assert result is mock_conn_ctx
