"""Cenários da v18.5-sandbox-phases que exigem a imagem real (capacidade code-sandbox).

Pulados quando não há daemon de containers ou quando a imagem ``SANDBOX_IMAGE`` não foi construída
(``bash scripts/build_images.sh``). Os pacotes sob demanda exigem rede do daemon. Os cenários de ativos
com servidor HTTP local exigem ``SANDBOX_TEST_HOST_ALIAS`` (nome pelo qual o container alcança o host,
ex.: ``host.docker.internal`` no Mac); esse nome é liberado do bloqueio de IPs internos só nestes testes,
pelo parâmetro ``allow_private_asset_hosts`` do sandbox.

ESCRITOS E NÃO EXECUTADOS na entrega da mudança (bateria de integração ao final, a pedido do pesquisador).
"""

import hashlib
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import docker
import pytest

from src import config
from src.skills.code.sandbox import PythonSandbox


def _image_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(config.SANDBOX_IMAGE)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _image_available(),
        reason="Daemon de containers inacessível ou imagem do sandbox ausente (bash scripts/build_images.sh).",
    ),
]

HOST_ALIAS = os.environ.get("SANDBOX_TEST_HOST_ALIAS")
needs_host_alias = pytest.mark.skipif(
    not HOST_ALIAS, reason="Defina SANDBOX_TEST_HOST_ALIAS (nome do host visto pelo container)."
)


def _sandbox(tmp_path: Path, **kwargs) -> PythonSandbox:
    kwargs.setdefault("work_dir", str(tmp_path / "work"))
    kwargs.setdefault("asset_cache_dir", str(tmp_path / "cache"))
    return PythonSandbox(**kwargs)


def _run(sandbox: PythonSandbox, tmp_path: Path, code: str, task: str = "t", **kwargs):
    return sandbox.run(code=code, session_id="s", task_name=task, output_dir=str(tmp_path / "out"), **kwargs)


_NO_NETWORK_CODE = (
    "import socket\n"
    "try:\n"
    "    socket.getaddrinfo('example.org', 80)\n"
    "except OSError:\n"
    "    print('sem dns')\n"
    "else:\n"
    "    raise SystemExit('DNS resolveu: há rede')\n"
)


@pytest.fixture
def http_server(tmp_path: Path):
    """Servidor HTTP local servindo ``tmp_path/www`` em todas as interfaces."""
    www = tmp_path / "www"
    www.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(www))
    server = ThreadingHTTPServer(("0.0.0.0", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield www, server.server_address[1]
    server.shutdown()


# --- tasks 5.3: execução sem rede -----------------------------------------------------------------

def test_script_sem_rede_nao_resolve_dns(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path), tmp_path, _NO_NETWORK_CODE)
    assert result.exit_code == 0, result.stderr
    assert "sem dns" in result.stdout and result.rede_na_execucao is False


def test_com_packages_o_script_continua_sem_rede(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path), tmp_path, "import tabulate\n" + _NO_NETWORK_CODE, packages=["tabulate"])
    assert result.exit_code == 0, result.stderr
    assert result.pacotes.get("tabulate") and result.imagem.id
    assert [f.nome for f in result.fases] == ["install", "execute"]


def test_download_nao_declarado_no_script(tmp_path: Path) -> None:
    code = "import urllib.request\nurllib.request.urlopen('https://example.org/pesos.bin', timeout=5)\n"
    result = _run(_sandbox(tmp_path), tmp_path, code)
    assert result.exit_code != 0 and result.download_nao_declarado is True


# --- tasks 5.4: falha de instalação -----------------------------------------------------------------

def test_pacote_inexistente_nao_roda_o_script(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path), tmp_path, "print('nao deveria rodar')", packages=["pacote-que-nao-existe-xyz"])
    assert result.fase_falha == "install" and result.install_failed is True
    assert "nao deveria rodar" not in result.stdout
    assert "pacote-que-nao-existe-xyz" in result.stderr


# --- tasks 5.5: ativos ----------------------------------------------------------------------------------

