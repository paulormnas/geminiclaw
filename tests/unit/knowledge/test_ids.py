"""Testes unitários para src/knowledge/ids.py (geração de IDs e NODE_ID)."""

import re
import uuid

import pytest

from src.knowledge.ids import generate_node_id, get_or_create_node_id, uuid7

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


@pytest.mark.unit
class TestUuid7:
    def test_gera_uuid_valido(self):
        """uuid7() deve gerar uma instância válida de uuid.UUID."""
        value = uuid7()
        assert isinstance(value, uuid.UUID)

    def test_versao_e_variante_corretas(self):
        """O UUID gerado deve ter versão 7 e variante RFC 4122."""
        value = uuid7()
        assert value.version == 7
        assert UUID_RE.match(str(value))

    def test_ids_sao_unicos(self):
        """Chamadas sucessivas devem gerar IDs distintos."""
        ids = {str(uuid7()) for _ in range(200)}
        assert len(ids) == 200

    def test_ids_sao_ordenaveis_por_tempo(self):
        """IDs gerados em sequência devem ser ordenáveis lexicograficamente (UUIDv7)."""
        ids = [str(uuid7()) for _ in range(5)]
        assert ids == sorted(ids)


@pytest.mark.unit
class TestGenerateNodeId:
    def test_retorna_texto_uuid7(self):
        """generate_node_id() deve retornar uma string no formato UUIDv7."""
        node_id = generate_node_id()
        assert isinstance(node_id, str)
        assert UUID_RE.match(node_id)


@pytest.mark.unit
class TestGetOrCreateNodeId:
    def test_gera_e_persiste_na_primeira_chamada(self, tmp_path):
        """Na primeira chamada, deve gerar um NODE_ID e persistir no arquivo."""
        node_id = get_or_create_node_id(config_dir=tmp_path)
        assert UUID_RE.match(node_id)
        assert (tmp_path / "node_id").read_text(encoding="utf-8").strip() == node_id

    def test_retorna_mesmo_valor_apos_reinicio(self, tmp_path):
        """Chamadas subsequentes (simulando reinício) devem retornar o mesmo NODE_ID."""
        first = get_or_create_node_id(config_dir=tmp_path)
        second = get_or_create_node_id(config_dir=tmp_path)
        assert first == second

    def test_arquivo_vazio_gera_novo_id(self, tmp_path):
        """Um arquivo node_id vazio não deve quebrar — um novo ID é gerado."""
        (tmp_path / "node_id").write_text("", encoding="utf-8")
        node_id = get_or_create_node_id(config_dir=tmp_path)
        assert UUID_RE.match(node_id)

    def test_diretorio_somente_leitura_nao_levanta(self, tmp_path, monkeypatch):
        """Falha ao persistir (ex.: diretório somente-leitura) não deve propagar exceção."""
        import os

        directory = tmp_path / "readonly"
        directory.mkdir()
        os.chmod(directory, 0o400)
        try:
            node_id = get_or_create_node_id(config_dir=directory / "nested")
            assert UUID_RE.match(node_id)
        finally:
            os.chmod(directory, 0o700)
