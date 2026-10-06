"""Teste de política: um único caminho de seleção de modelo (v16-model-catalog-router)."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
REMOVED = ("AGENT_MODEL", "LLM_MODEL", "DEFAULT_MODEL", "LLM_PROVIDER")
# Leitura de ambiente: environ.get("X"), environ["X"], getenv("X"), get_env("X"); ou config.X / import de X.
_READ = re.compile(
    r"""(environ(\.get)?\s*[\(\[]|getenv\s*\(|get_env\s*\()\s*["'](?P<env>{names})["']""".format(
        names="|".join(REMOVED)
    )
)
_CONFIG = re.compile(
    r"\bconfig\.(?P<attr>{names})\b|\bimport\b[^\n]*\b(?P<imp>{names})\b".format(names="|".join(REMOVED))
)
_ALLOWED = {ROOT / "src" / "llm" / "routing.py"}


def _python_files():
    for base in ("agents", "src"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if path not in _ALLOWED:
                yield path


def test_nenhuma_leitura_direta_de_variaveis_de_modelo_removidas():
    """Cenário: Leitura direta proibida (varre agents/ e src/, fora de src/llm/routing.py)."""
    offenders = []
    for path in _python_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if _READ.search(line) or _CONFIG.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "Leitura direta de variável de modelo removida:\n" + "\n".join(offenders)


def test_config_nao_define_mais_as_variaveis_removidas():
    from src import config

    for name in ("LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL"):
        assert not hasattr(config, name), name
    for role in ("RESEARCHER", "VALIDATOR", "DEVELOPER"):
        assert not hasattr(config, f"{role}_PROVIDER")
        assert not hasattr(config, f"{role}_MODEL")


def test_politica_so_funciona_se_detectar_uma_leitura():
    """Garante que o detector não é cego."""
    assert _READ.search('x = os.environ.get("AGENT_MODEL")')
    assert _READ.search("y = os.getenv('LLM_MODEL')")
    assert _CONFIG.search("from src.config import DEFAULT_MODEL")
    assert _CONFIG.search("m = config.LLM_MODEL")
    assert not _READ.search("# AGENT_MODEL aparece só em comentário")
