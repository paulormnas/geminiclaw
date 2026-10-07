# ruff: noqa: F811 — a fixture make_sandbox é reexportada e usada como argumento
"""Specs da mudança v18.5-sandbox-phases (capacidade code-sandbox), com o cliente do daemon simulado.

Nenhum teste cria container de verdade; os cenários que dependem da imagem real e de rede ficam em
``tests/integration/test_sandbox_phases_real.py``. Reaproveita o ``FakeDaemon`` de ``test_sandbox_slim``.
"""

import hashlib
import io
import json
import logging
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import docker.errors
import pytest
from test_sandbox_slim import FakeDaemon, _run, make_sandbox  # noqa: F401 — fixture reexportada

from src.skills.code.sandbox import NETWORK_FAILURE_SIGNATURES, is_undeclared_download_failure

SHA_A = hashlib.sha256(b"pesos").hexdigest()


class ShareAll:
    def network_allowed(self):
        return True

    def is_shareable(self, path):
        return True


def _snapshot(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    snap = tmp_path / "out" / "s" / "input_snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {"dados.csv": "a,b\n1,2\n"}).items():
        (snap / name).write_text(content)
    return snap


# --- Requirement: Execução do script sem rede ------------------------------------------------

@pytest.mark.unit
def test_pacotes_declarados_nao_ligam_a_rede_do_script(make_sandbox, tmp_path):
    """Cenário: Pacotes declarados não ligam a rede do script."""
    daemon = FakeDaemon(listing=[{"name": "scikit-learn", "version": "1.5.0"}])
    result = _run(make_sandbox(daemon), tmp_path, packages=["scikit-learn>=1.5"])

    assert daemon.run_kwargs["network_disabled"] is True
    assert result.rede_na_execucao is False


@pytest.mark.unit
def test_sem_pacotes_nem_ativos(make_sandbox, tmp_path):
    """Cenário: Sem pacotes nem ativos. Só o container de execução é criado, sem rede."""
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)

    assert len(daemon.run_calls) == 1
    assert daemon.run_kwargs["labels"]["geminiclaw.role"] == "sandbox"
    assert daemon.run_kwargs["network_disabled"] is True


# --- Requirement: Preparação com rede e sem dados ---------------------------------------------

@pytest.mark.unit
def test_montagens_da_preparacao(make_sandbox, tmp_path):
    """Cenário: Montagens da preparação. Só deps, staging e control (ro); ambiente fechado; sem dados da sessão."""
    _snapshot(tmp_path)
    daemon = _FetchDaemon()
    sandbox = make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache"))
    _run(sandbox, tmp_path, packages=["tabulate"],
         assets=[{"url": "https://exemplo.org/p.bin", "destino": "p.bin"}])

    prep = daemon.prep_kwargs
    assert prep["labels"]["geminiclaw.role"] == "sandbox-prep"
    assert prep["network_disabled"] is False
    # Um container por fase: o de instalação não enxerga /staging nem /control (M6).
    assert {v["bind"]: v["mode"] for v in prep["volumes"].values()} == {"/control": "ro", "/staging": "rw"}
    install = daemon.run_calls[1]
    assert install["labels"]["geminiclaw.role"] == "sandbox-prep" and install["network_disabled"] is False
    assert {v["bind"]: v["mode"] for v in install["volumes"].values()} == {"/deps": "rw"}
    assert set(install["environment"]) == {"HOME", "UV_CACHE_DIR", "PATH"}
    assert not prep.get("mounts")
    assert set(prep["environment"]) == {"HOME", "UV_CACHE_DIR", "PATH"}
    assert prep["user"] == f"{os.getuid()}:{os.getgid()}"


@pytest.mark.unit
def test_preparacao_removida_antes_da_execucao(make_sandbox, tmp_path):
    """Cenário: Container de preparação removido antes da execução."""
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    assert daemon.calls.index("run:sandbox-prep") < daemon.calls.index("remove") < daemon.calls.index("run:sandbox")


# --- Requirement: Instalação sem root e com falha explícita -------------------------------------

