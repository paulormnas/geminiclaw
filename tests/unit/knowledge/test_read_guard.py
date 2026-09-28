"""Testes unitários para src/knowledge/read_guard.py.

Scenario "Tentativa de escrita em consulta livre" (spec.md): read_query com
CREATE é recusado pelo filtro (tarefa 4.2 de tasks.md).
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
