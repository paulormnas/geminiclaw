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

import dataclasses
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

# Fonte dos trechos com nomes de artefatos: o EgressGate aplica a regra de nomes (design §3.5) a eles.
ARTIFACT_NAMES_SOURCE = "artefatos"

ORIGIN_INSTRUCAO_VALUE = ContentOrigin.INSTRUCAO.value
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


class ToolOutput(str):
    """Resultado textual de uma ferramenta com a origem do conteúdo (v18.5-egress-gate, design §1).

    É uma ``str`` (código que não conhece os rótulos a trata como texto); o laço do agente lê ``origin``,
    ``source`` e ``integral_path`` para rotular o trecho.
    """

    origin: "ContentOrigin | None"
    source: str | None
    integral_path: str | None
    tainted: bool

    def __new__(
        cls,
        text: str,
        origin: "ContentOrigin | None" = None,
        source: str | None = None,
        integral_path: str | None = None,
        tainted: bool = False,
    ) -> "ToolOutput":
        obj = super().__new__(cls, text)
        obj.origin = origin
        obj.source = source
        obj.integral_path = integral_path
        obj.tainted = tainted
        return obj


# Origem do resultado de cada ferramenta conhecida; ferramenta desconhecida: o tratamento mais restritivo.
TOOL_ORIGINS: dict[str, ContentOrigin] = {
    "python_interpreter": ContentOrigin.SAIDA_EXECUCAO,
    "quick_search": ContentOrigin.DOCUMENTO,
    "deep_search": ContentOrigin.DOCUMENTO,
    "web_reader": ContentOrigin.DOCUMENTO,
    "document_processor": ContentOrigin.DOCUMENTO,
    "memory": ContentOrigin.GRAFO,
    "buscar_dominio": ContentOrigin.GRAFO,
}
DEFAULT_TOOL_ORIGIN = ContentOrigin.SAIDA_EXECUCAO


def tool_result_fragment(
    tool_name: str, result: str, arguments: dict[str, Any] | None = None, *, tainted: bool = False
) -> PromptFragment:
    """Trecho rotulado do resultado de uma ferramenta (origem pela ferramenta; ``ToolOutput`` a refina)."""
    origin = TOOL_ORIGINS.get(tool_name, DEFAULT_TOOL_ORIGIN)
    source: str | None = None
    integral: str | None = None
    if isinstance(result, ToolOutput):
        origin = result.origin or origin
        source = result.source
        integral = result.integral_path
        tainted = tainted or result.tainted
    if source is None:
        args = arguments or {}
        if tool_name == "web_reader" and isinstance(args.get("url"), str):
            source = f"web:{args['url']}"
        elif tool_name == "quick_search" and isinstance(args.get("query"), str):
            source = f"busca:{args['query'][:120]}"
        else:
            source = f"ferramenta:{tool_name}"
    return PromptFragment(str(result), origin, tainted=tainted, source=source, integral_path=integral)


def message_to_fragments(message: dict[str, Any]) -> list[PromptFragment]:
    """Trechos de uma mensagem para reaproveitá-la em outro prompt (ex.: resumo do histórico).

    Mensagem sem rótulo vira ``saida_execucao`` contaminada (o lado seguro), como no ``EgressGate``.
    """
    labeled_fragments = message_fragments(message)
    if labeled_fragments is not None:
        result = list(labeled_fragments)
    else:
        content = message.get("content")
        result = (
            [PromptFragment(content, ContentOrigin.SAIDA_EXECUCAO, tainted=True, source="sem_rotulo")]
            if isinstance(content, str) and content
            else []
        )
    calls = message.get("tool_calls")
    if calls:
        tainted = bool(message.get(TOOL_CALLS_TAINTED_KEY, True))
        result.append(PromptFragment(dumps_messages(calls), ContentOrigin.CODIGO, tainted=tainted))
    return result


def truncate_message(message: dict[str, Any], limit_chars: int, suffix: str = "... [truncado]") -> dict[str, Any]:
    """Cópia da mensagem com o texto limitado a ``limit_chars``, mantendo a origem de cada trecho que sobrar."""
    copy_ = dict(message)
    fragments = message_fragments(message)
    if fragments is None:
        content = message.get("content", "")
        if isinstance(content, str):
            copy_["content"] = content[:limit_chars] + suffix
        return copy_
    kept: list[PromptFragment] = []
    remaining = max(limit_chars, 0)
    for frag in fragments:
        if remaining <= 0:
            break
        if len(frag.text) <= remaining:
            kept.append(frag)
            remaining -= len(frag.text) + len(FRAGMENT_SEPARATOR)
        else:
            kept.append(dataclasses.replace(frag, text=frag.text[:remaining] + suffix))
            remaining = 0
    copy_[FRAGMENTS_KEY] = kept
    copy_["content"] = plain_text(kept)
    return copy_


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


