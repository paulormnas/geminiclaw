"""Sinalizações dos agentes ao Curator (ADR 012 §2; ``v17-curator-agent`` design §4).

Researcher, Developer e Validator sinalizam pontos importantes com ``flag_for_curator``; o Curator as consome no
próximo checkpoint e marca cada uma como ``registrada`` (com o ``id`` do nó criado ou reforçado) ou ``descartada``
(com motivo). O registro é um arquivo **append-only** ``outputs/<sessão>/curator_flags.jsonl`` (sem mudança de
schema): cada sinalização é uma linha; cada decisão do Curator é outra linha ``{"resolve": <id>, ...}``.

Segurança: o texto das sinalizações vem de LLMs que leem documentos não confiáveis; por isso é limpo
(``clean_free_text``), limitado em tamanho e quantidade, e **sempre apresentado ao Curator como dado**, nunca como
instrução. O arquivo é aberto com ``O_NOFOLLOW`` (sem seguir link simbólico) e a leitura é limitada.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import config
from src.knowledge.normalization import clean_free_text
from src.logger import get_logger

logger = get_logger(__name__)

FLAGS_FILENAME = "curator_flags.jsonl"
FLAG_TYPES: tuple[str, ...] = ("descoberta_potencial", "caminho_relevante", "oportunidade", "falha_relevante")
ESTADO_REGISTRADA = "registrada"
ESTADO_DESCARTADA = "descartada"
MAX_REFS = 10
MAX_REF_CHARS = 200
MAX_FIELD_CHARS = 128
_MAX_READ_BYTES = 2 * 1024 * 1024
_MAX_RESOLUTION_REASON = 300


class FlagError(ValueError):
    """Sinalização ou decisão inválida (mensagem acionável, sem eco do texto recebido)."""


@dataclass(frozen=True)
class Flag:
    """Uma sinalização pendente.

    Attributes:
        id: Identificador da sinalização.
        tipo: Um de ``FLAG_TYPES``.
        texto: Texto limpo (dado não confiável).
        refs: IDs de nós ou caminhos de artefatos da sessão (dado não confiável).
        agente: Papel que sinalizou.
        subtarefa: Subtarefa em que ocorreu.
        criado_em: Instante ISO-8601.
    """

    id: str
    tipo: str
    texto: str
    refs: tuple[str, ...]
    agente: str
    subtarefa: str
    criado_em: str


def _path(session_dir: Path) -> Path:
    return Path(session_dir) / FLAGS_FILENAME


def _read_lines(session_dir: Path) -> list[dict[str, Any]]:
    """Lê o arquivo de forma tolerante (linhas inválidas são ignoradas; leitura limitada)."""
    path = _path(session_dir)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning("Arquivo de sinalizações ilegível", extra={"extra": {"error": type(exc).__name__}})
        return []
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(_MAX_READ_BYTES)
    records: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _append(session_dir: Path, record: dict[str, Any]) -> None:
    """Acrescenta uma linha (``O_APPEND``: escrita única, atômica para linhas curtas; sem seguir link simbólico)."""
    data = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    fd = os.open(_path(session_dir), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as handle:
        handle.write(data)


def _clean_ref(ref: object) -> str:
    if not isinstance(ref, str):
        raise FlagError("cada item de 'refs' deve ser texto (ID de nó ou caminho de artefato).")
    cleaned = clean_free_text(ref)
    if not cleaned or len(cleaned) > MAX_REF_CHARS:
        raise FlagError(f"cada item de 'refs' deve ter de 1 a {MAX_REF_CHARS} caracteres.")
    return cleaned


def record_flag(
    session_dir: Path,
    *,
    agente: str,
    subtarefa: str,
    tipo: str,
    texto: str,
    refs: list[str] | None = None,
    max_flags: int | None = None,
) -> str:
    """Registra uma sinalização pendente para o Curator.

    Args:
        session_dir: Diretório de outputs da sessão (``outputs/<sessão>/``).
        agente: Papel que sinaliza (ex.: ``developer``).
        subtarefa: Nome da subtarefa corrente.
        tipo: Um de ``FLAG_TYPES``.
        texto: Descrição curta (até ``CURATOR_FLAG_MAX_CHARS``).
        refs: IDs de nós ou caminhos de artefatos da sessão (até ``MAX_REFS``).
        max_flags: Máximo de sinalizações por sessão (padrão ``CURATOR_MAX_FLAGS_PER_SESSION``).

    Returns:
        O ``id`` da sinalização.

    Raises:
        FlagError: ``tipo`` desconhecido, texto vazio ou longo demais, ``refs`` inválidos ou limite da sessão.
    """
    if tipo not in FLAG_TYPES:
        raise FlagError(f"tipo inválido; use um de {list(FLAG_TYPES)}.")
    if not isinstance(texto, str) or not texto.strip():
        raise FlagError("texto vazio.")
    cleaned = clean_free_text(texto)
    if len(cleaned) > config.CURATOR_FLAG_MAX_CHARS:
        raise FlagError(f"texto longo demais (máximo {config.CURATOR_FLAG_MAX_CHARS} caracteres).")
    if refs is None:
        refs = []
    if not isinstance(refs, list) or len(refs) > MAX_REFS:
        raise FlagError(f"'refs' deve ser uma lista de até {MAX_REFS} itens.")
    clean_refs = [_clean_ref(r) for r in refs]
    limit = config.CURATOR_MAX_FLAGS_PER_SESSION if max_flags is None else max_flags
    lines = _read_lines(session_dir)
    resolved_ids = {str(r["resolve"]) for r in lines if "resolve" in r}
    # A cota conta só as PENDENTES: sinalizações já decididas pelo Curator não bloqueiam as legítimas.
    if sum(1 for r in lines if "resolve" not in r and "id" in r and r["id"] not in resolved_ids) >= limit:
        raise FlagError(f"limite de {limit} sinalizações pendentes atingido.")
    flag_id = uuid.uuid4().hex[:12]
    _append(
        session_dir,
        {
            "id": flag_id,
            "tipo": tipo,
            "texto": cleaned,
            "refs": clean_refs,
            "agente": clean_free_text(str(agente))[:MAX_FIELD_CHARS],
            "subtarefa": clean_free_text(str(subtarefa))[:MAX_FIELD_CHARS],
            "criado_em": datetime.now(timezone.utc).isoformat(),
        },
    )
    return flag_id


class FlagStore:
    """Leitura das pendentes e marcação (``registrada``/``descartada``) pelo Curator."""

    def __init__(self, session_dir: Path) -> None:
        self._dir = Path(session_dir)

    def _all(self) -> tuple[list[Flag], dict[str, dict[str, Any]]]:
        flags: list[Flag] = []
        resolved: dict[str, dict[str, Any]] = {}
        for rec in _read_lines(self._dir):
            if "resolve" in rec:
                resolved.setdefault(str(rec["resolve"]), rec)
                continue
            if rec.get("tipo") not in FLAG_TYPES or not isinstance(rec.get("id"), str):
                continue
            refs = rec.get("refs") if isinstance(rec.get("refs"), list) else []
            flags.append(
                Flag(
                    id=rec["id"],
                    tipo=rec["tipo"],
                    texto=str(rec.get("texto", ""))[: config.CURATOR_FLAG_MAX_CHARS],
                    refs=tuple(str(r)[:MAX_REF_CHARS] for r in refs[:MAX_REFS]),
                    agente=str(rec.get("agente", ""))[:MAX_FIELD_CHARS],
                    subtarefa=str(rec.get("subtarefa", ""))[:MAX_FIELD_CHARS],
                    criado_em=str(rec.get("criado_em", "")),
                )
            )
        return flags, resolved

    def pending(self, limit: int = 50) -> list[Flag]:
        """Sinalizações ainda sem decisão do Curator, em ordem de chegada."""
        flags, resolved = self._all()
        return [f for f in flags if f.id not in resolved][: max(limit, 0)]

    def counts(self) -> dict[str, int]:
        """Contagens por estado (sem texto): ``pendente``, ``registrada``, ``descartada``."""
        flags, resolved = self._all()
        out = {"pendente": 0, ESTADO_REGISTRADA: 0, ESTADO_DESCARTADA: 0}
        for flag in flags:
            state = resolved.get(flag.id, {}).get("estado")
            out[state if state in out else "pendente"] += 1
        return out

    def resolve(self, flag_id: str, estado: str, motivo: str, no_id: str | None = None) -> None:
        """Marca uma sinalização pendente como ``registrada`` (com ``no_id``) ou ``descartada`` (com motivo).

        Raises:
            FlagError: Sinalização inexistente ou já decidida, estado inválido, ``motivo`` ausente/longo ou
                ``no_id`` ausente em ``registrada``.
        """
        if estado not in (ESTADO_REGISTRADA, ESTADO_DESCARTADA):
            raise FlagError("estado inválido; use 'registrada' ou 'descartada'.")
        reason = clean_free_text(motivo) if isinstance(motivo, str) else ""
        if not reason or len(reason) > _MAX_RESOLUTION_REASON:
            raise FlagError(f"informe o motivo (1 a {_MAX_RESOLUTION_REASON} caracteres).")
        node = clean_free_text(no_id) if isinstance(no_id, str) else ""
        if estado == ESTADO_REGISTRADA and (not node or len(node) > MAX_FIELD_CHARS):
            raise FlagError("'registrada' exige o ID do nó criado ou reforçado (no_id).")
        flags, resolved = self._all()
        if flag_id not in {f.id for f in flags}:
            raise FlagError("sinalização inexistente.")
        if flag_id in resolved:
            raise FlagError("sinalização já decidida.")
        _append(
            self._dir,
            {
                "resolve": flag_id,
                "estado": estado,
                "motivo": reason,
                "no_id": node or None,
                "resolvido_em": datetime.now(timezone.utc).isoformat(),
            },
        )
