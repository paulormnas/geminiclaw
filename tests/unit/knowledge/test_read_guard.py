"""Testes unitários para src/knowledge/read_guard.py.

Scenario "Tentativa de escrita em consulta livre" (spec.md): read_query com
CREATE é recusado pelo filtro (tarefa 4.2 de tasks.md).

A classe ``TestRejeitaDollarQuote`` cobre o achado bloqueante do code review
do PR #64: ``AgeGraphStore.read_query`` encapsula ``cypher`` num bloco SQL
``$$ ... $$`` sem tag — um ``cypher`` contendo o literal ``$$`` fecharia o
dollar-quote prematuramente e permitiria injetar SQL arbitrário fora da
sandbox Cypher.
"""

import pytest

from src.knowledge.errors import ReadOnlyQueryViolation
from src.knowledge.read_guard import reject_unsafe_read_query


@pytest.mark.unit
class TestRejectUnsafeReadQuery:
    @pytest.mark.parametrize("keyword", ["CREATE", "MERGE", "SET", "DELETE", "REMOVE"])
    def test_recusa_palavras_chave_de_escrita(self, keyword):
        with pytest.raises(ReadOnlyQueryViolation):
            reject_unsafe_read_query(f"{keyword} (n:Projeto {{titulo: 'x'}})")

    def test_recusa_case_insensitive(self):
        with pytest.raises(ReadOnlyQueryViolation):
            reject_unsafe_read_query("create (n:Projeto {titulo: 'x'})")

    def test_aceita_consulta_de_leitura(self):
        reject_unsafe_read_query("MATCH (n:Projeto) RETURN n LIMIT 10")

    def test_nao_recusa_palavra_dentro_de_outra_palavra(self):
        """'RESET' não deve disparar o filtro de 'SET' (borda de palavra)."""
        reject_unsafe_read_query("MATCH (n) WHERE n.nome = 'RESETADO' RETURN n")


@pytest.mark.unit
class TestRejeitaDollarQuote:
    """Achado bloqueante do code review do PR #64: injeção via fechamento de '$$'."""

    def test_recusa_dollar_quote_literal(self):
        with pytest.raises(ReadOnlyQueryViolation):
            reject_unsafe_read_query("MATCH (n:Projeto) RETURN n $$; DROP TABLE ag_catalog.ag_graph; --")

    def test_recusa_tentativa_de_escape_com_union_sql(self):
        """Simula o vetor descrito no review: fechar o dollar-quote e injetar SQL via UNION."""
        payload = (
            "MATCH (n:Projeto) RETURN n $$, %s::agtype) as (result agtype) "
            "UNION SELECT relname::text::agtype FROM pg_catalog.pg_class; --"
        )
        with pytest.raises(ReadOnlyQueryViolation):
            reject_unsafe_read_query(payload)

    def test_recusa_dollar_quote_mesmo_sem_palavra_chave_de_escrita(self):
        """'$$' sozinho, sem nenhuma palavra-chave de escrita, ainda deve ser recusado."""
        with pytest.raises(ReadOnlyQueryViolation):
            reject_unsafe_read_query("$$")

    def test_aceita_consulta_sem_dollar_quote(self):
        reject_unsafe_read_query("MATCH (n:Projeto) WHERE n.titulo = 'x$y' RETURN n")
