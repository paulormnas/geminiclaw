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
class TestConfigureAgeSession:
    """Testes para ``_configure_age_session`` (PR #64 review, achado 'Importante').

    A exceção capturada deve ser restrita a ``psycopg.errors.UndefinedFile``
    (extensão AGE ainda não instalada — ``LOAD 'age'`` não encontra a
    biblioteca compartilhada). Qualquer outra falha deve propagar, sem ser
    mascarada como "grafo opcional".
    """

    def test_sucesso_carrega_age_e_ajusta_search_path(self):
        """Caminho feliz: LOAD e SET search_path executam sem exceção."""
        from src.db import _configure_age_session

        mock_conn = MagicMock()
        _configure_age_session(mock_conn)

        mock_conn.execute.assert_any_call("LOAD 'age'")
        mock_conn.execute.assert_any_call('SET search_path = ag_catalog, "$user", public')
        mock_conn.rollback.assert_not_called()

    def test_sucesso_encerra_a_transacao_para_o_pool(self):
        """O commit é obrigatório: sem ele o pool descarta a conexão (status INTRANS)."""
        from src.db import _configure_age_session

        mock_conn = MagicMock()
        _configure_age_session(mock_conn)

        mock_conn.commit.assert_called_once()

    def test_extensao_ausente_e_ignorada_silenciosamente(self):
        """UndefinedFile (extensão AGE não instalada) é registrado e engolido."""
        from psycopg.errors import UndefinedFile

        from src.db import _configure_age_session

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = UndefinedFile(
            'could not access file "$libdir/age": No such file or directory'
        )

        _configure_age_session(mock_conn)  # não deve levantar

        mock_conn.rollback.assert_called_once()

    def test_outra_falha_de_psycopg_e_propagada(self):
        """Uma falha real de conectividade/permissão não deve ser mascarada (fail-fast)."""
        from psycopg.errors import InsufficientPrivilege

        from src.db import _configure_age_session

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = InsufficientPrivilege("permission denied for database")

        with pytest.raises(InsufficientPrivilege):
            _configure_age_session(mock_conn)

    def test_excecao_generica_nao_relacionada_a_psycopg_e_propagada(self):
        """Um erro que não seja de banco (ex.: bug de programação) também deve propagar."""
        from src.db import _configure_age_session

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = RuntimeError("erro inesperado, não relacionado ao AGE")

        with pytest.raises(RuntimeError):
            _configure_age_session(mock_conn)


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
