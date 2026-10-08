"""Trechos de prompt rotulados por origem (v18.5-egress-gate, design §1).

Cada trecho que entra num prompt carrega a sua origem (:class:`ContentOrigin`), a marca de contaminação
(``tainted``) e a marca ``compartilhavel``. Uma mensagem rotulada é o ``dict`` do formato atual com a chave extra
``_fragments``; ``content`` continua presente (texto plano derivado) para que o código que não conhece os rótulos
funcione, e nenhum provedor vê ``_fragments``: o ``EgressGate`` os remove ao renderizar.

Este módulo também define a *marca de texto contaminado em linha* (``⟦T⟧...⟦/T⟧``), que acompanha o texto por
concatenações de strings (instrução do papel, resumos persistidos) até o ``EgressGate``, que a converte em trechos
``tainted`` e a remove antes do envio.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence


class ContentOrigin(str, Enum):
    """Origem de um trecho de prompt (ADR 019 §3.5)."""

    INSTRUCAO = "instrucao"
    DOCUMENTO = "documento"
    ESQUEMA_AGREGADO = "esquema_agregado"
    CODIGO = "codigo"
    SAIDA_EXECUCAO = "saida_execucao"
    GRAFO = "grafo"
    DADO_DE_PESQUISA = "dado_de_pesquisa"


# Origens cujo conteúdo é material observado: sempre vai delimitado como dado (design §5).
OBSERVED_ORIGINS: frozenset[ContentOrigin] = frozenset(
    {
        ContentOrigin.DOCUMENTO,
        ContentOrigin.SAIDA_EXECUCAO,
        ContentOrigin.GRAFO,
        ContentOrigin.DADO_DE_PESQUISA,
    }
)

FRAGMENTS_KEY = "_fragments"
TOOL_CALLS_TAINTED_KEY = "_tool_calls_tainted"
FRAGMENT_SEPARATOR = "\n"


@dataclass(frozen=True)
class PromptFragment:
    """Trecho de prompt com origem e marcas (design §1)."""

    text: str
    origin: ContentOrigin
    tainted: bool = False  # produzido por modelo com aceita_dados_brutos
    compartilhavel: bool = False  # só para dado_de_pesquisa marcado pelo pesquisador
    source: str | None = None  # "input_context/x.csv", "step_03:stdout", "web:<url>"...
    produced_by: str | None = None  # papel que produziu o texto, quando é saída de modelo
    # Caminho (no nó) da saída integral, citado nos avisos de retenção e elisão.
    integral_path: str | None = None


def fragment(
    text: str,
    origin: ContentOrigin,
    *,
    tainted: bool = False,
    compartilhavel: bool = False,
    source: str | None = None,
    produced_by: str | None = None,
    integral_path: str | None = None,
) -> PromptFragment:
    """Atalho para construir um :class:`PromptFragment`."""
    return PromptFragment(
        text=text,
        origin=origin,
        tainted=tainted,
        compartilhavel=compartilhavel,
        source=source,
        produced_by=produced_by,
        integral_path=integral_path,
    )


def labeled(role: str, *fragments: PromptFragment, **extra: Any) -> dict[str, Any]:
    """Monta uma mensagem rotulada: ``content`` plano derivado e ``_fragments`` com os trechos."""
    if not fragments:
        raise ValueError("labeled() exige ao menos um trecho.")
    message: dict[str, Any] = {
        "role": role,
        "content": plain_text(fragments),
        FRAGMENTS_KEY: list(fragments),
    }
    message.update(extra)
    return message


def plain_text(fragments: Iterable[PromptFragment]) -> str:
    """Texto plano (sem delimitadores) de uma sequência de trechos."""
    return FRAGMENT_SEPARATOR.join(strip_taint_marks(f.text) for f in fragments)


def message_fragments(message: dict[str, Any]) -> list[PromptFragment] | None:
    """Trechos rotulados da mensagem, ou ``None`` se ela não tem rótulo."""
    raw = message.get(FRAGMENTS_KEY)
    if raw is None:
        return None
    return list(raw)


def message_text(message: dict[str, Any]) -> str:
    """Texto plano de uma mensagem (rotulada ou não), para estimativas de tamanho."""
    fragments = message_fragments(message)
    if fragments is not None:
        return plain_text(fragments)
    content = message.get("content")
    return content if isinstance(content, str) else ""


def json_default(obj: Any) -> Any:
    """``default`` para ``json.dumps`` de mensagens que carregam :class:`PromptFragment`."""
    if isinstance(obj, PromptFragment):
        return {"text": obj.text, "origin": obj.origin.value, "tainted": obj.tainted}
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Objeto do tipo {type(obj).__name__} não é serializável em JSON.")


def dumps_messages(messages: Sequence[dict[str, Any]] | dict[str, Any]) -> str:
    """``json.dumps`` seguro para mensagens com ``_fragments`` (estimativas de tamanho e telemetria)."""
    return json.dumps(messages, ensure_ascii=False, default=json_default)


def public_message(message: dict[str, Any]) -> dict[str, Any]:
    """Cópia da mensagem sem as chaves internas (iniciadas por ``_``)."""
    return {k: v for k, v in message.items() if not k.startswith("_")}


# --- Marca de texto contaminado em linha ------------------------------------------------------------------------

TAINT_OPEN = "⟦T⟧"  # ⟦T⟧
TAINT_CLOSE = "⟦/T⟧"  # ⟦/T⟧
_TAINT_SPAN_RE = re.compile(re.escape(TAINT_OPEN) + r"(.*?)" + re.escape(TAINT_CLOSE), re.DOTALL)
_TAINT_ANY_RE = re.compile(re.escape(TAINT_OPEN) + "|" + re.escape(TAINT_CLOSE))


def strip_taint_marks(text: str) -> str:
    """Remove as marcas de contaminação em linha (o texto interno é preservado)."""
    return _TAINT_ANY_RE.sub("", text)


def mark_tainted(text: str) -> str:
    """Envolve ``text`` na marca de contaminação. Marcas já presentes no texto são removidas (anti-falsificação)."""
    if not text:
        return text
    return f"{TAINT_OPEN}{strip_taint_marks(text)}{TAINT_CLOSE}"


def split_taint_spans(text: str) -> list[tuple[str, bool]]:
    """Divide ``text`` em pedaços ``(texto, contaminado)``. Marca sem par é ignorada (falha para o lado seguro:
    texto após uma abertura sem fechamento é tratado como contaminado)."""
    parts: list[tuple[str, bool]] = []
    pos = 0
    for match in _TAINT_SPAN_RE.finditer(text):
        if match.start() > pos:
            parts.append((text[pos : match.start()], False))
        parts.append((match.group(1), True))
        pos = match.end()
    tail = text[pos:]
    if tail:
        open_at = tail.find(TAINT_OPEN)
        if open_at == -1:
            parts.append((strip_taint_marks(tail), False))
        else:
            if open_at > 0:
                parts.append((strip_taint_marks(tail[:open_at]), False))
            parts.append((strip_taint_marks(tail[open_at + len(TAINT_OPEN) :]), True))
    return [(strip_taint_marks(t), tainted) for t, tainted in parts if t]
