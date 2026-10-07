"""Specs das mudanças v16-sandbox-slim-image e v18.5-sandbox-phases (capacidade code-sandbox), com o cliente simulado.

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

    def __init__(self, install_exit=0, install_output=b"", listing=None, fetch_exit=0, fetch_output=b"",
                 python="3.11.9 (main, Jan 1 2026)"):
        self.calls: list[str] = []
        self.exec_calls: list[tuple] = []
        self.run_calls: list[dict] = []
        self.put_archives: list[tuple] = []
        # Conteúdo do diretório de controle (/control) no momento da criação do container de preparação:
        # o diretório de trabalho do run é removido ao fim.
        self.control_files: dict[str, str] = {}
        self.client = MagicMock()
        self.container = MagicMock()
        self._install_exit = install_exit
        self._install_output = install_output
        self._fetch_exit = fetch_exit
        self._fetch_output = fetch_output
        self._listing = listing if listing is not None else []
        self._python = python
        self.container.exec_run.side_effect = self._exec_run
        self.container.put_archive.side_effect = self._put_archive
        self.container.kill.side_effect = lambda *a, **k: self.calls.append("kill")
        self.container.remove.side_effect = lambda *a, **k: self.calls.append("remove")
        self.client.containers.run.side_effect = self._containers_run
        image = MagicMock()
        image.id = "sha256:abc123"
        image.attrs = {"RepoDigests": ["code-sandbox@sha256:def456"]}
        self.client.images.get.return_value = image

    def _containers_run(self, **kwargs):
        self.run_calls.append(kwargs)
        for host, vol in (kwargs.get("volumes") or {}).items():
            if vol["bind"] == "/control":
                assert vol["mode"] == "ro"
                self.control_files = {f.name: f.read_text() for f in Path(host).iterdir()}
        self.calls.append(f"run:{kwargs['labels']['geminiclaw.role']}")
        return self.container

    def _put_archive(self, path, data):
        self.calls.append("put_archive")
        self.put_archives.append((path, data))

    def _exec_run(self, cmd, *args, **kwargs):
        self.exec_calls.append((cmd, kwargs))
        if cmd[0] == "uv":
            self.calls.append("install")
            return SimpleNamespace(exit_code=self._install_exit, output=self._install_output)
        if cmd[0] == "python" and cmd[1] == "/control/fetch_assets.py":
            self.calls.append("fetch")
            return SimpleNamespace(exit_code=self._fetch_exit, output=self._fetch_output)
        if cmd[0] == SANDBOX_VENV_PYTHON:
            self.calls.append("introspect")
            deps = [[d["name"], d["version"]] for d in self._listing]
            payload = {"python": self._python, "all": [["numpy", "1.26.0"], *deps], "deps": deps}
            return SimpleNamespace(exit_code=0, output=json.dumps(payload).encode())
        self.calls.append("script")
        return SimpleNamespace(exit_code=0, output=(b"ok", b""))

    @property
    def run_kwargs(self) -> dict:
        """Argumentos do container de execução (o último criado)."""
        return self.run_calls[-1]

    @property
    def prep_kwargs(self) -> dict:
        """Argumentos do container de preparação (o primeiro, quando há preparação)."""
        return self.run_calls[0]


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
    assert kwargs["tmpfs"] == {"/tmp": "size=256m,noexec,nosuid,nodev"}
    assert kwargs["memswap_limit"] == kwargs["mem_limit"]
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
    assert cmd == [
        "uv", "pip", "install", "--no-config", "--only-binary", ":all:",
        "--python", SANDBOX_VENV_PYTHON, "--target", "/deps", "tabulate==0.9.0",
    ]
    prep_volumes = daemon.prep_kwargs["volumes"]
    assert any(v == {"bind": "/deps", "mode": "rw"} for v in prep_volumes.values())
    assert daemon.prep_kwargs["network_disabled"] is False
    assert any(v == {"bind": "/deps", "mode": "ro"} for v in daemon.run_kwargs["volumes"].values())


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


# --- Correções da revisão de segurança (PR #99) ----------------------------------------------

@pytest.mark.unit
def test_gitignore_mantem_pem_e_sandbox_work():
    """B1: `*.pem` e `store/sandbox_work/` são linhas separadas do .gitignore."""
    lines = (Path(__file__).parents[3] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.pem" in lines
    assert "store/sandbox_work/" in lines


@pytest.mark.unit
def test_introspeccao_e_isolada(make_sandbox, tmp_path):
    """I1: a introspecção roda no container de execução (sem preparação), com `-I` e workdir /tmp."""
    daemon = FakeDaemon(listing=[{"name": "tabulate", "version": "0.9.0"}])
    _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    cmd, kwargs = next((c, k) for c, k in daemon.exec_calls if c[0] == SANDBOX_VENV_PYTHON)
    assert cmd[1] == "-I"
    assert kwargs["workdir"] == "/tmp"
    assert daemon.calls.index("run:sandbox") < daemon.calls.index("introspect")


@pytest.mark.unit
def test_instalacao_sem_config_do_uv_e_em_tmp(make_sandbox, tmp_path):
    """I2/I3: `--no-config`, `UV_NO_CONFIG=1`, workdir /tmp (não /outputs) e só wheels."""
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    cmd, kwargs = next((c, k) for c, k in daemon.exec_calls if c[0] == "uv")
    assert "--no-config" in cmd
    assert cmd[cmd.index("--only-binary") + 1] == ":all:"
    assert kwargs["workdir"] == "/tmp"
    assert kwargs["environment"]["UV_NO_CONFIG"] == "1"


@pytest.mark.unit
def test_falha_de_instalacao_explica_exigencia_de_wheel(make_sandbox, tmp_path):
    """I3: pacote sem wheel falha de forma explícita e acionável."""
    daemon = FakeDaemon(install_exit=1, install_output=b"error: no wheels")
    result = _run(make_sandbox(daemon), tmp_path, packages=["so-sdist"])

    assert result.install_failed is True
    assert "wheel" in result.stderr and "--only-binary" in result.stderr


@pytest.mark.unit
def test_script_injetado_depois_da_preparacao(make_sandbox, tmp_path):
    """I4: o script só entra depois da instalação, já no container de execução; instalação falha => nada entra."""
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])
    assert daemon.calls.index("install") < daemon.calls.index("run:sandbox") < daemon.calls.index("put_archive")
    assert daemon.calls.index("put_archive") < daemon.calls.index("script")

    falha = FakeDaemon(install_exit=1)
    _run(make_sandbox(falha), tmp_path, packages=["tabulate"])
    assert "put_archive" not in falha.calls


@pytest.mark.unit
def test_uid_zero_e_recusado(make_sandbox, tmp_path):
    """I5: orquestrador como root => erro explícito, nenhum container."""
    daemon = FakeDaemon()
    with patch("src.skills.code.sandbox.os.getuid", return_value=0):
        result = _run(make_sandbox(daemon), tmp_path)

    assert result.exit_code == -1
    assert "root" in result.stderr
    daemon.client.containers.run.assert_not_called()


@pytest.mark.unit
def test_container_encerrado_antes_da_varredura(make_sandbox, tmp_path):
    """I6: kill antes da varredura de links e de arquivos especiais."""
    daemon = FakeDaemon()
    ordem: list[str] = []
    daemon.container.kill.side_effect = lambda *a, **k: ordem.append("kill")
    with patch(
        "src.skills.code.sandbox._purge_escaping_symlinks", side_effect=lambda *a: ordem.append("purge") or []
    ):
        _run(make_sandbox(daemon), tmp_path)

    assert ordem.index("kill") < ordem.index("purge")


@pytest.mark.unit
@pytest.mark.parametrize("name", ["../x", "a/b", "..", "", "x..y", "a b", ".."])
@pytest.mark.parametrize("campo", ["task_name", "session_id"])
def test_nomes_de_pasta_invalidos(make_sandbox, tmp_path, name, campo):
    """I7: session_id e task_name com padrão restrito; nenhum container para nome inválido."""
    daemon = FakeDaemon()
    ids = {"session_id": "s", "task_name": "t", campo: name}
    result = make_sandbox(daemon).run(code="pass", output_dir=str(tmp_path / "out"), **ids)

    assert result.exit_code == -1
    assert "Nome inválido" in result.stderr
    daemon.client.containers.run.assert_not_called()


@pytest.mark.unit
def test_pasta_fora_do_diretorio_de_saida_e_recusada(make_sandbox, tmp_path):
    """I7: um symlink na sessão que aponta para fora do diretório de saída é recusado."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "s").symlink_to(tmp_path)  # sessão -> fora de `out`
    daemon = FakeDaemon()
    result = make_sandbox(daemon).run(code="pass", session_id="s", task_name="t", output_dir=str(out))

    assert result.exit_code == -1
    daemon.client.containers.run.assert_not_called()


@pytest.mark.unit
def test_limites_da_lista_de_pacotes():
    """S6: quantidade e tamanho dos requisitos são limitados."""
    assert prepare_packages([f"pkg{i}" for i in range(21)])[0] == []
    assert prepare_packages(["a" * 201])[1]
    assert prepare_packages([f"pkg{i}" for i in range(20)])[1] == []


@pytest.mark.unit
def test_varredura_remove_fifo_e_preserva_arquivos(tmp_path):
    """S7: FIFOs em /outputs são removidos; arquivos regulares, diretórios e links ficam."""
    from src.skills.code.sandbox import _purge_special_files

    (tmp_path / "sub").mkdir()
    (tmp_path / "ok.txt").write_text("x")
    os.mkfifo(tmp_path / "sub" / "pipe")
    (tmp_path / "link").symlink_to(tmp_path / "ok.txt")

    removed = _purge_special_files(tmp_path)

    assert removed == [os.path.join("sub", "pipe")]
    assert (tmp_path / "ok.txt").exists() and (tmp_path / "link").is_symlink()
