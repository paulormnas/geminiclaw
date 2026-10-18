# ruff: noqa: F811 — a fixture make_sandbox é reexportada e usada como argumento
"""Saídas das dependências no sandbox (v18.7-dependency-artifacts, capacidade code-sandbox), com o daemon simulado."""

from pathlib import Path

import pytest
from test_sandbox_phases import ShareAll
from test_sandbox_slim import FakeDaemon, _run, make_sandbox  # noqa: F401 — fixture reexportada

from src.utils.agent_context import DependencyMount

pytestmark = pytest.mark.unit


def _dep(tmp_path: Path, name: str = "dividir_dados", session: str = "s", files=("y_train.csv",)) -> DependencyMount:
    folder = tmp_path / "out" / session / name
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        (folder / f).write_text("a\n1\n", encoding="utf-8")
    return DependencyMount(name, folder, session)


def test_leitura_da_dependencia_somente_leitura(make_sandbox, tmp_path):
    """Scenarios: Leitura da dependência e Escrita recusada (montagem ``ro``)."""
    mount = _dep(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, dependency_mounts=[mount], project_id="proj1")

    volumes = daemon.run_kwargs["volumes"]
    assert volumes[str(mount.source.resolve())] == {"bind": "/deps_out/proj1/dividir_dados", "mode": "ro"}
    assert volumes[str((tmp_path / "out" / "s" / "t").resolve())]["mode"] == "rw"  # só /outputs é gravável
    assert result.dependencias_montadas == ["dividir_dados"]


def test_sem_projeto_usa_o_diretorio_padrao(make_sandbox, tmp_path):
    mount = _dep(tmp_path)
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, dependency_mounts=[mount])
    assert daemon.run_kwargs["volumes"][str(mount.source.resolve())]["bind"] == "/deps_out/sem_projeto/dividir_dados"


def test_varias_dependencias(make_sandbox, tmp_path):
    mounts = [_dep(tmp_path, "treinar"), _dep(tmp_path, "dividir_dados")]
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, dependency_mounts=mounts, project_id="p")
    binds = {v["bind"] for v in daemon.run_kwargs["volumes"].values()}
    assert {"/deps_out/p/treinar", "/deps_out/p/dividir_dados"} <= binds
    assert result.dependencias_montadas == ["treinar", "dividir_dados"]


def test_sem_dependencias_nada_e_montado(make_sandbox, tmp_path):
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path)
    assert not any(v["bind"].startswith("/deps_out") for v in daemon.run_kwargs["volumes"].values())
    assert result.dependencias_montadas == []


def test_propria_subtarefa_e_recusada(make_sandbox, tmp_path):
    """Scenario: Própria subtarefa."""
    mount = _dep(tmp_path, "t")  # a subtarefa em execução chama-se "t"
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, dependency_mounts=[mount])
    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra" and result.infra_error == "sandbox_mount_refused"


@pytest.mark.parametrize("where", ["raiz", "sessao", "symlink", "dentro_link", "fora"])
def test_pasta_fora_do_lugar_e_recusada(make_sandbox, tmp_path, where):
    """Scenario: Pasta fora da sessão."""
    out = tmp_path / "out"
    real = _dep(tmp_path)
    if where == "raiz":
        mount = DependencyMount("dividir_dados", out, "s")
    elif where == "sessao":
        mount = DependencyMount("dividir_dados", out / "s", "s")
    elif where == "symlink":
        link = out / "s" / "atalho"
        link.symlink_to(real.source)
        mount = DependencyMount("atalho", link, "s")
    elif where == "dentro_link":
        (real.source / "ataque").symlink_to(tmp_path / "out")
        mount = real
    else:
        fora = tmp_path / "fora" / "s" / "dividir_dados"
        fora.mkdir(parents=True)
        mount = DependencyMount("dividir_dados", fora, "s")
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, dependency_mounts=[mount])
    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra"


def test_sessao_fora_da_cadeia_e_recusada(make_sandbox, tmp_path):
    """Scenario: Sessão fora da cadeia."""
    mount = _dep(tmp_path, session="outra")
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, dependency_mounts=[mount])
    daemon.client.containers.run.assert_not_called()
    assert result.infra_error == "sandbox_mount_refused" and "cadeia de continuidade" in result.stderr


def test_dependencia_da_sessao_anterior_da_cadeia(make_sandbox, tmp_path):
    """Scenario: Dependência da sessão anterior."""
    prior = tmp_path / "out" / "s_antiga"
    mount = _dep(tmp_path, session="s_antiga")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path, prior_dirs=[prior], dependency_mounts=[mount], project_id="p")
    volumes = daemon.run_kwargs["volumes"]
    assert volumes[str(mount.source.resolve())]["bind"] == "/deps_out/p/dividir_dados"
    assert volumes[str(prior.resolve())]["bind"] == "/prior/s_antiga"


def test_sessao_declarada_diferente_da_pasta_e_recusada(make_sandbox, tmp_path):
    real = _dep(tmp_path)
    mount = DependencyMount(real.task_name, real.source, "s_antiga")
    result = _run(make_sandbox(FakeDaemon()), tmp_path, dependency_mounts=[mount])
    assert result.fase_falha == "infra"


def test_teto_de_montagens_recusa_sem_montar_parte(make_sandbox, tmp_path, monkeypatch):
    """Scenario: Teto de montagens."""
    monkeypatch.setattr("src.config.DEPENDENCY_ARTIFACTS_MAX_MOUNTS", 16)
    mounts = [_dep(tmp_path, f"d{i}") for i in range(17)]
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, dependency_mounts=mounts)
    daemon.client.containers.run.assert_not_called()
    assert result.infra_error == "sandbox_mount_refused" and "DEPENDENCY_ARTIFACTS_MAX_MOUNTS=16" in result.stderr


def test_dependencia_repetida_e_recusada(make_sandbox, tmp_path):
    mount = _dep(tmp_path)
    result = _run(make_sandbox(FakeDaemon()), tmp_path, dependency_mounts=[mount, mount])
    assert result.fase_falha == "infra"


def test_identificador_de_projeto_inseguro_e_recusado(make_sandbox, tmp_path):
    mount = _dep(tmp_path)
    result = _run(make_sandbox(FakeDaemon()), tmp_path, dependency_mounts=[mount], project_id="../x")
    assert result.fase_falha == "infra"


def test_sem_rede_com_dependencia_montada(make_sandbox, tmp_path):
    """Scenario: Sem rede com dependência (mesmo com todas as entradas compartilháveis)."""
    mount = _dep(tmp_path)
    folder = tmp_path / "out" / "s" / "t"
    folder.mkdir(parents=True, exist_ok=True)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=ShareAll()), tmp_path, needs_network=True,
                  dependency_mounts=[mount])
    assert daemon.run_kwargs["network_disabled"] is True and result.rede_na_execucao is False
    assert "/deps_out" in result.nota_rede


def test_rede_continua_possivel_sem_dependencia(make_sandbox, tmp_path):
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=ShareAll()), tmp_path, needs_network=True)
    assert result.rede_na_execucao is True
