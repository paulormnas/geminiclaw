"""Adendo de projeto ao regimento: leitura única, formato fechado e pedido de ativação (ADR 022 §4.4; design §5).

O adendo é um arquivo do pesquisador (``REGIMENTO_ADDENDUM_FILE``, nos insumos) que só acrescenta regras e proibições
ao recorte. Ele não muda nada que o código aplica (paradas, limites, integridade). Só é injetado quando o pesquisador
aprovou o sha256 dos bytes pela decisão reservada ``ativar_adendo_regimento``; a prova é um pedido em ``gate_requests``,
nunca uma cópia no projeto.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src import config
from src.logger import get_logger
from src.utils.display_text import sanitize_line

logger = get_logger(__name__)

DECISAO = "ativar_adendo_regimento"
ALLOWED_KEYS = frozenset({"versao", "regras", "proibicoes"})
ITEM_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
ITEM_TEXT_MAX = 500
FILE_MAX_BYTES = 64 * 1024
TITULO = "Regras adicionais do projeto"
LINHA_EGRESSO = "Depois de aprovado, o adendo é enviado como instrução a todos os provedores da sessão."
_CLASSES = ("motivo de parada", "limite", "regra de integridade")
_WORD_RE = re.compile(r"[a-z][a-z0-9_]*")


class AdendoError(ValueError):
    """Adendo inválido (formato, link simbólico, tamanho) ou aprovação impossível de conferir."""


@dataclass(frozen=True)
class ItemAdendo:
    id: str
    texto: str


@dataclass(frozen=True)
class Adendo:
    """Adendo lido e validado, com o sha256 dos bytes que foram lidos."""

    sha256: str
    versao: int
    regras: tuple[ItemAdendo, ...]
    proibicoes: tuple[ItemAdendo, ...]

    def renderizar(self) -> str:
        """Texto injetado no fim do recorte, sob o título ``Regras adicionais do projeto``."""
        blocos = [f"## {TITULO}"]
        if self.regras:
            blocos.append("Regras:\n" + "\n".join(f"- {i.id}: {i.texto}" for i in self.regras))
        if self.proibicoes:
            blocos.append("Proibições:\n" + "\n".join(f"- {i.id}: {i.texto}" for i in self.proibicoes))
        return "\n\n".join(blocos)


def _items(raw: Any, chave: str) -> tuple[ItemAdendo, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AdendoError(f"'{chave}' deve ser uma lista de itens com 'id' e 'texto'.")
    out: list[ItemAdendo] = []
    for pos, item in enumerate(raw, 1):
        if not isinstance(item, dict) or set(item) != {"id", "texto"}:
            raise AdendoError(f"item {pos} de '{chave}' deve ter exatamente as chaves 'id' e 'texto'.")
        ident, texto = item["id"], item["texto"]
        if not isinstance(ident, str) or not ITEM_ID_RE.match(ident):
            raise AdendoError(f"item {pos} de '{chave}': 'id' deve casar com {ITEM_ID_RE.pattern}.")
        if not isinstance(texto, str) or not texto.strip():
            raise AdendoError(f"item '{ident}' de '{chave}': 'texto' deve ser um texto não vazio.")
        limpo = sanitize_line(texto, 0)
        if limpo != texto.strip() or len(limpo) > ITEM_TEXT_MAX:
            raise AdendoError(
                f"item '{ident}' de '{chave}': 'texto' deve ter uma linha, sem caracteres de controle, "
                f"com até {ITEM_TEXT_MAX} caracteres."
            )
        out.append(ItemAdendo(ident, limpo))
    return tuple(out)


def parse_adendo(data: bytes) -> Adendo:
    """Valida o formato fechado dos bytes lidos e calcula o sha256 deles."""
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise AdendoError(f"o adendo não é um YAML válido em UTF-8: {type(exc).__name__}.") from exc
    if not isinstance(parsed, dict):
        raise AdendoError("o adendo deve ser um mapa com as chaves 'versao', 'regras' e 'proibicoes'.")
    extras = sorted(str(k) for k in parsed if k not in ALLOWED_KEYS)
    if extras:
        raise AdendoError(
            f"chave fora do formato do adendo: {', '.join(extras)}. Só 'versao', 'regras' e 'proibicoes' são aceitas; "
            "o adendo só acrescenta regras e proibições."
        )
    if not isinstance(parsed.get("versao"), int) or isinstance(parsed.get("versao"), bool):
        raise AdendoError("o adendo deve ter 'versao' inteira.")
    regras, proibicoes = _items(parsed.get("regras"), "regras"), _items(parsed.get("proibicoes"), "proibicoes")
    if not regras and not proibicoes:
        raise AdendoError("o adendo não tem nenhuma regra nem proibição.")
    ids = [i.id for i in (*regras, *proibicoes)]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise AdendoError(f"ids repetidos no adendo: {', '.join(repetidos)}.")
    return Adendo(hashlib.sha256(data).hexdigest(), int(parsed["versao"]), regras, proibicoes)


def ler_adendo(diretorio: str | Path, nome: str | None = None) -> Adendo | None:
    """Lê o adendo uma única vez, sem seguir link simbólico; ``None`` se o arquivo não existe.

    Raises:
        AdendoError: link simbólico, arquivo que não é comum, grande demais ou fora do formato.
    """
    arquivo = Path(diretorio) / (nome or config.REGIMENTO_ADDENDUM_FILE)
    if not os.path.lexists(arquivo):
        return None
    try:
        fd = os.open(arquivo, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise AdendoError(
                f"{arquivo.name} é um link simbólico; o adendo precisa ser um arquivo comum dentro dos insumos."
            ) from exc
        raise AdendoError(f"não foi possível ler {arquivo.name}: {exc.strerror}.") from exc
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise AdendoError(f"{arquivo.name} não é um arquivo comum.")
        if info.st_size > FILE_MAX_BYTES:
            raise AdendoError(f"{arquivo.name} passa de {FILE_MAX_BYTES} bytes.")
        data = handle.read(FILE_MAX_BYTES + 1)
    return parse_adendo(data)


def ids_citados(adendo: Adendo, estrutura: dict[str, Any]) -> dict[str, list[str]]:
    """Ids de parada, de limite e de integridade da parte estruturada que o texto do adendo cita."""
    paradas = {m["id"] for m in estrutura["motivos_parada"]}
    classes = {
        "motivo de parada": {i for i in paradas if not i.startswith("limite_")},
        "limite": {i for i in paradas if i.startswith("limite_")},
        "regra de integridade": {r["id"] for r in estrutura["regras_integridade"]},
    }
    palavras: set[str] = set()
    for item in (*adendo.regras, *adendo.proibicoes):
        palavras.update(_WORD_RE.findall(item.texto.lower()))
    return {c: sorted(classes[c] & palavras) for c in _CLASSES if classes[c] & palavras}


def pedido_de_ativacao(adendo: Adendo, estrutura: dict[str, Any], limite: int | None = None) -> str:
    """Texto do pedido ``ativar_adendo_regimento``: o adendo, o hash, a linha sobre egresso e os avisos.

    Raises:
        AdendoError: o texto passa do que o pedido ao pesquisador comporta (não é truncado).
    """
    linhas = [f"Ativar o adendo de regras do projeto (sha256 {adendo.sha256})."]
    corpo = adendo.renderizar().split("\n", 1)[1]
    linhas.append(corpo)
    linhas.append(LINHA_EGRESSO)
    for classe, ids in ids_citados(adendo, estrutura).items():
        linhas.append(
            f"Aviso: o adendo cita {', '.join(ids)} ({classe}). Confira se o texto afrouxa alguma regra; "
            "o adendo nunca desliga paradas, limites nem regras de integridade."
        )
    texto = sanitize_line("\n".join(linhas), 0)
    teto = int(limite if limite is not None else config.GATE_QUESTION_MAX_CHARS)
    if len(texto) > teto:
        raise AdendoError(
            f"o adendo é grande demais para o pedido de aprovação ({len(texto)} caracteres, o pedido comporta {teto}); "
            "encurte os textos para o pesquisador poder lê-lo inteiro antes de aprovar."
        )
    return texto


def aprovado(gate: Any, adendo: Adendo) -> bool:
    """O sha256 dos bytes lidos tem pedido ``autorizada`` por origem humana em ``gate_requests`` (sem consumo)."""
    return bool(gate.authorized_reference(DECISAO, adendo.sha256))


def registrar_pedido(
    gate: Any, adendo: Adendo, estrutura: dict[str, Any], *, session_id: str | None, project_id: str | None
) -> None:
    """Cria (idempotente) o pedido de ativação do adendo; pedido já no limite da sessão não é erro."""
    from src.gate.types import GatePendingLimitReached

    pergunta = pedido_de_ativacao(adendo, estrutura)
    try:
        gate.request(DECISAO, adendo.sha256, pergunta, session_id=session_id, project_id=project_id)
    except GatePendingLimitReached:
        logger.warning("Pedido do adendo não criado: limite de pendentes da sessão", extra={"sha256": adendo.sha256})


def nomes(itens: Iterable[ItemAdendo]) -> list[str]:
    return [i.id for i in itens]