@needs_host_alias
def test_ativo_baixado_verificado_e_em_cache(tmp_path: Path, http_server) -> None:
    www, port = http_server
    (www / "p.bin").write_bytes(b"pesos")
    sha = hashlib.sha256(b"pesos").hexdigest()
    url = f"http://{HOST_ALIAS}:{port}/p.bin"
    sandbox = _sandbox(tmp_path, allow_private_asset_hosts=(HOST_ALIAS,))
    code = "print(open('/assets/p.bin','rb').read().decode())\n" + _NO_NETWORK_CODE

    # sem hash declarado: confiança no primeiro uso, registrada
    first = _run(sandbox, tmp_path, code, assets=[{"url": url, "destino": "p.bin"}])
    assert first.exit_code == 0, first.stderr
    assert "pesos" in first.stdout
    assert (first.ativos[0].sha256, first.ativos[0].hash_declarado, first.ativos[0].origem) == (sha, False, "download")

    # com hash declarado e já em cache: nenhum container de preparação
    second = _run(sandbox, tmp_path, code, task="t2", assets=[{"url": url, "destino": "p.bin", "sha256": sha}])
    assert second.exit_code == 0, second.stderr
    assert second.ativos[0].origem == "cache"
    assert [f.nome for f in second.fases] == ["execute"]


@needs_host_alias
def test_hash_divergente(tmp_path: Path, http_server) -> None:
    www, port = http_server
    (www / "p.bin").write_bytes(b"pesos")
    sandbox = _sandbox(tmp_path, allow_private_asset_hosts=(HOST_ALIAS,))
    result = _run(sandbox, tmp_path, "print('nao deveria rodar')",
                  assets=[{"url": f"http://{HOST_ALIAS}:{port}/p.bin", "destino": "p.bin", "sha256": "0" * 64}])
    assert result.fase_falha == "fetch_assets" and "nao deveria rodar" not in result.stdout


def test_url_interna_bloqueada_sem_lista_de_permissao(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path), tmp_path, "print('x')",
                  assets=[{"url": "http://169.254.169.254/latest", "destino": "m"}])
    assert result.exit_code == -1 and "assets" in result.stderr


# --- tasks 5.6: /inputs somente leitura, copy e symlink --------------------------------------------------

def _snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "out" / "s" / "input_snapshot"
    snap.mkdir(parents=True)
    (snap / "dados.csv").write_text("a,b\n1,2\n")
    return snap


def test_inputs_somente_leitura(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "mount")
    snap = _snapshot(tmp_path)
    code = (
        "try:\n"
        "    open('/inputs/dados.csv', 'w').write('x')\n"
        "except OSError:\n"
        "    print('ro')\n"
        "else:\n"
        "    raise SystemExit('gravou em /inputs')\n"
    )
    result = _run(_sandbox(tmp_path), tmp_path, code)
    assert result.exit_code == 0, result.stderr
    assert "ro" in result.stdout and (snap / "dados.csv").read_text() == "a,b\n1,2\n"


def test_entrega_por_copia(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    _snapshot(tmp_path)
    result = _run(_sandbox(tmp_path), tmp_path, "print(open('/inputs/dados.csv').read())")
    assert result.exit_code == 0, result.stderr
    assert "a,b" in result.stdout and result.modo_entrega == "copy"


def test_symlink_em_insumos_recusado(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    (tmp_path / "segredo.txt").write_text("x")
    (snap / "ataque").symlink_to(tmp_path / "segredo.txt")
    result = _run(_sandbox(tmp_path), tmp_path, "print('x')")
    assert result.fase_falha == "infra" and "link simbólico" in result.stderr


# --- tasks 5.7: dono dos artefatos -----------------------------------------------------------------------

def test_artefatos_do_uid_do_host_sem_chmod_777(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path), tmp_path, "open('/outputs/a.txt', 'w').write('x')")
    assert result.exit_code == 0, result.stderr
    info = (tmp_path / "out" / "s" / "t" / "a.txt").stat()
    assert info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o002


# --- tasks 5.5.2: FIFO criado em /outputs --------------------------------------------------------------

def test_fifo_em_outputs_e_removido(tmp_path: Path) -> None:
    result = _run(_sandbox(tmp_path), tmp_path, "import os; os.mkfifo('/outputs/pipe')")
    assert result.exit_code == 0, result.stderr
    assert not (tmp_path / "out" / "s" / "t" / "pipe").exists()


# --- tasks 5.8: paralelismo ---------------------------------------------------------------------------

def _timed_run(sandbox: PythonSandbox, tmp_path: Path, task: str):
    started = time.monotonic()
    result = _run(sandbox, tmp_path, "import time; time.sleep(2)", task=task)
    return result, time.monotonic() - started


def test_duas_execucoes_paralelas_levam_menos_que_a_soma(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [f.result() for f in [pool.submit(_timed_run, sandbox, tmp_path, f"t{i}") for i in range(2)]]
    elapsed = time.monotonic() - started

    assert all(result.exit_code == 0 for result, _ in outcomes)
    assert elapsed < sum(duration for _, duration in outcomes) - 1
