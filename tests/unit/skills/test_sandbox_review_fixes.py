# ruff: noqa: F811 — a fixture make_sandbox é reexportada e usada como argumento
"""Achados da revisão de segurança do PR #111 (v18.5-sandbox-phases): um grupo de testes por achado."""

import pytest
from test_sandbox_phases import _FetchDaemon
from test_sandbox_slim import FakeDaemon, _run, make_sandbox  # noqa: F401 — fixture reexportada


# --- A1: a rede exige autorização explícita do classificador ---------------------------------------

@pytest.mark.unit
def test_a1_sem_insumos_e_classificador_padrao_nao_libera_rede(make_sandbox, tmp_path):
    """Sem insumos, ``all([])`` não pode liberar a rede: o classificador padrão não autoriza nada."""
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, needs_network=True)

    assert daemon.run_kwargs["network_disabled"] is True
    assert result.rede_na_execucao is False
    assert "classificador" in result.nota_rede


@pytest.mark.unit
def test_a1_classificador_sem_autorizacao_explicita_nega_antes_de_outras_regras(make_sandbox, tmp_path):
    """Um classificador que só implementa ``is_shareable`` (sem ``network_allowed``) é fail-closed."""

    class SoShareable:
        def is_shareable(self, path):
            return True

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=SoShareable()), tmp_path, needs_network=True)

    assert result.rede_na_execucao is False and "classificador" in result.nota_rede


@pytest.mark.unit
def test_a1_classificador_que_autoriza_sem_insumos_libera_a_rede(make_sandbox, tmp_path):
    class Autoriza:
        def network_allowed(self):
            return True

        def is_shareable(self, path):
            return True

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=Autoriza()), tmp_path, needs_network=True)

    assert result.rede_na_execucao is True


# --- A2: put_archive só em pontos de montagem (raiz somente leitura) ----------------------------------

@pytest.mark.unit
def test_a2_copy_usa_mount_tmpfs_com_tamanho_e_modo(make_sandbox, tmp_path, monkeypatch):
    """/inputs em modo copy é um ``Mount`` tmpfs (aceita put_archive com a raiz ro), não HostConfig.Tmpfs."""
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    monkeypatch.setenv("SANDBOX_COPY_MAX_BYTES", "1048576")
    snap = tmp_path / "out" / "s" / "input_snapshot"
    snap.mkdir(parents=True)
    (snap / "dados.csv").write_text("a,b\n")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)

    mount = next(m for m in daemon.run_kwargs["mounts"] if m["Target"] == "/inputs")
    assert mount["Type"] == "tmpfs"
    assert mount["TmpfsOptions"] == {"SizeBytes": 1048576, "Mode": 0o555}
    assert "/inputs" not in daemon.run_kwargs["tmpfs"]
    assert any(path == "/inputs" for path, _data in daemon.put_archives)


@pytest.mark.unit
def test_a2_fetch_usa_diretorio_de_controle_ro_e_nao_put_archive(make_sandbox, tmp_path):
    """Script e spec do fetch vão no diretório /control (ro), escrito no host antes de criar o container."""
    daemon = _FetchDaemon()
    _run(make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache")), tmp_path,
         assets=[{"url": "https://e.org/p", "destino": "p.bin"}])

    control = [v for v in daemon.prep_kwargs["volumes"].values() if v["bind"] == "/control"]
    assert control == [{"bind": "/control", "mode": "ro"}]
    assert set(daemon.control_files) == {"fetch_assets.py", "fetch_spec.json"}
    assert "https://e.org/p" in daemon.control_files["fetch_spec.json"]
    assert [path for path, _data in daemon.put_archives] == ["/outputs"]  # só o script, em ponto de montagem
    fetch_cmd = next(c for c, _kw in daemon.exec_calls if c[0] == "python" and "fetch" in c[1])
    assert fetch_cmd == ["python", "/control/fetch_assets.py", "/control/fetch_spec.json"]