# --- Marcas em linha ---------------------------------------------------------------------------------------------
#
# Carregam a origem por concatenações de strings (instrução do papel, prompt de subtarefa, resumos persistidos) até
# o ``EgressGate``, que as converte em trechos rotulados e as remove antes do envio:
#   ⟦T⟧...⟦/T⟧          texto contaminado (produzido por modelo com aceita_dados_brutos)
#   ⟦D:<fonte>⟧...⟦/D⟧  dado de pesquisa (ex.: bloco de input_context/)
#   ⟦S:<fonte>⟧...⟦/S⟧  saída de execução (ex.: metrics.json na síntese)

TAINT_OPEN = "\u27e6T\u27e7"  # ⟦T⟧
TAINT_CLOSE = "\u27e6/T\u27e7"  # ⟦/T⟧
DATA_CLOSE = "\u27e6/D\u27e7"  # ⟦/D⟧
_DATA_OPEN_PREFIX = "\u27e6D:"  # ⟦D:
_MARK_CHARS = "\u27e6\u27e7"
_KIND_ORIGIN = {"D": ContentOrigin.DADO_DE_PESQUISA, "S": ContentOrigin.SAIDA_EXECUCAO}
_MARKED_RE = re.compile(
    re.escape(TAINT_OPEN) + r"(?P<t>.*?)" + re.escape(TAINT_CLOSE)
    + r"|\u27e6(?P<k>[DS]):(?P<src>[^\u27e7]*)\u27e7(?P<body>.*?)\u27e6/(?P=k)\u27e7",
    re.DOTALL,
)
_ANY_MARK_RE = re.compile(
    re.escape(TAINT_OPEN) + "|" + re.escape(TAINT_CLOSE) + r"|\u27e6/[DS]\u27e7|\u27e6[DS]:[^\u27e7]*\u27e7"
)
_OPEN_MARK_RE = re.compile(re.escape(TAINT_OPEN) + r"|\u27e6[DS]:[^\u27e7]*\u27e7")


def strip_marks(text: str) -> str:
    """Remove as marcas em linha (o texto interno é preservado)."""
    # Até o ponto fixo: uma passada só deixaria "⟦⟦/T⟧/T⟧" virar uma marca válida (forjável).
    while True:
        cleaned = _ANY_MARK_RE.sub("", text)
        if cleaned == text:
            return cleaned
        text = cleaned


strip_taint_marks = strip_marks


def mark_tainted(text: str) -> str:
    """Envolve ``text`` na marca de contaminação. Marcas já presentes no texto são removidas (anti-falsificação)."""
    if not text:
        return text
    return f"{TAINT_OPEN}{strip_marks(text)}{TAINT_CLOSE}"


def taint_if(text: str, tainted: bool) -> str:
    """``mark_tainted(text)`` quando ``tainted``; senão o próprio texto."""
    return mark_tainted(text) if tainted else text


def _mark_origin(text: str, kind: str, source: str) -> str:
    if not text:
        return text
    clean_source = "".join(c for c in source if c not in _MARK_CHARS and c not in "\r\n")[:200]
    return f"\u27e6{kind}:{clean_source}\u27e7{strip_marks(text)}\u27e6/{kind}\u27e7"


def mark_research_data(text: str, source: str) -> str:
    """Envolve ``text`` na marca de dado de pesquisa de ``source`` (ex.: ``input_context/``)."""
    return _mark_origin(text, "D", source)


def mark_execution_output(text: str, source: str) -> str:
    """Envolve ``text`` na marca de saída de execução de ``source`` (ex.: ``metrics.json``)."""
    return _mark_origin(text, "S", source)


def expand_marks(text: str, base: PromptFragment) -> list[PromptFragment]:
    """Divide ``text`` em trechos conforme as marcas em linha, herdando de ``base`` o que a marca não altera.

    Marca sem par é falha para o lado seguro: o texto após uma abertura sem fechamento é tratado como contaminado
    (``⟦T⟧``) ou com a origem da marca (``⟦D:``/``⟦S:``).
    """
    pieces: list[PromptFragment] = []

    def add(chunk: str, **changes: Any) -> None:
        chunk = strip_marks(chunk)
        if chunk:
            pieces.append(dataclasses.replace(base, text=chunk, **changes))

    pos = 0
    for match in _MARKED_RE.finditer(text):
        add(text[pos : match.start()])
        if match.group("t") is not None:
            add(match.group("t"), tainted=True)
        else:
            add(match.group("body"), origin=_KIND_ORIGIN[match.group("k")], source=match.group("src") or base.source)
        pos = match.end()
    tail = text[pos:]
    opened = _OPEN_MARK_RE.search(tail)
    if opened is None:
        add(tail)
    else:
        add(tail[: opened.start()])
        rest = tail[opened.end() :]
        token = opened.group(0)
        if token == TAINT_OPEN:
            add(rest, tainted=True)
        else:
            add(rest, origin=_KIND_ORIGIN[token[1]], source=token[3:-1] or base.source)
    return pieces
