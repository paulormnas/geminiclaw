"""Constantes, limites, estatísticas e utilitários de dados do Curator (``v17-curator-agent``).

Parte do módulo ``curator_tools`` dividido por responsabilidade (8.4): ver ``curator_tools.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.knowledge.curator_flags import (
    ESTADO_DESCARTADA,
    ESTADO_REGISTRADA,
)
from src.knowledge.graph_store import Node
from src.logger import get_logger

logger = get_logger(__name__)


DATA_TAG = "dado_nao_confiavel"
AUDIT_FILENAME = "curator_audit.jsonl"

DISCOVERY_TYPES = ("funciona", "nao_funciona", "condicional", "licao_de_caminho")
EVIDENCE_LABELS = ("Resultado", "Experimento", "Decisao")
SOBRE_LABELS = ("Abordagem", "Problema", "Hipotese")
FLAG_DECISIONS = (ESTADO_REGISTRADA, ESTADO_DESCARTADA)

_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_IDS = 20
_MAX_DATASET_FILTER = 20
_MAX_FILTER_VALUE_CHARS = 128
_MAX_ROWS = 50
_MAX_VALUE_CHARS = 500
_MAX_AUDIT_REASON = 300
_FILTER_KEYS = ("dataset_ids", "no_execucao")
_STATUS_DISCOVERY = ("contestada", "substituida")
# Campos de texto que podem citar números: cada um passa pela conferência das referências numéricas.
_NUMERIC_TEXT_FIELDS = frozenset(
    {
        "enunciado", "condicoes", "justificativa", "diferenca", "condicoes_extra", "ponto_de_parada",
        "proximo_passo_sugerido",
    }
)
_QUEUE_OVERFETCH = 5


class CuratorToolError(Exception):
    """Argumento inválido ou operação indisponível; a mensagem volta ao modelo (sem eco de texto longo)."""


@dataclass(frozen=True)
class CuratorLimits:
    """Orçamento e tamanhos por execução do Curator (valores de ``src/config.py``)."""

    max_writes: int
    max_read_queries: int
    max_text_chars: int
    max_output_chars: int
    queue_batch: int

    @classmethod
    def from_config(cls) -> "CuratorLimits":
        return cls(
            max_writes=config.CURATOR_MAX_WRITES_PER_RUN,
            max_read_queries=config.CURATOR_MAX_READ_QUERIES_PER_RUN,
            max_text_chars=config.CURATOR_MAX_TEXT_CHARS,
            max_output_chars=config.CURATOR_MAX_TOOL_OUTPUT_CHARS,
            queue_batch=config.CURATOR_QUEUE_BATCH,
        )


@dataclass
class CuratorStats:
    """Contagens da execução (vão para a telemetria; nunca texto)."""

    criados: int = 0
    reforcados: int = 0
    descartados: int = 0
    recusas: int = 0
    escritas: int = 0
    consultas_livres: int = 0
    pares_revisados: int = 0
    pares_servidos: int = 0
    mudancas_de_status: int = 0


@dataclass
class _Review:
    """Resultado da revisão de duplicatas antes de criar."""

    consultados: list[str] = field(default_factory=list)
    duplicatas: list[tuple[str, float | None]] = field(default_factory=list)
    relacionados: list[tuple[str, float | None]] = field(default_factory=list)


_DATA_TAG_RE = re.compile(r"<(?=\s*/?\s*" + DATA_TAG + r")", re.IGNORECASE)


def wrap_data(origem: str, payload: Any, limit: int) -> str:
    """Serializa ``payload`` e o entrega entre delimitadores, como dado não confiável (limite em caracteres).

    O fechamento ``</dado_nao_confiavel`` dentro do conteúdo é neutralizado, para que texto vindo de nós, arquivos ou
    sinalizações não consiga "sair" do bloco e se passar por instrução.
    """
    text = json.dumps(payload, ensure_ascii=False, default=str)
    text = _DATA_TAG_RE.sub("&lt;", text)
    if len(text) > limit:
        text = text[: max(limit - 1, 0)] + "…"
    return f'<{DATA_TAG} origem="{origem}">\n{text}\n</{DATA_TAG}>'


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Funções e predicados sobre texto: viram oráculo (``length(n.texto) > 5``, ``STARTS WITH``) mesmo com a saída filtrada.
_TEXT_ORACLE_RE = re.compile(
    r"\b(length|size|char_length|starts\s+with|ends\s+with|contains|toLower|toUpper|substring|left|right|trim|"
    r"ltrim|rtrim|split|replace|reverse|ascii|toString|keys|properties|labels|in)\b|=~",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
OMITTED = "[omitido]"


def _safe_param(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return bool(_UUID_RE.fullmatch(value)) or value == ""
    if isinstance(value, (list, tuple)):
        return all(_safe_param(v) for v in value)
    return False


def _only_ids_and_numbers(value: Any) -> Any:
    """Mantém números, booleanos, ``None`` e UUIDs; troca todo outro texto por ``[omitido]`` (recursivo)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if _UUID_RE.fullmatch(value) else OMITTED
    if isinstance(value, dict):
        return {str(k)[:60]: _only_ids_and_numbers(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_only_ids_and_numbers(v) for v in list(value)[:50]]
    return OMITTED


def _clip(value: Any, limit: int = _MAX_VALUE_CHARS) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, dict):
        return {str(k): _clip(v, limit) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_clip(v, limit) for v in list(value)[:50]]
    return value


_HIDDEN_PROPERTIES = frozenset({"estado_vetorizacao", "versao_schema", "origem_no"})


def node_view(node: Node) -> dict[str, Any]:
    """Visão compacta de um nó para o modelo: ``id``, ``label`` e propriedades (textos cortados)."""
    return {
        "id": node.id,
        "label": node.label,
        "propriedades": {k: _clip(v) for k, v in node.properties.items() if k not in _HIDDEN_PROPERTIES},
    }


def _short_text(node: Node) -> str:
    for key in ("enunciado", "nome", "titulo", "termo", "contexto"):
        value = node.properties.get(key)
        if isinstance(value, str) and value:
            return str(_clip(value, 200))
    return ""


