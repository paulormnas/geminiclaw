"""Apelido da pesquisa (v18.7-background-sessions, design §1.9).

``<slug do projeto, [a-z0-9], até 12 caracteres>-<NN>``, com ``NN`` o menor número de dois dígitos sem uso no
projeto; sem projeto, ``sessao-NN``. A retomada herda o apelido da cadeia. O índice do banco não é único, porque a
cadeia compartilha o apelido.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

ALIAS_SLUG_MAX = 12
NO_PROJECT_SLUG = "sessao"
_ALIAS_RE = re.compile(r"^([a-z0-9]{1,12})-(\d{2,})$")


def slugify(name: str | None) -> str:
    """Nome do projeto em ``[a-z0-9]``, sem acentos, até ``ALIAS_SLUG_MAX`` caracteres; vazio vira ``sessao``."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "", ascii_name.lower())[:ALIAS_SLUG_MAX]
    return slug or NO_PROJECT_SLUG


def next_alias(project_name: str | None, used: Iterable[str | None]) -> str:
    """Menor ``<slug>-NN`` que não está em ``used`` (apelidos já gravados no mesmo projeto)."""
    slug = slugify(project_name)
    taken = {u for u in used if u}
    number = 1
    while f"{slug}-{number:02d}" in taken:
        number += 1
    return f"{slug}-{number:02d}"


def is_alias(text: str) -> bool:
    """O texto tem a forma de um apelido (``<slug>-NN``)."""
    return bool(_ALIAS_RE.match(text or ""))
