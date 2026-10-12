"""Manifesto, plano e obtenção conferida (v16-platform-images, cenários 6.2–6.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.platform_images import (
    MANIFEST_PATH,
    ManifestError,
    PlatformImageError,
    ensure_images,
    load_manifest,
    parse_manifest,
    plan_images,
    select_images,
)
from src.platform_info import detect_platform

from .helpers import FakeClient

pytestmark = pytest.mark.unit

PI5 = "Raspberry Pi 5 Model B\x00"


def _info(arch: str = "aarch64", *, pi: bool = True, page: int = 16384, system: str = "Linux"):
    return detect_platform(system=system, machine=arch, device_tree_text=PI5 if pi else None, page_size=page,
                           daemon_info={"OSType": "linux", "Architecture": arch})


def _manifest(tmp_path: Path):
    return load_manifest(MANIFEST_PATH)


def test_manifesto_do_repositorio_e_valido() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    assert {"sandbox", "postgres", "qdrant"} <= set(manifest)
    assert manifest["ollama"].opcional is True and manifest["qdrant"].validada_em == ("linux/arm64/pi5/16k",)
    assert manifest["sandbox"].reference  # lê SANDBOX_IMAGE da configuração


def test_chave_desconhecida_cita_a_chave_e_a_imagem() -> None:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    data["imagens"]["qdrant"]["emular"] = True
    with pytest.raises(ManifestError, match=r"qdrant.*emular|emular.*qdrant"):
        parse_manifest(data)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["imagens"]["qdrant"].update(obter="curl"), "obter"),
    (lambda d: d["imagens"]["sandbox"].pop("dockerfile"), "dockerfile"),
    (lambda d: d["imagens"]["qdrant"].update(arquiteturas=[]), "arquiteturas"),
    (lambda d: d.update(versao=2), "Versão"),
    (lambda d: d.update(extra=1), "chaves"),
])
def test_manifesto_invalido(mutate, message) -> None:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(ManifestError, match=message):
        parse_manifest(data)


def test_manifesto_ilegivel_e_yaml_invalido(tmp_path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "nao_existe.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(bad)


def test_selecao_padrao_exclui_o_opcional() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    assert [s.nome for s in select_images(manifest)] == ["sandbox", "postgres", "qdrant"]
    assert "ollama" in [s.nome for s in select_images(manifest, with_ollama=True)]
    assert [s.nome for s in select_images(manifest, ["ollama"])] == ["ollama"]
    with pytest.raises(PlatformImageError, match="fora do manifesto"):
        select_images(manifest, ["nao_existe"])


def test_plano_imagem_presente_com_a_arquitetura_certa_e_ok() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    sandbox = manifest["sandbox"]
    client = FakeClient("aarch64", {sandbox.reference: "arm64"})
    (item,) = plan_images([sandbox], _info(), client)
    assert item.estado == "ok"


def test_plano_arquitetura_divergente_manda_construir() -> None:
    sandbox = load_manifest(MANIFEST_PATH)["sandbox"]
    (item,) = plan_images([sandbox], _info(), FakeClient("aarch64", {sandbox.reference: "amd64"}))
    assert item.estado == "build" and "amd64" in item.detalhe and "arm64" in item.detalhe


def test_plano_ausente_pull_e_build_e_compose() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    items = {i.nome: i for i in plan_images([manifest["sandbox"], manifest["qdrant"], manifest["postgres"]],
                                            _info(), FakeClient("aarch64"))}
    assert (items["sandbox"].estado, items["qdrant"].estado, items["postgres"].estado) == ("build", "pull", "compose")


def test_plataforma_nao_validada_avisa_sem_nenhum_efeito() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    client = FakeClient("x86_64")
    info = _info("x86_64", pi=False, page=4096)
    (item,) = plan_images([manifest["qdrant"]], info, client)
    assert "nao_validada" in item.avisos and item.estado == "pull"
    assert client.images.calls == []  # o plano nunca baixa nem constrói


def test_plataforma_validada_nao_avisa() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    (item,) = plan_images([manifest["qdrant"]], _info(), FakeClient("aarch64"))
    assert item.avisos == ()


def test_arquitetura_sem_suporte_no_plano() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    info = detect_platform(system="Linux", machine="s390x", page_size=4096,
                           daemon_info={"OSType": "linux", "Architecture": "s390x"})
    (item,) = plan_images([manifest["qdrant"]], info, FakeClient("s390x"))
    assert item.estado == "sem_suporte"


def test_plano_sem_daemon_falha_com_mensagem_clara() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    info = detect_platform(system="Linux", machine="aarch64", page_size=4096)
    with pytest.raises(PlatformImageError, match="Daemon de containers inacessível"):
        plan_images([manifest["qdrant"]], info, FakeClient())


# -- ensure (6.4) --------------------------------------------------------------------------------------------------


def test_build_nativo_registra_o_resultado(tmp_path) -> None:
    sandbox = load_manifest(MANIFEST_PATH)["sandbox"]
    client = FakeClient("aarch64")
    platform_file = tmp_path / "store" / "platform.json"
    result = ensure_images([sandbox], _info(), client, assume_yes=True, project_root=tmp_path,
                           platform_file=platform_file, out=lambda _m: None)
    (kind, kwargs), = client.images.calls
    assert kind == "build" and kwargs["platform"] == "linux/arm64" and kwargs["dockerfile"] == sandbox.dockerfile
    assert kwargs["tag"] == sandbox.reference
    saved = json.loads(platform_file.read_text(encoding="utf-8"))
    entry = saved["imagens"]["sandbox"]
    assert entry["referencia"] == sandbox.reference and entry["arquitetura"] == "arm64" and entry["id"]
    assert saved["plataforma"]["id"] == "linux/arm64/pi5/16k" and saved["manifesto_versao"] == 1
    assert entry["validada"] is False and result.avisos


def test_arquitetura_divergente_apos_pull_falha_citando_as_duas(tmp_path) -> None:
    qdrant = load_manifest(MANIFEST_PATH)["qdrant"]
    client = FakeClient("aarch64", pull_arch="amd64")
    platform_file = tmp_path / "platform.json"
    with pytest.raises(PlatformImageError, match=r"amd64.*arm64"):
        ensure_images([qdrant], _info(), client, assume_yes=True, platform_file=platform_file, out=lambda _m: None)
    assert not platform_file.exists()


def test_sem_suporte_nao_baixa_nada(tmp_path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    info = detect_platform(system="Linux", machine="s390x", page_size=4096,
                           daemon_info={"OSType": "linux", "Architecture": "s390x"})
    client = FakeClient("s390x")
    with pytest.raises(PlatformImageError, match=r"s390x.*arm64.*amd64|Arquiteturas suportadas"):
        ensure_images([manifest["qdrant"], manifest["sandbox"]], info, client, assume_yes=True,
                      platform_file=tmp_path / "p.json", out=lambda _m: None)
    assert client.images.calls == []


def test_confirmacao_negada_nao_altera_nada(tmp_path) -> None:
    qdrant = load_manifest(MANIFEST_PATH)["qdrant"]
    client = FakeClient("aarch64")
    with pytest.raises(PlatformImageError, match="negada"):
        ensure_images([qdrant], _info(), client, input_fn=lambda _p: "n", platform_file=tmp_path / "p.json",
                      out=lambda _m: None)
    assert client.images.calls == []


def test_confirmacao_positiva_baixa_com_a_plataforma(tmp_path) -> None:
    qdrant = load_manifest(MANIFEST_PATH)["qdrant"]
    client = FakeClient("aarch64")
    asked: list[str] = []
    ensure_images([qdrant], _info(), client, input_fn=lambda p: asked.append(p) or "s",
                  platform_file=tmp_path / "p.json", out=lambda _m: None)
    assert client.images.calls[0][1]["platform"] == "linux/arm64" and "linux/arm64" in asked[0]


def test_imagem_ok_nao_baixa_e_compose_so_registra(tmp_path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    qdrant = manifest["qdrant"]
    client = FakeClient("aarch64", {qdrant.reference: "arm64"})
    result = ensure_images([qdrant, manifest["postgres"]], _info(), client, assume_yes=True,
                           platform_file=tmp_path / "p.json", out=lambda _m: None)
    assert client.images.calls == [] and result.imagens["qdrant"]["validada"] is True
    assert result.imagens["postgres"]["observacao"].startswith("construída pelo docker compose")


def test_falha_do_daemon_vira_erro_acionavel(tmp_path) -> None:
    qdrant = load_manifest(MANIFEST_PATH)["qdrant"]
    client = FakeClient("aarch64")

    def boom(*a, **k):
        raise RuntimeError("sem rede")

    client.images.pull = boom
    with pytest.raises(PlatformImageError, match="Falha em pull"):
        ensure_images([qdrant], _info(), client, assume_yes=True, platform_file=tmp_path / "p.json",
                      out=lambda _m: None)
