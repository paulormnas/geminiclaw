"""Ativos declarados, download fixo e origens de montagem (v18.5-sandbox-phases, capacidade code-sandbox)."""

import hashlib
import os
from pathlib import Path

import pytest

from src.skills.code import fetch_assets
from src.skills.code.assets import (
    AssetSpec,
    cached_path,
    parse_assets,
    sha256_file,
    verify_and_cache,
)
from src.skills.code.inputs import (
    MountSourceError,
    NoneShareableClassifier,
    check_mount_source,
    list_input_files,
)

VALID_SHA = "a" * 64


# --- Requirement: Ativos declarados, verificados e em cache (validação) ----------------------

@pytest.mark.unit
@pytest.mark.parametrize("destino", ["../x", "a/b", "/abs", "", ".oculto", "a..b", "x" * 101])
def test_destino_recusado(destino):
    """Cenário: Destino ou URL recusados (destino)."""
    specs, errors = parse_assets([{"url": "https://exemplo.org/a.bin", "destino": destino}])
    assert specs == [] and len(errors) == 1
    assert "destino" in errors[0]


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/",
        "file:///etc/passwd",
        "ftp://exemplo.org/a",
        "http://127.0.0.1/a",
        "http://localhost/a",
        "http://10.0.0.5/a",
        "http://192.168.1.1/a",
        "http://[::1]/a",
        "http://100.64.0.1/a",
        "http:///sem-host",
    ],
)
def test_url_recusada(url):
    """Cenário: Destino ou URL recusados (URL)."""
    specs, errors = parse_assets([{"url": url, "destino": "x.bin"}])
    assert specs == [] and len(errors) == 1
    assert "URL recusada" in errors[0]


@pytest.mark.unit
def test_assets_validos_e_sha_normalizado():
    specs, errors = parse_assets([
        {"url": "https://exemplo.org/pesos.pt", "destino": "pesos.pt", "sha256": VALID_SHA.upper()},
        {"url": "http://exemplo.org/c.txt", "destino": "c.txt", "sha256": None},
    ])
    assert errors == []
    assert specs[0].sha256 == VALID_SHA and specs[1].sha256 is None


@pytest.mark.unit
def test_assets_sha_invalido_repetido_e_formato():
    _, errors = parse_assets([{"url": "https://e.org/a", "destino": "a", "sha256": "xyz"}])
    assert "sha256" in errors[0]
    _, errors = parse_assets([
        {"url": "https://e.org/a", "destino": "a"},
        {"url": "https://e.org/b", "destino": "a"},
    ])
    assert "repetido" in errors[0]
    _, errors = parse_assets(["https://e.org/a"])
    assert "objeto" in errors[0]
    _, errors = parse_assets([{"url": "https://e.org/a", "destino": f"a{i}"} for i in range(11)])
    assert "máximo" in errors[0]


# --- verificação no host e cache -----------------------------------------------------------

def _stage(tmp_path: Path, name: str, content: bytes) -> tuple[Path, Path]:
    staging, cache = tmp_path / "staging", tmp_path / "cache"
    staging.mkdir(exist_ok=True)
    (staging / name).write_bytes(content)
    return staging, cache


@pytest.mark.unit
def test_hash_divergente_traz_os_dois_hashes(tmp_path):
    """Cenário: Hash divergente."""
    staging, cache = _stage(tmp_path, "p.bin", b"conteudo")
    real = hashlib.sha256(b"conteudo").hexdigest()
    records, error = verify_and_cache([AssetSpec("https://e.org/p", "p.bin", VALID_SHA)], staging, cache)

    assert records == []
    assert VALID_SHA in error and real in error
    assert list(cache.iterdir()) == []  # nada entra no cache


@pytest.mark.unit
def test_ativo_sem_hash_declarado_registra_o_calculado(tmp_path):
    """Cenário: Ativo sem hash declarado."""
    staging, cache = _stage(tmp_path, "p.bin", b"conteudo")
    real = hashlib.sha256(b"conteudo").hexdigest()
    records, error = verify_and_cache([AssetSpec("https://e.org/p", "p.bin", None)], staging, cache)

    assert error is None
    assert records[0].sha256 == real and records[0].hash_declarado is False
    assert records[0].origem == "download" and records[0].tamanho == len(b"conteudo")
    assert cached_path(cache, real).read_bytes() == b"conteudo"
    assert not (staging / "p.bin").exists()  # movido


@pytest.mark.unit
def test_hash_declarado_correto(tmp_path):
    staging, cache = _stage(tmp_path, "p.bin", b"abc")
    real = hashlib.sha256(b"abc").hexdigest()
    records, error = verify_and_cache([AssetSpec("https://e.org/p", "p.bin", real)], staging, cache)
    assert error is None and records[0].hash_declarado is True


@pytest.mark.unit
def test_arquivo_ausente_ou_nao_regular(tmp_path):
    staging, cache = _stage(tmp_path, "p.bin", b"abc")
    _, error = verify_and_cache([AssetSpec("https://e.org/q", "q.bin", None)], staging, cache)
    assert "não foi baixado" in error
    (staging / "link").symlink_to(staging / "p.bin")
    _, error = verify_and_cache([AssetSpec("https://e.org/q", "link", None)], staging, cache)
    assert "não é um arquivo regular" in error


