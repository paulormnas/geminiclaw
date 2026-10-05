"""Comparador tolerante de artefatos (V16 / ``v16-pipeline-robustness`` §2).

Resolve cada artefato esperado pelo plano contra os arquivos reais da sessão, em camadas da mais
estrita à mais tolerante (``exact``, ``glob``, ``normalized``, ``extension``). Função pura sobre o
sistema de arquivos: nunca lê conteúdo e nunca sai da pasta da sessão.
"""

from __future__ import annotations

import fnmatch
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Extensões de artefato de dados para as quais a camada ``extension`` vale (nunca código).
EXTENSION_TIER_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".svg", ".csv", ".json", ".md", ".txt", ".html", ".pdf", ".parquet"}
)
_IGNORED_NAMES = frozenset({"scientific_helpers.py", "script.py", "manifest.json"})


@dataclass(frozen=True)
class ArtifactResolution:
    """Resolução de um artefato esperado.

    Attributes:
        expected: Nome ou padrão esperado, como no plano.
        matched: Caminhos resolvidos, relativos à pasta da sessão (vazio = ausente).
        tier: ``exact``, ``glob``, ``normalized``, ``extension`` ou ``missing``.
    """

    expected: str
    matched: list[Path] = field(default_factory=list)
    tier: str = "missing"

    @property
    def name_mismatch(self) -> bool:
        """Indica resolução por nome diferente do esperado (aprovação com aviso)."""
        return self.tier in ("normalized", "extension")


def _normalize(name: str) -> str:
    stripped = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s_\-]+", "", stripped.lower())


def _list_files(session_dir: Path, task_dir: str | None) -> list[Path]:
    """Lista arquivos da sessão (relativos), a pasta da subtarefa primeiro."""
    root = session_dir.resolve()
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (ValueError, OSError):
            continue
        if path.name in _IGNORED_NAMES or path.suffix == ".pyc":
            continue
        found.append(path.relative_to(root))
    prefix = f"{task_dir}/" if task_dir else None
    if prefix:
        found.sort(key=lambda p: (not p.as_posix().startswith(prefix), p.as_posix()))
    return found


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _normalize_ascii(Path(name).stem)) if t}


def _normalize_ascii(name: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn").lower()


def _pair_by_overlap(items: list[tuple[int, str]], candidates: list[Path]) -> list[tuple[tuple[int, str], Path]]:
    """Casa esperados e arquivos da mesma extensão, preferindo maior sobreposição de palavras do nome."""
    scored = sorted(
        (
            (-len(_tokens(exp) & _tokens(file.name)), i, j)
            for i, (_, exp) in enumerate(items)
            for j, file in enumerate(candidates)
        )
    )
    taken_items: set[int] = set()
    taken_files: set[int] = set()
    pairs = []
    for _, i, j in scored:
        if i in taken_items or j in taken_files:
            continue
        taken_items.add(i)
        taken_files.add(j)
        pairs.append((items[i], candidates[j]))
    return pairs


def _clean(expected: str) -> str:
    """Remove o prefixo ``/outputs/`` e barras iniciais (o plano cita caminhos do sandbox)."""
    cleaned = expected.strip().lstrip("./") if expected.strip().startswith("./") else expected.strip()
    cleaned = cleaned.lstrip("/")
    return cleaned[len("outputs/"):] if cleaned.startswith("outputs/") else cleaned


def _is_safe_expected(expected: str) -> bool:
    return bool(expected.strip()) and ".." not in Path(expected).parts


def resolve_artifacts(
    expected: list[str],
    session_dir: Path | str,
    task_dir: str | None = None,
    mode: str = "tolerant",
) -> list[ArtifactResolution]:
    """Resolve os artefatos esperados contra os arquivos da pasta da sessão.

    Args:
        expected: Artefatos esperados (nomes, caminhos relativos ou padrões glob).
        session_dir: Pasta da sessão.
        task_dir: Pasta da subtarefa (tem prioridade na busca).
        mode: ``tolerant`` (todas as camadas) ou ``strict`` (só ``exact`` e ``glob``).

    Returns:
        Uma ``ArtifactResolution`` por esperado, na ordem recebida. Cada arquivo resolve no
        máximo um esperado.
    """
    files = _list_files(Path(session_dir), task_dir)
    used: set[Path] = set()
    results: dict[int, ArtifactResolution] = {}
    pending = list(enumerate(expected))

    def take(pred) -> list[Path]:
        return [f for f in files if f not in used and pred(f)]

    def run_tier(tier: str, matcher) -> None:
        nonlocal pending
        remaining = []
        for idx, exp in pending:
            hits = matcher(exp)
            if hits:
                used.update(hits)
                results[idx] = ArtifactResolution(exp, hits, tier)
            else:
                remaining.append((idx, exp))
        pending = remaining

    safe = [(i, e) for i, e in pending if _is_safe_expected(e)]
    for idx, exp in pending:
        if (idx, exp) not in safe:
            results[idx] = ArtifactResolution(exp, [], "missing")
    pending = safe

    def exact(exp: str) -> list[Path]:
        norm = _clean(exp)
        name = Path(exp).name
        if any(c in name for c in "*?"):
            return []
        hit = take(lambda f: f.as_posix() == norm or f.as_posix().endswith("/" + norm))
        return hit[:1] or take(lambda f: f.name == name)[:1]

    def glob(exp: str) -> list[Path]:
        name = Path(exp).name
        if not any(c in name for c in "*?"):
            return []
        return take(lambda f: fnmatch.fnmatch(f.name, name))

    run_tier("exact", exact)
    run_tier("glob", glob)
    if mode != "strict":
        run_tier("normalized", lambda exp: take(lambda f: _normalize(f.name) == _normalize(Path(exp).name))[:1])

        # extension: cada arquivo restante com a mesma extensão resolve um esperado (sobra = missing)
        by_suffix: dict[str, list[tuple[int, str]]] = {}
        for idx, exp in pending:
            suffix = Path(exp).suffix.lower()
            if suffix in EXTENSION_TIER_SUFFIXES:
                by_suffix.setdefault(suffix, []).append((idx, exp))
        for suffix, items in by_suffix.items():
            # glob esperado conta como (pelo menos) um arquivo; usa a pasta da subtarefa
            candidates = take(lambda f, s=suffix: f.suffix.lower() == s and (
                task_dir is None or f.as_posix().startswith(f"{task_dir}/")
            ))
            for (idx, exp), file in _pair_by_overlap(items, candidates):
                used.add(file)
                results[idx] = ArtifactResolution(exp, [file], "extension")
        pending = [(i, e) for i, e in pending if i not in results]

    for idx, exp in pending:
        results[idx] = ArtifactResolution(exp, [], "missing")
    return [results[i] for i in range(len(expected))]
