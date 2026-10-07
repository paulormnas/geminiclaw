"""Dados de pesquisa só como descritor (v17-input-document-index, requisito homônimo)."""

import struct
import zlib
from pathlib import Path

import pytest

from src.skills.document_processor.descriptors import describe_dataset, describe_image, describe_other


def _png(path: Path, w: int, h: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.mark.unit
def test_csv_descriptor_has_columns_types_and_rows_without_values(tmp_path):
    """Cenário CSV."""
    csv_path = tmp_path / "dados.csv"
    csv_path.write_text("id,massa_g\n" + "\n".join(f"{i},{1234.5 + i}" for i in range(150)) + "\n")

    text = describe_dataset(csv_path)

    assert "id (inteiro)" in text and "massa_g (decimal)" in text
    assert "150 linhas" in text
    assert "1234" not in text and "1235" not in text


@pytest.mark.unit
def test_csv_numeric_header_is_not_leaked(tmp_path):
    csv_path = tmp_path / "d.csv"
    csv_path.write_text("5.1,3.5\n4.9,3.0\n")

    text = describe_dataset(csv_path)

    assert "5.1" not in text and "coluna_1" in text and "2 linhas" in text


@pytest.mark.unit
def test_unreadable_dataset_gets_minimal_descriptor(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json")

    text = describe_dataset(bad)

    assert "x.json" in text and "formato: json" in text


@pytest.mark.unit
def test_png_descriptor_has_dimensions_and_no_ocr(tmp_path):
    """Cenário Imagem."""
    img = tmp_path / "foto.png"
    _png(img, 7, 5)

    text = describe_image(img)

    assert "foto.png" in text and "formato: png" in text and "7x5 px" in text


@pytest.mark.unit
def test_other_descriptor_has_name_format_size(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")

    text = describe_other(f)

    assert "a.bin" in text and "formato: bin" in text and "3 bytes" in text