@pytest.mark.unit
def test_pacote_inexistente_fase_install(make_sandbox, tmp_path):
    """Cenário: Pacote inexistente. fase_falha="install", script não executa, mensagem cita o pacote."""
    daemon = FakeDaemon(install_exit=1, install_output=b"error: No solution found")
    result = _run(make_sandbox(daemon), tmp_path, packages=["pacote-que-nao-existe-xyz"])

    assert result.fase_falha == "install"
    assert result.exit_code != 0
    assert "script" not in daemon.calls
    assert [r["labels"]["geminiclaw.role"] for r in daemon.run_calls] == ["sandbox-prep"]  # sem container de execução
    assert "pacote-que-nao-existe-xyz" in result.stderr
    assert [f.nome for f in result.fases] == ["install"]


@pytest.mark.unit
@pytest.mark.parametrize("item", ["--index-url=http://exemplo", "git+https://exemplo.org/x.git"])
def test_requisito_de_pacote_invalido_antes_de_containers(make_sandbox, tmp_path, item):
    """Cenário: Requisito de pacote inválido."""
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, packages=[item])

    daemon.client.containers.run.assert_not_called()
    assert result.exit_code == -1 and "inválidos" in result.stderr


@pytest.mark.unit
def test_nenhum_exec_como_root_em_nenhuma_fase(make_sandbox, tmp_path):
    """Cenário: Nenhum comando como root (todas as fases, usuário do orquestrador)."""
    daemon = FakeDaemon()
    sandbox = make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache"))
    _run(sandbox, tmp_path, packages=["tabulate"], assets=[{"url": "https://e.org/a", "destino": "a"}])

    assert daemon.exec_calls
    assert all("user" not in kw for _c, kw in daemon.exec_calls)
    assert {c["user"] for c in daemon.run_calls} == {f"{os.getuid()}:{os.getgid()}"}


# --- Requirement: Ativos declarados, verificados e em cache -------------------------------------

class _FetchDaemon(FakeDaemon):
    """Simula o download: grava o conteúdo no diretório de staging do host (bind mount)."""

    def __init__(self, content: bytes = b"pesos", **kwargs):
        super().__init__(**kwargs)
        self.content = content

    def _exec_run(self, cmd, *args, **kwargs):
        if cmd[0] == "python" and cmd[1] == "/control/fetch_assets.py":
            staging = next(h for h, v in self.run_calls[0]["volumes"].items() if v["bind"] == "/staging")
            for item in json.loads(self._spec())["assets"]:
                (Path(staging) / item["destino"]).write_bytes(self.content)
        return super()._exec_run(cmd, *args, **kwargs)

    def _spec(self) -> str:
        return self.control_files["fetch_spec.json"]


@pytest.mark.unit
def test_hash_divergente_nao_executa_o_script(make_sandbox, tmp_path):
    """Cenário: Hash divergente."""
    daemon = _FetchDaemon(content=b"outro conteudo")
    sandbox = make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache"))
    result = _run(sandbox, tmp_path, assets=[{"url": "https://e.org/p", "destino": "p.bin", "sha256": SHA_A}])

    assert result.fase_falha == "fetch_assets"
    assert SHA_A in result.stderr and hashlib.sha256(b"outro conteudo").hexdigest() in result.stderr
    assert "script" not in daemon.calls


@pytest.mark.unit
def test_ativo_sem_hash_declarado(make_sandbox, tmp_path):
    """Cenário: Ativo sem hash declarado. O hash calculado é registrado e o ativo é montado somente leitura."""
    daemon = _FetchDaemon(content=b"pesos")
    cache = tmp_path / "cache"
    result = _run(make_sandbox(daemon, asset_cache_dir=str(cache)), tmp_path,
                  assets=[{"url": "https://e.org/p", "destino": "p.bin", "sha256": None}])

    assert result.fase_falha is None and result.exit_code == 0
    record = result.ativos[0]
    assert (record.sha256, record.hash_declarado, record.origem) == (SHA_A, False, "download")
    mount = daemon.run_kwargs["mounts"][0]
    assert mount["Target"] == "/assets/p.bin" and mount["ReadOnly"] is True
    assert mount["Source"] == str((cache / SHA_A).resolve())
    assert [f.nome for f in result.fases] == ["fetch_assets", "execute"]


