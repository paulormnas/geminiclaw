"""Specs da mudança v16-sandbox-slim-image (capacidade code-sandbox), com o cliente do daemon simulado.

Nenhum teste constrói imagem nem cria container de verdade. Os cenários que dependem da imagem
real (conteúdo, escrita fora das áreas permitidas, dono dos artefatos, socket sem rede) ficam em
``tests/integration/test_sandbox_slim_image.py``.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import docker.errors
import pytest

from src.skills.code.sandbox import SANDBOX_VENV_PYTHON, PythonSandbox, prepare_packages


class FakeDaemon:
    """Cliente do daemon simulado que registra a ordem das chamadas relevantes."""

    def __init__(self, networks=("bridge",), install_exit=0, install_output=b"", listing=None,
                 disconnect_error=None):
        self.calls: list[str] = []
        self.exec_calls: list[tuple] = []
        self.client = MagicMock()
        self.container = MagicMock()
        self._networks = {name: {} for name in networks}
        self.container.attrs = {"NetworkSettings": {"Networks": self._networks}}
        self._install_exit = install_exit
        self._install_output = install_output
        self._listing = listing if listing is not None else []
        self._disconnect_error = disconnect_error
        self.container.exec_run.side_effect = self._exec_run
        self.client.containers.run.return_value = self.container
        self.client.networks.get.side_effect = self._get_network

    def _get_network(self, name):
        network = MagicMock()

        def disconnect(container):
            if self._disconnect_error:
                raise self._disconnect_error
            self.calls.append(f"disconnect:{name}")
            self._networks.pop(name, None)

        network.disconnect.side_effect = disconnect
        return network

    def _exec_run(self, cmd, *args, **kwargs):
        self.exec_calls.append((cmd, kwargs))
        if cmd[0] == "uv":
            self.calls.append("install")
            return SimpleNamespace(exit_code=self._install_exit, output=self._install_output)
        if cmd[0] == SANDBOX_VENV_PYTHON:
            return SimpleNamespace(exit_code=0, output=json.dumps(self._listing).encode())
        self.calls.append("script")
        return SimpleNamespace(exit_code=0, output=(b"ok", b""))

    @property
    def run_kwargs(self) -> dict:
        return self.client.containers.run.call_args.kwargs


@pytest.fixture
def make_sandbox(tmp_path: Path):
    """Cria um ``PythonSandbox`` ligado a um ``FakeDaemon``; o patch dura o teste todo."""
    with patch("src.skills.code.sandbox.docker.from_env") as from_env:
        def factory(daemon: FakeDaemon, **kwargs) -> PythonSandbox:
            from_env.return_value = daemon.client
            kwargs.setdefault("work_dir", str(tmp_path / "work"))
            return PythonSandbox(**kwargs)

        yield factory


def _run(sandbox: PythonSandbox, tmp_path: Path, **kwargs):
    return sandbox.run(code="print('ok')", session_id="s", task_name="t", output_dir=str(tmp_path / "out"), **kwargs)


# --- Requirement: Imagem mínima do sandbox ---------------------------------------------------

@pytest.mark.unit
def test_imagem_configuravel(make_sandbox, tmp_path, monkeypatch):
    """Cenário: Imagem configurável (SANDBOX_IMAGE=meu-sandbox:1)."""
    monkeypatch.setenv("SANDBOX_IMAGE", "meu-sandbox:1")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)
    assert daemon.run_kwargs["image"] == "meu-sandbox:1"
    daemon.client.images.get.assert_called_with("meu-sandbox:1")


@pytest.mark.unit
def test_imagem_padrao_e_code_sandbox_latest(make_sandbox, monkeypatch):
    monkeypatch.delenv("SANDBOX_IMAGE", raising=False)
    assert make_sandbox(FakeDaemon()).image == "code-sandbox:latest"


@pytest.mark.unit
def test_imagem_ausente(make_sandbox, tmp_path):
    """Cenário: Imagem ausente. Erro acionável e nenhum pull."""
    daemon = FakeDaemon()
    daemon.client.images.get.side_effect = docker.errors.ImageNotFound("sem imagem")
    result = _run(make_sandbox(daemon), tmp_path)

    assert result.exit_code == -1
    assert "code-sandbox:latest" in result.stderr
    assert "scripts/build_images.sh" in result.stderr
    daemon.client.images.pull.assert_not_called()
    daemon.client.containers.run.assert_not_called()


# --- Requirement: Container sem privilégios --------------------------------------------------

@pytest.mark.unit
def test_parametros_de_criacao(make_sandbox, tmp_path, monkeypatch):
    """Cenário: Parâmetros de criação."""
    monkeypatch.setenv("SANDBOX_PIDS_LIMIT", "99")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)

    kwargs = daemon.run_kwargs
    assert kwargs["user"] == f"{os.getuid()}:{os.getgid()}"
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert kwargs["read_only"] is True
    assert kwargs["pids_limit"] == 99
    assert kwargs["tmpfs"] == {"/tmp": "size=256m"}
    assert kwargs["network_disabled"] is True
    assert kwargs["environment"]["HOME"] == "/tmp"


@pytest.mark.unit
def test_nenhum_root(make_sandbox, tmp_path):
    """Cenário: Nenhum root (script com packages)."""
    daemon = FakeDaemon(listing=[{"name": "tabulate", "version": "0.9.0"}])
    _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    assert daemon.exec_calls
    for _cmd, kwargs in daemon.exec_calls:
        assert kwargs.get("user") != "root"
        assert "user" not in kwargs


@pytest.mark.unit
def test_modulo_sem_exec_como_root():
    """Cenário: Nenhum root. Nenhuma chamada como root sobra no módulo do sandbox."""
    source = (Path(__file__).parents[3] / "src" / "skills" / "code" / "sandbox.py").read_text(encoding="utf-8")
    assert "user='root'" not in source and 'user="root"' not in source
    assert "chown" not in source and "0o777" not in source and "0o666" not in source


# --- Requirement: Pacotes sob demanda sem root e com falha explícita -------------------------

@pytest.mark.unit
def test_pacote_inexistente(make_sandbox, tmp_path):
    """Cenário: Pacote inexistente. O script não roda e o log do uv volta no stderr."""
    log = "\n".join(f"linha {i}" for i in range(100)) + "\nerror: No solution found: pacote-que-nao-existe-123"
    daemon = FakeDaemon(install_exit=1, install_output=log.encode())
    result = _run(make_sandbox(daemon), tmp_path, packages=["pacote-que-nao-existe-123"])

    assert result.install_failed is True
    assert "script" not in daemon.calls
    assert "pacote-que-nao-existe-123" in result.stderr
    assert "No solution found" in result.stderr
    assert "linha 0" not in result.stderr  # só o final do log (SANDBOX_INSTALL_LOG_TAIL_LINES=40)
    daemon.container.remove.assert_called()


@pytest.mark.unit
def test_comando_de_instalacao_fixo(make_sandbox, tmp_path):
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, packages=["tabulate==0.9.0"])

    cmd = next(c for c, _ in daemon.exec_calls if c[0] == "uv")
    assert cmd == ["uv", "pip", "install", "--python", SANDBOX_VENV_PYTHON, "--target", "/deps", "tabulate==0.9.0"]
    volumes = daemon.run_kwargs["volumes"]
    assert any(v["bind"] == "/deps" for v in volumes.values())
    assert daemon.run_kwargs["network_disabled"] is False


@pytest.mark.unit
def test_requisito_invalido(make_sandbox, tmp_path):
    """Cenário: Requisito inválido. Nenhum container é criado e o erro cita os dois itens."""
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, packages=["--index-url=http://x", "pkg @ https://x/y.whl"])

    daemon.client.containers.run.assert_not_called()
    assert result.exit_code == -1
    assert "--index-url=http://x" in result.stderr
    assert "pkg @ https://x/y.whl" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    "item", ["./pasta", "/etc/passwd", "pkg; python_version<'3'", "pkg[extra] @ git+https://x/y", "", "-r req.txt"]
)
def test_requisitos_invalidos_adicionais(item):
    to_install, invalid = prepare_packages([item])
    assert to_install == []
    assert len(invalid) == 1


@pytest.mark.unit
def test_pacote_do_conjunto_basico(make_sandbox, tmp_path):
    """Cenário: Pacote do conjunto básico. Sem instalação e com o container sem rede."""
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, packages=["numpy", "os"])

    assert "install" not in daemon.calls
    assert daemon.run_kwargs["network_disabled"] is True
    assert "disconnect:bridge" not in daemon.calls
    assert all(v["bind"] != "/deps" for v in daemon.run_kwargs["volumes"].values())


@pytest.mark.unit
def test_conjunto_basico_com_versao_e_instalado():
    to_install, invalid = prepare_packages(["numpy==1.26.0", "Scikit_Learn", "pandas>=2", "tabulate", "tabulate"])
    assert invalid == []
    assert to_install == ["numpy==1.26.0", "pandas>=2", "tabulate"]


@pytest.mark.unit
def test_pacotes_registrados(make_sandbox, tmp_path):
    """Cenário: Pacotes registrados, e o diretório de trabalho da execução é removido."""
    daemon = FakeDaemon(listing=[{"name": "tabulate", "version": "0.9.0"}])
    sandbox = make_sandbox(daemon)
    result = _run(sandbox, tmp_path, packages=["tabulate"])

    assert result.packages_installed == ["tabulate==0.9.0"]
    assert result.install_failed is False
    assert result.exit_code == 0
    assert list(sandbox.work_dir.iterdir()) == []  # SANDBOX_WORK_DIR/<run_id> removido


@pytest.mark.unit
def test_diretorio_de_trabalho_removido_na_falha(make_sandbox, tmp_path):
    daemon = FakeDaemon(install_exit=1)
    sandbox = make_sandbox(daemon)
    _run(sandbox, tmp_path, packages=["tabulate"])
    assert list(sandbox.work_dir.iterdir()) == []


# --- Requirement: Script sem rede depois da instalação --------------------------------------

@pytest.mark.unit
def test_desconexao_antes_do_script(make_sandbox, tmp_path):
    """Cenário: Desconexão antes do script. Cada rede é desconectada depois da instalação."""
    daemon = FakeDaemon(networks=("bridge", "outra"))
    result = _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    assert result.exit_code == 0
    assert daemon.calls.index("install") < daemon.calls.index("disconnect:bridge") < daemon.calls.index("script")
    assert daemon.calls.index("disconnect:outra") < daemon.calls.index("script")


@pytest.mark.unit
def test_desconexao_falha(make_sandbox, tmp_path):
    """Cenário: Desconexão falha. O script não roda (fail-closed) e o erro cita a desconexão."""
    daemon = FakeDaemon(disconnect_error=docker.errors.APIError("boom"))
    result = _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    assert "script" not in daemon.calls
    assert result.exit_code == -1
    assert "desconexão de rede" in result.stderr
    daemon.container.remove.assert_called()


@pytest.mark.unit
def test_desconexao_nao_confirmada(make_sandbox, tmp_path):
    """Se o container continua em alguma rede depois do disconnect, a execução é abortada."""
    daemon = FakeDaemon()
    daemon.client.networks.get.side_effect = lambda name: MagicMock()  # disconnect não faz nada

    result = _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    assert "script" not in daemon.calls
    assert "desconexão de rede" in result.stderr


# --- Requirement: Saída por bind mount restrito à subtarefa ---------------------------------

@pytest.mark.unit
def test_sem_copia_duplicada(make_sandbox, tmp_path):
    """Cenário: Sem cópia duplicada. get_archive não é chamado."""
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)
    daemon.container.get_archive.assert_not_called()


@pytest.mark.unit
def test_variavel_ignorada(make_sandbox, tmp_path, monkeypatch):
    """Cenário: Variável ignorada (HOST_PROJECT_PATH). A origem do bind mount é o caminho real."""
    monkeypatch.setenv("HOST_PROJECT_PATH", "/qualquer")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)

    expected = str((tmp_path / "out" / "s" / "t").resolve())
    assert list(daemon.run_kwargs["volumes"]) == [expected]
    assert "HOST_PROJECT_PATH" not in (Path(__file__).parents[3] / "src" / "skills" / "code" / "sandbox.py").read_text()
