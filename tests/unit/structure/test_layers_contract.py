"""Contrato de camadas verificado (ADR 024 §3; ``v18.7-source-layout``, requisito "Contrato de camadas verificado")."""

from __future__ import annotations

import textwrap
import tomllib

import pytest

from tests.unit.structure.helpers import ROOT, importlinter_section, run_lint_imports

pytestmark = pytest.mark.unit


def test_contrato_valido_no_codigo_reorganizado() -> None:
    result = run_lint_imports(ROOT / "pyproject.toml")
    assert result.returncode == 0, result.stdout + result.stderr


def test_importacao_proibida_e_acusada(tmp_path) -> None:
    pkg = tmp_path / "pkgtmp"
    (pkg / "orchestration").mkdir(parents=True)
    (pkg / "knowledge").mkdir()
    for init in (pkg / "__init__.py", pkg / "orchestration" / "__init__.py", pkg / "knowledge" / "__init__.py"):
        init.write_text("")
    (pkg / "orchestration" / "mod.py").write_text("VALOR = 1\n")
    (pkg / "knowledge" / "mod.py").write_text(
        "def usa() -> int:\n    from pkgtmp.orchestration import mod\n\n    return mod.VALOR\n"
    )
    options = tomllib.loads(importlinter_section())["tool"]["importlinter"]
    config = tmp_path / "contrato.ini"
    config.write_text(textwrap.dedent(f"""\
        [importlinter]
        root_package = pkgtmp
        exclude_type_checking_imports = {str(options['exclude_type_checking_imports'])}

        [importlinter:contract:camadas]
        name = camadas temporarias
        type = layers
        layers =
            orchestration
            knowledge
        containers =
            pkgtmp
        """))
    result = run_lint_imports(config, cwd=tmp_path, pythonpath=[tmp_path])
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "knowledge" in output and "orchestration" in output


def test_importacao_de_verificacao_de_tipos_nao_conta(tmp_path) -> None:
    kept = run_lint_imports(ROOT / "pyproject.toml")
    assert kept.returncode == 0, kept.stdout + kept.stderr

    section = importlinter_section()
    assert "exclude_type_checking_imports = true" in section
    config = tmp_path / "sem_exclusao.toml"
    config.write_text(section.replace("exclude_type_checking_imports = true", "exclude_type_checking_imports = false"))
    result = run_lint_imports(config)
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "src.knowledge.resume_context" in output and "src.session.continuity" in output


def test_contrato_sem_excecoes_de_egresso_e_llm() -> None:
    """``v18.7-layer-cycles``: a exceção ``egress`` <-> ``llm`` saiu; resta só a de ``config`` (questão em aberto)."""
    options = tomllib.loads(importlinter_section())["tool"]["importlinter"]
    ignored = options["contracts"][0]["ignore_imports"]
    assert ignored == ["src.config -> src.utils.node_id"]
    assert not any("llm" in item or "egress" in item for item in ignored)
    assert run_lint_imports(ROOT / "pyproject.toml").returncode == 0


def test_importacao_de_llm_para_egress_e_acusada(tmp_path) -> None:
    pkg = tmp_path / "pkgtmp"
    (pkg / "egress").mkdir(parents=True)
    (pkg / "llm").mkdir()
    for init in (pkg / "__init__.py", pkg / "egress" / "__init__.py", pkg / "llm" / "__init__.py"):
        init.write_text("")
    (pkg / "egress" / "mod.py").write_text("VALOR = 1\n")
    (pkg / "llm" / "mod.py").write_text(
        "def usa() -> int:\n    from pkgtmp.egress import mod\n\n    return mod.VALOR\n"
    )
    options = tomllib.loads(importlinter_section())["tool"]["importlinter"]
    config = tmp_path / "contrato.ini"
    config.write_text(textwrap.dedent(f"""\
        [importlinter]
        root_package = pkgtmp
        exclude_type_checking_imports = {str(options['exclude_type_checking_imports'])}

        [importlinter:contract:camadas]
        name = camadas temporarias
        type = layers
        layers =
            egress
            llm
        containers =
            pkgtmp
        """))
    result = run_lint_imports(config, cwd=tmp_path, pythonpath=[tmp_path])
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "llm" in output and "egress" in output