@pytest.mark.unit
def test_ativo_ja_em_cache_dispensa_preparacao(make_sandbox, tmp_path):
    """Cenário: Ativo já em cache."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / SHA_A).write_bytes(b"pesos")
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, asset_cache_dir=str(cache)), tmp_path,
                  assets=[{"url": "https://e.org/p", "destino": "p.bin", "sha256": SHA_A}])

    assert [c["labels"]["geminiclaw.role"] for c in daemon.run_calls] == ["sandbox"]
    assert result.ativos[0].origem == "cache" and result.ativos[0].tamanho == 5
    assert daemon.run_kwargs["mounts"][0]["Target"] == "/assets/p.bin"


@pytest.mark.unit
def test_fetch_roda_antes_de_install_e_com_script_fixo(make_sandbox, tmp_path):
    """A preparação baixa e verifica no host antes de instalar; o script de download é o fixo do projeto."""
    daemon = _FetchDaemon()
    sandbox = make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache"))
    _run(sandbox, tmp_path, packages=["tabulate"], assets=[{"url": "https://e.org/p", "destino": "p.bin"}])

    assert daemon.calls.index("fetch") < daemon.calls.index("install")
    assert "def download(" in daemon.control_files["fetch_assets.py"]
    assert not any(path in ("/tmp", "/staging") for path, _data in daemon.put_archives)


@pytest.mark.unit
@pytest.mark.parametrize("asset", [
    {"url": "https://e.org/a", "destino": "../x"},
    {"url": "http://169.254.169.254/", "destino": "x"},
    {"url": "file:///etc/passwd", "destino": "x"},
])
def test_destino_ou_url_recusados_antes_de_containers(make_sandbox, tmp_path, asset):
    """Cenário: Destino ou URL recusados."""
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, assets=[asset])

    daemon.client.containers.run.assert_not_called()
    assert result.exit_code == -1 and "assets" in result.stderr


@pytest.mark.unit
def test_falha_de_download_e_fase_fetch_assets(make_sandbox, tmp_path):
    daemon = FakeDaemon(fetch_exit=1, fetch_output=b"erro p.bin: o servidor respondeu HTTP 404")
    result = _run(make_sandbox(daemon), tmp_path, assets=[{"url": "https://e.org/p", "destino": "p.bin"}])

    assert result.fase_falha == "fetch_assets" and "HTTP 404" in result.stderr
    assert "script" not in daemon.calls


# --- Requirement: Entrega de dados somente leitura na execução ----------------------------------

@pytest.mark.unit
def test_montagem_somente_leitura(make_sandbox, tmp_path, monkeypatch):
    """Cenário: Montagem somente leitura. input_snapshot em /inputs (ro); só /outputs é rw."""
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "mount")
    snap = _snapshot(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path)

    volumes = daemon.run_kwargs["volumes"]
    assert volumes[str(snap.resolve())] == {"bind": "/inputs", "mode": "ro"}
    assert [v["bind"] for v in volumes.values() if v["mode"] == "rw"] == ["/outputs"]
    assert result.modo_entrega == "mount" and result.entradas_entregues == ["dados.csv"]


@pytest.mark.unit
def test_entrega_por_copia(make_sandbox, tmp_path, monkeypatch):
    """Cenário: Entrega por cópia. /inputs vem por put_archive e o resultado traz modo_entrega="copy"."""
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    snap = _snapshot(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, memory_limit="1g"), tmp_path)

    assert result.modo_entrega == "copy"
    assert all(v["bind"] != "/inputs" for v in daemon.run_kwargs["volumes"].values())
    assert "/inputs" not in daemon.run_kwargs["tmpfs"]
    mount = next(m for m in daemon.run_kwargs["mounts"] if m["Target"] == "/inputs")
    assert mount["Type"] == "tmpfs"
    _path, data = next(a for a in daemon.put_archives if a[0] == "/inputs")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert tar.extractfile("dados.csv").read() == (snap / "dados.csv").read_bytes()


@pytest.mark.unit
def test_copia_acima_do_limite(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    monkeypatch.setenv("SANDBOX_COPY_MAX_BYTES", "4")
    _snapshot(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, memory_limit="1g"), tmp_path)

    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra" and "SANDBOX_INPUT_DELIVERY=mount" in result.stderr


@pytest.mark.unit
def test_modo_de_entrega_invalido_falha_explicitamente(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "nfs")
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path)

    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra" and "SANDBOX_INPUT_DELIVERY" in result.stderr


@pytest.mark.unit
def test_origem_de_montagem_fora_do_lugar(make_sandbox, tmp_path):
    """Cenário: Origem de montagem fora do lugar. Symlink para fora da sessão recusa antes do container."""
    snap = _snapshot(tmp_path)
    (tmp_path / "segredo.txt").write_text("x")
    (snap / "ataque").symlink_to(tmp_path / "segredo.txt")
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path)

    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra" and result.infra_error == "sandbox_mount_refused"
    assert "link simbólico" in result.stderr


@pytest.mark.unit
def test_sessoes_anteriores_montadas_somente_leitura(make_sandbox, tmp_path):
    prior = tmp_path / "out" / "s_antiga"
    prior.mkdir(parents=True)
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, prior_dirs=[prior])

    assert daemon.run_kwargs["volumes"][str(prior.resolve())] == {"bind": "/prior/s_antiga", "mode": "ro"}


@pytest.mark.unit
def test_sessao_anterior_fora_da_raiz_e_recusada(make_sandbox, tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, prior_dirs=[fora])

    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra"


# --- Requirement: Erro acionável para download não declarado ------------------------------------

class _FailingScript(FakeDaemon):
    def __init__(self, stderr: bytes, **kwargs):
        super().__init__(**kwargs)
        self._stderr = stderr

    def _exec_run(self, cmd, *args, **kwargs):
        if cmd[0] == "python" and "/outputs/script.py" in cmd:
            self.calls.append("script")
            return SimpleNamespace(exit_code=1, output=(b"", self._stderr))
        return super()._exec_run(cmd, *args, **kwargs)


@pytest.mark.unit
def test_download_dentro_do_script(make_sandbox, tmp_path):
    """Cenário: Download dentro do script."""
    daemon = _FailingScript(b"Traceback...\nurllib.error.URLError: <urlopen error [Errno -3] Temporary failure>\n")
    result = _run(make_sandbox(daemon), tmp_path)

    assert result.download_nao_declarado is True
    assert result.fase_falha == "execute"


@pytest.mark.unit
def test_falha_que_nao_e_de_rede(make_sandbox, tmp_path):
    """Cenário: Falha que não é de rede."""
    daemon = _FailingScript(b"Traceback (most recent call last):\nValueError: x\n")
    result = _run(make_sandbox(daemon), tmp_path)

    assert result.download_nao_declarado is False and result.exception_type == "ValueError"


@pytest.mark.unit
@pytest.mark.parametrize("signature", NETWORK_FAILURE_SIGNATURES)
def test_assinaturas_de_rede(signature):
    assert is_undeclared_download_failure(f"... {signature} ...") is True


@pytest.mark.unit
def test_assinatura_ausente():
    assert is_undeclared_download_failure("ZeroDivisionError: division by zero") is False
    assert is_undeclared_download_failure("") is False


# --- Requirement: Exceção de rede para entradas compartilháveis ---------------------------------

@pytest.mark.unit
def test_todas_as_entradas_compartilhaveis(make_sandbox, tmp_path, caplog):
    """Cenário: Todas as entradas compartilháveis."""
    _snapshot(tmp_path)
    daemon = FakeDaemon()
    sandbox = make_sandbox(daemon, input_classifier=ShareAll())
    with caplog.at_level(logging.WARNING):
        result = _run(sandbox, tmp_path, needs_network=True)

    assert daemon.run_kwargs["network_disabled"] is False
    assert result.rede_na_execucao is True and result.nota_rede is None
    assert any(r.levelno == logging.WARNING and "COM rede" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_uma_entrada_nao_compartilhavel(make_sandbox, tmp_path):
    """Cenário: Uma entrada não compartilhável."""
    _snapshot(tmp_path, {"a.csv": "1", "b.csv": "2"})

    class OnlyA:
        def network_allowed(self):
            return True

        def is_shareable(self, path):
            return path.name == "a.csv"

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=OnlyA()), tmp_path, needs_network=True)

    assert daemon.run_kwargs["network_disabled"] is True
    assert result.rede_na_execucao is False
    assert "não compartilháveis" in result.nota_rede
    assert "a.csv" not in result.nota_rede and "b.csv" not in result.nota_rede


@pytest.mark.unit
def test_classificador_padrao_nunca_libera_rede(make_sandbox, tmp_path):
    """Cenário: Classificador padrão."""
    _snapshot(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, needs_network=True)

    assert daemon.run_kwargs["network_disabled"] is True and result.rede_na_execucao is False


@pytest.mark.unit
def test_rede_exige_pedido_explicito(make_sandbox, tmp_path):
    _snapshot(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=ShareAll()), tmp_path)  # needs_network=False

    assert daemon.run_kwargs["network_disabled"] is True and result.rede_na_execucao is False


@pytest.mark.unit
def test_rede_negada_com_dados_produzidos_visiveis(make_sandbox, tmp_path):
    """Condição 3: artefato de execução anterior em /outputs ou saída anterior em /prior bloqueia a rede."""
    task = tmp_path / "out" / "s" / "t"
    task.mkdir(parents=True)
    (task / "resultado.csv").write_text("1")
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=ShareAll()), tmp_path, needs_network=True)
    assert result.rede_na_execucao is False and "dados produzidos" in result.nota_rede

    (task / "resultado.csv").unlink()
    prior = tmp_path / "out" / "antiga"
    prior.mkdir()
    result2 = _run(make_sandbox(FakeDaemon(), input_classifier=ShareAll()), tmp_path,
                   needs_network=True, prior_dirs=[prior])
    assert result2.rede_na_execucao is False and "/prior" in result2.nota_rede


@pytest.mark.unit
def test_arquivos_injetados_nao_contam_como_dados_produzidos(make_sandbox, tmp_path):
    task = tmp_path / "out" / "s" / "t"
    task.mkdir(parents=True)
    (task / "script.py").write_text("x")
    (task / "scientific_helpers.py").write_text("x")
    result = _run(make_sandbox(FakeDaemon(), input_classifier=ShareAll()), tmp_path, needs_network=True,
                  extra_files={"scientific_helpers.py": "x"})
    assert result.rede_na_execucao is True


# --- Requirement: Resultado estruturado do sandbox -------------------------------------------

@pytest.mark.unit
def test_execucao_com_pacote(make_sandbox, tmp_path):
    """Cenário: Execução com pacote."""
    daemon = FakeDaemon(listing=[{"name": "tabulate", "version": "0.9.0"}])
    result = _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    assert result.pacotes["tabulate"] == "0.9.0"
    assert result.pacotes_solicitados == ["tabulate"] and result.packages_installed == ["tabulate==0.9.0"]
    assert result.python_version == "3.11.9"
    assert result.imagem.id == "sha256:abc123" and result.imagem.repo_digests == ["code-sandbox@sha256:def456"]
    assert [f.nome for f in result.fases] == ["install", "execute"]
    assert all(f.inicio and f.fim for f in result.fases)
    assert [f.exit_code for f in result.fases] == [0, 0]
    assert result.fase_falha is None


@pytest.mark.unit
def test_daemon_indisponivel(make_sandbox, tmp_path):
    """Cenário: Daemon indisponível."""
    daemon = FakeDaemon()
    daemon.client.containers.run.side_effect = ConnectionError("socket")
    with patch("src.skills.code.sandbox.RETRY_BACKOFFS_SECONDS", (0.0,)), \
         patch("src.skills.code.sandbox.emit_connection_retry"):
        result = _run(make_sandbox(daemon), tmp_path)

    assert result.fase_falha == "infra" and result.infra_error == "docker_unavailable"


@pytest.mark.unit
def test_imagem_ausente_e_fase_infra(make_sandbox, tmp_path):
    daemon = FakeDaemon()
    daemon.client.images.get.side_effect = docker.errors.ImageNotFound("x")
    result = _run(make_sandbox(daemon), tmp_path)
    assert result.fase_falha == "infra" and result.infra_error == "sandbox_image_missing"


@pytest.mark.unit
def test_falha_do_script_e_fase_execute(make_sandbox, tmp_path):
    daemon = _FailingScript(b"Traceback (most recent call last):\nValueError: x\n")
    result = _run(make_sandbox(daemon), tmp_path)
    assert result.fase_falha == "execute" and result.fases[-1].exit_code == 1


# --- limpeza e fronteira de rede -----------------------------------------------------------------

@pytest.mark.unit
def test_diretorio_de_trabalho_removido_em_qualquer_desfecho(make_sandbox, tmp_path):
    for daemon in (FakeDaemon(), FakeDaemon(install_exit=1), _FetchDaemon(content=b"x")):
        sandbox = make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache"))
        _run(sandbox, tmp_path, packages=["tabulate"],
             assets=[{"url": "https://e.org/p", "destino": "p", "sha256": SHA_A}])
        assert list(sandbox.work_dir.iterdir()) == []


@pytest.mark.unit
def test_sandbox_nao_usa_mais_desconexao_de_rede():
    """A rede do script é decidida na criação do container (fail-closed), não por disconnect em container único."""
    source = (Path(__file__).parents[3] / "src" / "skills" / "code" / "sandbox.py").read_text(encoding="utf-8")
    assert "disconnect" not in source
