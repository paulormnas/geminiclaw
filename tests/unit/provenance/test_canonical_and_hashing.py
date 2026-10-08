"""Canonicalização, hash de registro e cache de hash (spec execution-provenance)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.provenance.canonical import ZERO_HASH, CanonicalError, canonical, metric_text, record_hash
from src.provenance.hashing import HashCache, hash_file, sha256_file

pytestmark = pytest.mark.unit


def test_canonicalizacao_estavel_independe_da_ordem_das_chaves():
    a = {"b": 1, "a": {"y": [1, 2], "x": "ç"}}
    b = {"a": {"x": "ç", "y": [1, 2]}, "b": 1}
    assert canonical(a) == canonical(b) == '{"a":{"x":"ç","y":[1,2]},"b":1}'.encode()
    assert record_hash(a) == record_hash(b) and len(record_hash(a)) == 64


def test_float_no_registro_e_recusado():
    with pytest.raises(CanonicalError, match=r"\$\.corpo\.x"):
        canonical({"corpo": {"x": 0.5}})
    with pytest.raises(CanonicalError):
        canonical({"corpo": [1, [2, 3.0]]})


def test_metrica_vira_texto():
    """Scenario: Métricas como texto."""
    assert metric_text(0.8) == "0.8"
    assert metric_text(3) == "3"
    assert metric_text(float("nan")) == "nan"
    assert metric_text(float("inf")) == "inf" and metric_text(float("-inf")) == "-inf"
    assert metric_text(True) is None and metric_text("0.8") is None


def test_zero_hash_tem_64_zeros():
    assert ZERO_HASH == "0" * 64


def test_hash_de_arquivo_em_blocos(tmp_path: Path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"x" * (3 * 1024 * 1024 + 5))
    import hashlib

    assert sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_cache_acerta_para_arquivo_grande_inalterado(tmp_path: Path, monkeypatch):
    """Scenario: Entrada grande inalterada — o hash vem do cache, sem releitura."""
    path = tmp_path / "grande.csv"
    path.write_bytes(b"a" * 4096)
    cache = HashCache(tmp_path / "cache.db", min_bytes=1024)
    first, _ = hash_file(path, cache)
    assert cache.misses == 1 and cache.hits == 0

    def boom(*_a, **_k):
        raise AssertionError("o arquivo não deveria ser relido")

    monkeypatch.setattr("src.provenance.hashing.sha256_file", boom)
    second, size = hash_file(path, cache)
    assert second == first and size == 4096 and cache.hits == 1


def test_cache_erra_quando_mtime_muda(tmp_path: Path):
    path = tmp_path / "grande.csv"
    path.write_bytes(b"a" * 4096)
    cache = HashCache(tmp_path / "cache.db", min_bytes=1024)
    first, _ = hash_file(path, cache)
    path.write_bytes(b"b" * 4096)
    os.utime(path, ns=(1, 2_000_000_000))
    second, _ = hash_file(path, cache)
    assert second != first and cache.misses == 2


def test_arquivo_pequeno_nao_usa_cache(tmp_path: Path):
    path = tmp_path / "p.txt"
    path.write_text("oi")
    cache = HashCache(tmp_path / "cache.db", min_bytes=1024)
    hash_file(path, cache)
    hash_file(path, cache)
    assert cache.hits == 0 and cache.misses == 0


def test_full_ignora_o_cache(tmp_path: Path):
    """Scenario: Verificação completa — alteração que preserva tamanho e mtime_ns só é vista com ``full``."""
    path = tmp_path / "grande.csv"
    path.write_bytes(b"a" * 4096)
    stat = path.stat()
    cache = HashCache(tmp_path / "cache.db", min_bytes=1024)
    original, _ = hash_file(path, cache)
    path.write_bytes(b"z" * 4096)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    cached, _ = hash_file(path, cache)
    assert cached == original  # o cache confia em tamanho + mtime_ns
    full, _ = hash_file(path, cache, full=True)
    assert full != original


def test_cache_indisponivel_nao_derruba_o_hash(tmp_path: Path):
    path = tmp_path / "grande.csv"
    path.write_bytes(b"a" * 4096)
    blocker = tmp_path / "bloqueio"
    blocker.write_text("arquivo no lugar do diretório")
    cache = HashCache(blocker / "cache.db", min_bytes=1024)
    digest, size = hash_file(path, cache)
    assert digest == sha256_file(path) and size == 4096