@pytest.mark.unit
def test_cache_ignora_symlink(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (tmp_path / "alvo").write_bytes(b"x")
    (cache / VALID_SHA).symlink_to(tmp_path / "alvo")
    assert cached_path(cache, VALID_SHA) is None
    assert sha256_file(tmp_path / "alvo") == hashlib.sha256(b"x").hexdigest()


# --- script de download (fixo, somente stdlib) -----------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize(
    "address, blocked",
    [("127.0.0.1", True), ("10.1.2.3", True), ("169.254.169.254", True), ("100.64.0.9", True),
     ("::1", True), ("::ffff:10.0.0.1", True), ("8.8.8.8", False), ("2606:4700::1111", False)],
)
def test_faixas_bloqueadas(address, blocked):
    assert fetch_assets.blocked_address(address) is blocked


@pytest.mark.unit
def test_host_resolvido_para_endereco_interno_e_bloqueado(monkeypatch):
    monkeypatch.setattr(
        fetch_assets.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.7", 80))]
    )
    with pytest.raises(fetch_assets.AssetError, match="interno"):
        fetch_assets._resolve("interno.exemplo.org", 80, ())
    # lista de permissão injetada (somente testes)
    assert fetch_assets._resolve("interno.exemplo.org", 80, ("interno.exemplo.org",)) == "10.0.0.7"


@pytest.mark.unit
def test_redirecionamento_para_interno_e_revalidado(monkeypatch, tmp_path):
    """Um redirecionamento para IP interno é recusado na revalidação."""
    class Resp:
        status = 302

        def getheader(self, name):
            return "http://169.254.169.254/latest" if name == "Location" else None

    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Resp()

        def close(self):
            pass

    monkeypatch.setattr(fetch_assets, "_resolve", lambda *a, **k: "93.184.216.34")
    monkeypatch.setattr(fetch_assets, "_PinnedHTTPSConnection", Conn)
    with pytest.raises(fetch_assets.AssetError, match="bloqueado"):
        fetch_assets.download("https://exemplo.org/a", str(tmp_path / "a"), 100)


@pytest.mark.unit
def test_download_respeita_limite_de_tamanho(monkeypatch, tmp_path):
    class Resp:
        status = 200

        def __init__(self):
            self._chunks = [b"x" * 60, b"y" * 60, b""]

        def getheader(self, name):
            return None

        def read(self, n):
            return self._chunks.pop(0)

    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Resp()

        def close(self):
            pass

    monkeypatch.setattr(fetch_assets, "_resolve", lambda *a, **k: "93.184.216.34")
    monkeypatch.setattr(fetch_assets, "_PinnedHTTPConnection", Conn)
    with pytest.raises(fetch_assets.AssetError, match="excede"):
        fetch_assets.download("http://exemplo.org/a", str(tmp_path / "a"), 100)


# --- origens de montagem e classificador -------------------------------------------------------

@pytest.mark.unit
def test_symlink_em_insumos_e_recusado(tmp_path):
    """Cenário: Origem de montagem fora do lugar."""
    session = tmp_path / "s"
    snap = session / "input_snapshot"
    snap.mkdir(parents=True)
    (tmp_path / "segredo.txt").write_text("x")
    (snap / "ok.csv").write_text("a,b")
    (snap / "ataque").symlink_to(tmp_path / "segredo.txt")
    with pytest.raises(MountSourceError, match="link simbólico"):
        list_input_files(snap, session)


@pytest.mark.unit
def test_pasta_de_insumos_symlink_para_fora_e_recusada(tmp_path):
    session = tmp_path / "s"
    session.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    (session / "input_snapshot").symlink_to(fora)
    with pytest.raises(MountSourceError):
        list_input_files(session / "input_snapshot", session)


@pytest.mark.unit
def test_lista_insumos_regulares(tmp_path):
    snap = tmp_path / "s" / "input_snapshot"
    (snap / "sub").mkdir(parents=True)
    (snap / "a.csv").write_text("1")
    (snap / "sub" / "b.txt").write_text("2")
    files = list_input_files(snap, tmp_path / "s")
    assert [f.relative_to(snap).as_posix() for f in files] == ["a.csv", "sub/b.txt"]


@pytest.mark.unit
def test_check_mount_source(tmp_path):
    root = tmp_path / "out"
    (root / "s1").mkdir(parents=True)
    assert check_mount_source(root / "s1", root) == (root / "s1").resolve()
    (tmp_path / "fora").mkdir()
    (root / "link").symlink_to(tmp_path / "fora")
    with pytest.raises(MountSourceError):
        check_mount_source(root / "link", root)
    with pytest.raises(MountSourceError):
        check_mount_source(tmp_path / "fora", root)


@pytest.mark.unit
def test_classificador_padrao_nao_compartilha_nada(tmp_path):
    assert NoneShareableClassifier().is_shareable(tmp_path / "qualquer.csv") is False


@pytest.mark.unit
def test_fetch_assets_nao_importa_nada_do_projeto():
    """O script injetado no container usa só a biblioteca padrão."""
    source = Path(fetch_assets.__file__).read_text(encoding="utf-8")
    assert "from src" not in source and "import src" not in source
    assert os.path.basename(fetch_assets.__file__) == "fetch_assets.py"
