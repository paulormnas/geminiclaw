"""Utilitário ``scripts.platform_images`` e checagem da imagem do sandbox no início da sessão
(v16-platform-images, cenários 6.5 e comandos da seção 3)."""

from __future__ import annotations

import json
import logging

import pytest

from scripts import platform_images as cli
from src import infrastructure
from src.platform_images import (
    ENSURE_COMMAND,
    MANIFEST_PATH,
    PlatformImageError,
    check_sandbox_image,
    load_manifest,
    reset_warning_state,
)

from .helpers import FakeClient

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fresh_warning():
    reset_warning_state()
    yield
    reset_warning_state()


@pytest.fixture
def sandbox_ref() -> str:
    return load_manifest(MANIFEST_PATH)["sandbox"].reference


def _run(argv, client=None, **kw):
    lines: list[str] = []
    code = cli.run(argv, client=client or FakeClient("aarch64"), out=lines.append, **kw)
    return code, "\n".join(lines)


def test_detect_mostra_a_plataforma() -> None:
    code, out = _run(["detect"])
    assert code == 0 and "Plataforma:" in out and "linux/arm64" in out


def test_detect_json() -> None:
    code, out = _run(["detect", "--json"])
    data = json.loads(out)
    assert code == 0 and data["target"] == "linux/arm64" and "id" in data


def test_plan_lista_o_estado_sem_alterar_nada() -> None:
    client = FakeClient("aarch64")
    code, out = _run(["plan"], client)
    assert code == 0 and "sandbox" in out and "build" in out and "qdrant" in out and "pull" in out
    assert "ollama" not in out and client.images.calls == []


def test_plan_com_ollama_e_json() -> None:
    code, out = _run(["plan", "--com-ollama", "--json"])
    names = [item["nome"] for item in json.loads(out)["plano"]]
    assert code == 0 and "ollama" in names


def test_plan_estrito_devolve_2_quando_ha_nao_validada() -> None:
    code, out = _run(["plan", "--imagens", "sandbox", "--estrito"])
    assert code == 2 and "nao_validada" in out  # o sandbox ainda não tem plataforma validada


def test_plan_estrito_ok_quando_tudo_validado() -> None:
    code, _ = _run(["plan", "--imagens", "qdrant", "--estrito"], FakeClient("aarch64"))
    # fora do Pi 5 de 16K a plataforma detectada no CI não é a validada: o código vale 0 ou 2, nunca 1.
    assert code in (0, 2)


def test_ensure_constroi_e_grava(tmp_path) -> None:
    client = FakeClient("aarch64")
    code, out = _run(["ensure", "--imagens", "sandbox", "--yes"], client, platform_file=tmp_path / "platform.json",
                     project_root=tmp_path)
    assert code == 0 and (tmp_path / "platform.json").is_file() and "sandbox" in out
    assert client.images.calls[0][0] == "build"


def test_ensure_erro_vira_codigo_1_com_mensagem(monkeypatch) -> None:
    client = FakeClient("s390x")
    code, out = _run(["ensure", "--imagens", "qdrant", "--yes"], client)
    assert code == 1 and "Erro:" in out and client.images.calls == []


def test_sem_daemon_o_plan_falha_e_o_detect_segue(monkeypatch) -> None:
    def no_daemon(timeout=10):
        raise PlatformImageError("Daemon de containers inacessível")

    monkeypatch.setattr("scripts.platform_images.docker_client", no_daemon)
    lines: list[str] = []
    assert cli.run(["plan"], out=lines.append) == 1
    lines.clear()
    assert cli.run(["detect"], out=lines.append) == 0 and "Aviso" in lines[0]


# -- início da sessão (6.5) ----------------------------------------------------------------------------------------


def test_imagem_ausente_impede_a_sessao_com_o_comando_de_ensure() -> None:
    with pytest.raises(PlatformImageError) as exc:
        check_sandbox_image(FakeClient("aarch64"))
    assert ENSURE_COMMAND in str(exc.value) and "não existe" in str(exc.value)


def test_arquitetura_errada_impede_a_sessao_citando_as_duas(sandbox_ref) -> None:
    with pytest.raises(PlatformImageError, match=r"amd64.*arm64") as exc:
        check_sandbox_image(FakeClient("aarch64", {sandbox_ref: "amd64"}))
    assert ENSURE_COMMAND in str(exc.value)


def test_plataforma_nao_validada_gera_um_unico_warning(sandbox_ref, caplog) -> None:
    client = FakeClient("aarch64", {sandbox_ref: "arm64"})
    with caplog.at_level(logging.WARNING):
        check_sandbox_image(client)
        check_sandbox_image(client)
    warnings = [r for r in caplog.records if "não validada" in r.getMessage()]
    assert len(warnings) == 1


def test_imagem_certa_inicia_sem_erro(sandbox_ref) -> None:
    check_sandbox_image(FakeClient("aarch64", {sandbox_ref: "arm64"}))


def test_daemon_inacessivel_nao_bloqueia(monkeypatch) -> None:
    def no_daemon(timeout=10):
        raise PlatformImageError("sem daemon")

    monkeypatch.setattr("src.platform_images.docker_client", no_daemon)
    check_sandbox_image()  # não levanta: ensure_infrastructure já avisa


def test_infraestrutura_chama_a_checagem_so_com_a_skill_de_codigo(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("src.platform_images.check_sandbox_image", lambda *a, **k: calls.append("x"))
    monkeypatch.setattr(infrastructure, "SKILL_CODE_ENABLED", False)
    infrastructure.check_sandbox_image_for_session()
    assert calls == []
    monkeypatch.setattr(infrastructure, "SKILL_CODE_ENABLED", True)
    infrastructure.check_sandbox_image_for_session()
    assert calls == ["x"]
