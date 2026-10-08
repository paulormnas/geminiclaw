"""Manifesto ``input_context/dados.yaml`` e classificação efetiva dos arquivos de entrada.

O pesquisador marca arquivos como ``compartilhavel`` (ex.: dataset público) ou ``dado_de_pesquisa`` (ex.: caderno de
laboratório em PDF). Sem marcação vale a regra padrão por extensão (design §2). Qualquer inconsistência do manifesto
impede a sessão (``ManifestError``), com a linha do problema.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from src.egress.fragments import ContentOrigin
from src.logger import get_logger

logger = get_logger(__name__)

MANIFEST_NAME = "dados.yaml"
MANIFEST_VERSION = 1
MARK_SHAREABLE = "compartilhavel"
MARK_RESEARCH_DATA = "dado_de_pesquisa"
VALID_MARKS = frozenset({MARK_SHAREABLE, MARK_RESEARCH_DATA})
ORIGIN_MANIFEST = "manifesto"
ORIGIN_DEFAULT = "padrao"

_TOP_KEYS = frozenset({"versao", "arquivos"})
_ENTRY_KEYS = frozenset({"caminho", "marcacao", "motivo"})

# Regra padrão (design §2): documentos seguem a LLM_DATA_POLICY; o resto é dado de pesquisa.
DOCUMENT_EXTENSIONS = frozenset({".txt", ".md", ".rst", ".pdf", ".docx", ".pptx"})


class ManifestError(ValueError):
    """Manifesto inválido: a sessão não inicia."""


@dataclass(frozen=True)
class ManifestEntry:
    """Entrada do manifesto."""

    caminho: str
    marcacao: str
    motivo: str | None
    linha: int  # 1-based; 0 quando desconhecida


@dataclass(frozen=True)
class FileMarking:
    """Classificação efetiva de um arquivo de ``input_context/``."""

    caminho: str  # relativo a input_context/, separador "/"
    classe: ContentOrigin
    marcacao: str | None  # None quando vale a regra padrão
    motivo: str | None
    origem: str  # "manifesto" | "padrao"
    sha256: str | None = None

    @property
    def compartilhavel(self) -> bool:
        return self.marcacao == MARK_SHAREABLE

    def to_payload(self) -> dict[str, Any]:
        """Registro gravado em ``payload["research_data_markings"]``."""
        return {
            "caminho": self.caminho,
            "classe_efetiva": ("dado_de_pesquisa" if self.classe is ContentOrigin.DADO_DE_PESQUISA else "documento"),
            "marcacao": self.marcacao,
            "motivo": self.motivo,
            "sha256": self.sha256,
            "origem": self.origem,
        }


def default_origin(path: Path | str) -> ContentOrigin:
    """Classe padrão pela extensão (design §2)."""
    suffix = Path(path).suffix.lower()
    return ContentOrigin.DOCUMENTO if suffix in DOCUMENT_EXTENSIONS else ContentOrigin.DADO_DE_PESQUISA


def file_sha256(path: Path) -> str | None:
    """sha256 do conteúdo do arquivo, ou ``None`` se ilegível."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


class ResearchDataManifest:
    """Marcações lidas de ``dados.yaml``."""

    def __init__(self, base_dir: Path, entries: list[ManifestEntry], source: Path | None = None) -> None:
        self.base_dir = base_dir
        self.entries = entries
        self.source = source

    @property
    def present(self) -> bool:
        return self.source is not None

    def matching(self, rel_path: str) -> list[ManifestEntry]:
        """Entradas cujo caminho ou padrão casa com ``rel_path``."""
        return [e for e in self.entries if _matches(e.caminho, rel_path)]

    def entry_for(self, rel_path: str) -> ManifestEntry | None:
        """Entrada que vale para ``rel_path``.

        Raises:
            ManifestError: Marcações diferentes para o mesmo arquivo (a mensagem cita os dois padrões).
        """
        found = self.matching(rel_path)
        if not found:
            return None
        first = found[0]
        for other in found[1:]:
            if other.marcacao != first.marcacao:
                raise ManifestError(
                    f"{MANIFEST_NAME}: marcações conflitantes para '{rel_path}': "
                    f"'{first.caminho}' ({first.marcacao}, linha {first.linha}) e "
                    f"'{other.caminho}' ({other.marcacao}, linha {other.linha})."
                )
        return first

    def marking_for(self, path: Path) -> FileMarking:
        """Classificação efetiva de ``path`` (arquivo dentro de ``base_dir``).

        Raises:
            ManifestError: Conflito de marcações ou symlink que resolve fora de ``input_context/``.
        """
        rel = relative_posix(path, self.base_dir)
        entry = self.entry_for(rel)
        if entry is not None:
            _ensure_inside(path, self.base_dir, entry)
        default = default_origin(path)
        if entry is None:
            return FileMarking(rel, default, None, None, ORIGIN_DEFAULT)
        if entry.marcacao == MARK_SHAREABLE:
            # `compartilhavel` só muda o tratamento de dado de pesquisa; num documento vale como registro.
            return FileMarking(rel, default, MARK_SHAREABLE, entry.motivo, ORIGIN_MANIFEST)
        return FileMarking(rel, ContentOrigin.DADO_DE_PESQUISA, MARK_RESEARCH_DATA, entry.motivo, ORIGIN_MANIFEST)

    def warn_unmatched(self, files: list[Path]) -> list[str]:
        """Padrões sem nenhum arquivo: ``WARNING`` por padrão (devolve as mensagens)."""
        rels = [relative_posix(p, self.base_dir) for p in files]
        messages: list[str] = []
        for entry in self.entries:
            if not any(_matches(entry.caminho, rel) for rel in rels):
                message = (
                    f"{MANIFEST_NAME}: o padrão '{entry.caminho}' (linha {entry.linha}) não casa com nenhum arquivo."
                )
                logger.warning(message)
                messages.append(message)
        return messages


