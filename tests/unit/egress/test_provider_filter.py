"""Todo provedor obtido passa pelo filtro de egresso (v18.7-layer-cycles; ADR 019; ADR 024 §4)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.egress.gate import GatedProvider
from src.egress.routing import ModelRouter
from src.llm import factory
from src.llm.base import LLMProvider, LLMResponse

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_ROLES = ("researcher", "developer", "validator", "summarizer", "curator", "base", "planner")

# Padrão -> arquivos (relativos à raiz) onde ele pode aparecer em src/ e scripts/ (design §5, S1).
# `src/llm/factory.py` também chama `.unwrap()`: é a conferência do resolvedor (S2), que recusa o provedor sem filtro.
_ALLOWED = {
    "create_provider": {"src/egress/routing.py", "src/llm/availability.py", "scripts/benchmark/comm_judge.py"},
    "default_provider_factory": {"src/llm/availability.py"},
    "unwrap": {"src/llm/metering.py", "src/llm/factory.py"},
}
_INNER_DIR = "src/egress/"
_PROVIDERS_DIR = "src/llm/providers/"


class _Fake(LLMProvider):
    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        return LLMResponse(text="ok")

    async def generate_stream(self, messages, system=None):
        yield "ok"

    async def health_check(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "fake"


def _provider_classes(root: Path) -> list[str]:
    names: list[str] = []
    for path in (root / "src" / "llm" / "providers").glob("*.py"):
        names += re.findall(r"^class (\w+)\([^)]*Provider[^)]*\):", path.read_text(encoding="utf-8"), re.M)
    return names


def scan_ungated_providers(root: Path) -> list[str]:
    """Ocorrências que devolvem ou expõem provedor sem filtro fora dos arquivos permitidos."""
    classes = _provider_classes(root) or _provider_classes(_ROOT)
    constructors = re.compile(r"(?<![\w.])(?:" + "|".join(map(re.escape, classes)) + r")\(")
    calls = {
        name: re.compile(r"(?<!def )(?<![\w])" + name + r"\(") for name in ("create_provider", "default_provider_factory")
    }
    unwrap = re.compile(r"\.unwrap\(\)")
    inner = re.compile(r"\.inner\b")
    found: list[str] = []
    for base in ("src", "scripts"):
        for path in sorted((root / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            if constructors.search(text) and not rel.startswith(_PROVIDERS_DIR):
                found.append(f"{rel}: construtor de provedor")
            for name, pattern in calls.items():
                if pattern.search(text) and rel not in _ALLOWED[name]:
                    found.append(f"{rel}: {name}(")
            if unwrap.search(text) and rel not in _ALLOWED["unwrap"]:
                found.append(f"{rel}: .unwrap()")
            if inner.search(text) and not rel.startswith(_INNER_DIR):
                found.append(f"{rel}: .inner")
    return found


@pytest.mark.parametrize("role", _ROLES)
def test_provedor_de_cada_papel_e_filtrado(role: str) -> None:
    assert isinstance(ModelRouter.get_provider(role), GatedProvider)


def test_provedor_sem_papel_e_filtrado() -> None:
    provider = factory.get_provider()
    assert isinstance(provider, GatedProvider)
    assert provider.dest.papel == "researcher"


def test_provedor_sem_filtro_so_nos_arquivos_permitidos() -> None:
    assert scan_ungated_providers(_ROOT) == []


def test_varredura_acusa_arquivo_fora_da_lista(tmp_path) -> None:
    (tmp_path / "src" / "llm" / "providers").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "qualquer.py").write_text("from x import create_provider\n\nprovider = create_provider('a', 'b')\n")
    assert scan_ungated_providers(tmp_path) == ["src/qualquer.py: create_provider("]


def test_resolvedor_que_devolve_provedor_cru_e_recusado(monkeypatch) -> None:
    monkeypatch.setattr(factory, "_resolver", lambda papel=None: _Fake())
    with pytest.raises(RuntimeError, match="provedor sem filtro de egresso: o resolvedor registrado deve devolver"):
        factory.get_provider()
