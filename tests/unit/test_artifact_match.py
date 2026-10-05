"""Comparador tolerante de artefatos (v16-pipeline-robustness, requisito "Resolução tolerante")."""

import os

import pytest

from src.artifact_match import resolve_artifacts

pytestmark = pytest.mark.unit


def _touch(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_prefixo_diferente_do_esperado_resolve_por_extensao(tmp_path):
    """Scenario: Prefixo diferente do esperado."""
    _touch(tmp_path, "eda/iris_hist.png", "eda/iris_box.png")
    res = resolve_artifacts(["eda_hist.png", "eda_box.png"], tmp_path, "eda")
    assert [r.tier for r in res] == ["extension", "extension"]
    assert all(r.name_mismatch for r in res)
    assert {r.matched[0].name for r in res} == {"iris_hist.png", "iris_box.png"}


def test_padrao_glob(tmp_path):
    """Scenario: Padrão glob."""
    _touch(tmp_path, "eda/eda_hist.png")
    (res,) = resolve_artifacts(["eda_*.png"], tmp_path, "eda")
    assert res.tier == "glob" and not res.name_mismatch


def test_menos_arquivos_que_o_esperado(tmp_path):
    """Scenario: Menos arquivos que o esperado."""
    _touch(tmp_path, "eda/a.png", "eda/b.png")
    res = resolve_artifacts(["x1.png", "x2.png", "x3.png"], tmp_path, "eda")
    assert [r.tier for r in res].count("missing") == 1


def test_codigo_nunca_casa_por_extensao(tmp_path):
    """Scenario: Código nunca casa por extensão."""
    _touch(tmp_path, "t/outro.py")
    (res,) = resolve_artifacts(["modelo.py"], tmp_path, "t")
    assert res.tier == "missing"


def test_cada_arquivo_resolve_um_esperado(tmp_path):
    """Scenario: Cada arquivo resolve um esperado."""
    _touch(tmp_path, "t/unico.png")
    res = resolve_artifacts(["a.png", "b.png"], tmp_path, "t")
    assert sorted(r.tier for r in res) == ["extension", "missing"]


def test_saida_da_pasta_da_sessao(tmp_path):
    """Scenario: Saída da pasta da sessão."""
    session = tmp_path / "sess"
    session.mkdir()
    (tmp_path / "segredo.txt").write_text("s")
    os.symlink(tmp_path / "segredo.txt", session / "link.txt")
    res = resolve_artifacts(["../segredo.txt", "link.txt", "/etc/passwd"], session, None)
    assert [r.tier for r in res] == ["missing", "missing", "missing"]


def test_modo_estrito(tmp_path):
    """Scenario: Modo estrito."""
    _touch(tmp_path, "eda/iris_hist.png")
    (res,) = resolve_artifacts(["eda_hist.png"], tmp_path, "eda", mode="strict")
    assert res.tier == "missing"


def test_nome_normalizado(tmp_path):
    _touch(tmp_path, "t/ConfusionMatrix.PNG")
    (res,) = resolve_artifacts(["confusion_matrix.png"], tmp_path, "t")
    assert res.tier == "normalized"


def test_exato_com_prefixo_outputs_e_pasta_da_subtarefa_primeiro(tmp_path):
    _touch(tmp_path, "a/metrics.json", "b/metrics.json")
    (res,) = resolve_artifacts(["/outputs/b/metrics.json"], tmp_path, "a")
    assert res.tier == "exact" and res.matched[0].as_posix() == "b/metrics.json"
    (res2,) = resolve_artifacts(["metrics.json"], tmp_path, "b")
    assert res2.matched[0].as_posix() == "b/metrics.json"


def test_arquivos_de_infraestrutura_sao_ignorados(tmp_path):
    _touch(tmp_path, "t/script.py", "t/scientific_helpers.py")
    res = resolve_artifacts(["script.py"], tmp_path, "t")
    assert res[0].tier == "missing"