def relative_posix(path: Path, base_dir: Path) -> str:
    """Caminho de ``path`` relativo a ``base_dir`` com separador ``/`` (sem resolver symlinks)."""
    try:
        return PurePosixPath(*path.relative_to(base_dir).parts).as_posix()
    except ValueError:
        return PurePosixPath(*path.parts[-1:]).as_posix()


def _matches(pattern: str, rel_path: str) -> bool:
    return pattern == rel_path or fnmatch.fnmatchcase(rel_path, pattern)


def _ensure_inside(path: Path, base_dir: Path, entry: ManifestEntry) -> None:
    try:
        resolved = path.resolve()
        base = base_dir.resolve()
    except OSError as exc:
        raise ManifestError(f"{MANIFEST_NAME}: não foi possível resolver '{path}': {exc}") from exc
    if resolved != base and base not in resolved.parents:
        raise ManifestError(
            f"{MANIFEST_NAME}: o arquivo '{path.name}' (entrada '{entry.caminho}', linha {entry.linha}) resolve fora "
            "de input_context/ (symlink); remova o link ou copie o arquivo para input_context/."
        )


def _entry_lines(text: str) -> list[int]:
    """Linha (1-based) de cada item de ``arquivos`` na ordem do arquivo; vazia se a estrutura não permitir."""
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return []
    if not isinstance(root, yaml.MappingNode):
        return []
    for key, value in root.value:
        if getattr(key, "value", None) == "arquivos" and isinstance(value, yaml.SequenceNode):
            return [item.start_mark.line + 1 for item in value.value]
    return []


def _fail(message: str, line: int = 0) -> ManifestError:
    where = f" (linha {line})" if line else ""
    return ManifestError(f"{MANIFEST_NAME}{where}: {message}")


def parse_manifest(text: str, base_dir: Path, source: Path | None = None) -> ResearchDataManifest:
    """Valida ``text`` (conteúdo de ``dados.yaml``) com esquema estrito.

    Raises:
        ManifestError: Chave desconhecida, ``versao`` diferente de 1, marcação inválida, ``compartilhavel`` sem
            ``motivo``, caminho absoluto ou que sai de ``input_context/``.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise _fail(f"YAML inválido: {exc}", (mark.line + 1) if mark else 0) from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise _fail("o conteúdo precisa ser um mapa com 'versao' e 'arquivos'.")
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise _fail(f"chave desconhecida: {', '.join(sorted(map(str, unknown)))} (permitidas: versao, arquivos).")
    if data.get("versao") != MANIFEST_VERSION or isinstance(data.get("versao"), bool):
        raise _fail(f"'versao' precisa ser {MANIFEST_VERSION}.")
    raw_entries = data.get("arquivos", [])
    if raw_entries is None:
        raw_entries = []
    if not isinstance(raw_entries, list):
        raise _fail("'arquivos' precisa ser uma lista.")
    lines = _entry_lines(text)
    entries: list[ManifestEntry] = []
    for index, raw in enumerate(raw_entries):
        line = lines[index] if index < len(lines) else 0
        if not isinstance(raw, dict):
            raise _fail(f"a entrada {index + 1} precisa ser um mapa.", line)
        extra = set(raw) - _ENTRY_KEYS
        if extra:
            raise _fail(f"chave desconhecida na entrada {index + 1}: {', '.join(sorted(map(str, extra)))}.", line)
        caminho = raw.get("caminho")
        if not isinstance(caminho, str) or not caminho.strip():
            raise _fail(f"a entrada {index + 1} não tem 'caminho'.", line)
        caminho = caminho.strip()
        marcacao = raw.get("marcacao")
        if marcacao not in VALID_MARKS:
            raise _fail(
                f"'marcacao' inválida em '{caminho}': use '{MARK_SHAREABLE}' ou '{MARK_RESEARCH_DATA}'.", line
            )
        motivo = raw.get("motivo")
        if motivo is not None and not isinstance(motivo, str):
            raise _fail(f"'motivo' de '{caminho}' precisa ser texto.", line)
        motivo = motivo.strip() if isinstance(motivo, str) and motivo.strip() else None
        if marcacao == MARK_SHAREABLE and motivo is None:
            raise _fail(f"'{caminho}' é 'compartilhavel' e exige 'motivo' (ex.: DOI do dataset público).", line)
        normalized = caminho.replace("\\", "/")
        if normalized.startswith("/") or PurePosixPath(normalized).is_absolute() or (
            len(normalized) > 1 and normalized[1] == ":"
        ):
            raise _fail(f"o caminho '{caminho}' é absoluto; use caminho relativo a input_context/.", line)
        if ".." in PurePosixPath(normalized).parts:
            raise _fail(f"o caminho '{caminho}' sai de input_context/.", line)
        entries.append(ManifestEntry(normalized, marcacao, motivo, line))
    return ResearchDataManifest(base_dir, entries, source)


def load_manifest(context_dir: Path | str) -> ResearchDataManifest:
    """Lê ``<context_dir>/dados.yaml``; sem o arquivo, devolve um manifesto vazio (vale a regra padrão).

    Raises:
        ManifestError: Manifesto inválido.
    """
    base = Path(context_dir)
    path = base / MANIFEST_NAME
    if not path.is_file():
        return ResearchDataManifest(base, [], None)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _fail(f"não foi possível ler o arquivo: {exc}") from exc
    return parse_manifest(text, base, path)
