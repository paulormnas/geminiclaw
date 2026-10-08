"""Serialização canônica e hash dos registros de execução (design §1).

``record_hash = sha256(canonical(registro))``. Números de ponto flutuante são **proibidos** no registro: valores de
métricas entram como texto (``repr(float)``, ``"nan"``, ``"inf"``) para que o hash não dependa da formatação de floats.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

ZERO_HASH = "0" * 64
RECORD_FORMAT = 1


class CanonicalError(ValueError):
    """O objeto não pode ser serializado de forma canônica (ex.: contém ``float``)."""


def _reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise CanonicalError(f"float proibido no registro em {path}: grave o valor como texto.")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"chave não textual em {path}: {key!r}")
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def canonical(obj: Any) -> bytes:
    """Bytes UTF-8 da serialização canônica de ``obj``.

    Raises:
        CanonicalError: ``obj`` contém ``float`` ou chave que não é texto.
    """
    _reject_floats(obj)
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8")


def record_hash(record: dict[str, Any]) -> str:
    """sha256 (hex) do registro canônico."""
    return hashlib.sha256(canonical(record)).hexdigest()


def metric_text(value: Any) -> str | None:
    """Texto de uma métrica numérica (``repr`` do float; ``"nan"``/``"inf"``); ``None`` se não for número."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_sha256(value: Any) -> str:
    """sha256 do JSON canônico de ``value`` (floats aceitos aqui: é o hash de ``params``, não do registro)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return sha256_text(text)
