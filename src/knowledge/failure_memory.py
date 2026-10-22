"""Memória de falhas do projeto, apresentada ao Developer antes de cada subtarefa de código (ADR 026 §5).

Um registro global das falhas já vistas e de como foram corrigidas evita que o mesmo erro se repita: em
"Recovering Wasted Compute in Autoresearch Agents" (COLM 2026) ele levou as execuções válidas de 81% para 100% e as
falhas repetidas de 46% para 7,8%. Tudo aqui é determinístico (sem LLM): os itens saem das assinaturas de falha que o
orquestrador grava nos ``Experimento`` (``failure_cause.classify_failure``) e o texto segue um modelo fixo, sem
resumo de LLM nem texto livre do sandbox.

Separa dois escopos. ``ambiente`` reúne as falhas que não dependem do método (pacotes, memória, tempo e o contrato de
``metrics.json``). O escopo de cada abordagem reúne as demais falhas de código, como o tipo da exceção.
``criterio_nao_atendido`` não entra: não é erro, é resultado, e já está nos registros de resultado.
"""

from __future__ import annotations

from dataclasses import dataclass

from src import config
from src.knowledge.failure_cause import (
    CAUSA_ABORDAGEM,
    SIG_INSTALACAO_PACOTES,
    SIG_OOM,
    SIG_SEM_METRICAS,
    SIG_TIMEOUT,
)
from src.knowledge.graph_store import GraphStore, Node

ESCOPO_AMBIENTE = "ambiente"
_AMBIENTE = frozenset({SIG_INSTALACAO_PACOTES, SIG_OOM, SIG_TIMEOUT, SIG_SEM_METRICAS})
_MAX_EXPERIMENTS = 1000
_MAX_DIFF_KEYS = 3
_NO_CORRECTION = "sem correção conhecida"


@dataclass(frozen=True)
class FailureItem:
    """Uma falha recorrente do projeto.

    Attributes:
        escopo: ``ambiente`` ou o nome da abordagem.
        assinatura: Assinatura da falha (``oom``, ``instalacao_pacotes``, tipo da exceção...).
        ocorrencias: Quantas vezes ocorreu no projeto.
        correcao: Diferença de configuração do experimento seguinte, na mesma abordagem, que terminou com métrica
            (``chave=valor`` separados por vírgula), ou ``None`` quando não há correção conhecida.
    """

    escopo: str
    assinatura: str
    ocorrencias: int
    correcao: str | None


def _approach_of(store: GraphStore, exp: Node) -> tuple[str | None, dict]:
    """Nome da abordagem aplicada e a configuração normalizada do experimento (aresta ``APLICOU``)."""
    sub = store.neighbors(exp.id, ["APLICOU"], direction="out", depth=1)
    by_id = {n.id: n for n in sub.nodes}
    for edge in sub.edges:
        if edge.src_id == exp.id and edge.rel_type == "APLICOU" and edge.dst_id in by_id:
            cfg = edge.properties.get("config")
            return str(by_id[edge.dst_id].properties.get("nome") or "") or None, cfg if isinstance(cfg, dict) else {}
    return None, {}


def _scalar(value: object) -> bool:
    return isinstance(value, (str, int, float, bool))


def _diff(before: dict, after: dict) -> str | None:
    """``chave=valor`` do que mudou de ``before`` para ``after`` (só escalares, até três chaves)."""
    changed = [
        f"{key}={after[key]}"
        for key in sorted(after)
        if _scalar(after[key]) and before.get(key) != after[key]
    ]
    return ", ".join(changed[:_MAX_DIFF_KEYS]) or None


def build_failure_items(store: GraphStore, project_id: str) -> list[FailureItem]:
    """Falhas conhecidas do projeto, da mais frequente para a menos, com a correção conhecida quando há."""
    experiments = sorted(
        store.find_nodes("Experimento", {"projeto_id": project_id}, limit=_MAX_EXPERIMENTS),
        key=lambda n: str(n.properties.get("criado_em") or ""),
    )
    rows: list[tuple[Node, str | None, dict]] = [(exp, *_approach_of(store, exp)) for exp in experiments]
    counts: dict[tuple[str, str], int] = {}
    fixes: dict[tuple[str, str], str | None] = {}
    for index, (exp, approach, cfg) in enumerate(rows):
        props = exp.properties
        signature = props.get("assinatura_falha")
        if props.get("status") != "falha" or not isinstance(signature, str):
            continue
        if signature in _AMBIENTE:
            scope = ESCOPO_AMBIENTE
        elif props.get("causa_falha") == CAUSA_ABORDAGEM and approach:
            scope = approach
        else:
            continue
        key = (scope, signature)
        counts[key] = counts.get(key, 0) + 1
        if scope == ESCOPO_AMBIENTE or fixes.get(key):
            fixes.setdefault(key, None)
            continue
        for later, later_approach, later_cfg in rows[index + 1:]:
            if later_approach == approach and later.properties.get("status") == "sucesso":
                fixes[key] = _diff(cfg, later_cfg)
                break
        else:
            fixes.setdefault(key, None)
    items = [FailureItem(scope, sig, n, fixes.get((scope, sig))) for (scope, sig), n in counts.items()]
    return sorted(items, key=lambda i: (-i.ocorrencias, i.escopo, i.assinatura))


def format_failure_memory(items: list[FailureItem], max_chars: int) -> tuple[str, int]:
    """Texto "NÃO / USE" do modelo fixo, cortado em ``max_chars``; devolve também quantos itens couberam."""
    lines: list[str] = []
    used = 0
    for item in items:
        times = f"{item.ocorrencias} vez" if item.ocorrencias == 1 else f"{item.ocorrencias} vezes"
        line = f"NÃO: {item.assinatura} em {item.escopo} ({times}). USE: {item.correcao or _NO_CORRECTION}"
        extra = len(line) + (1 if lines else 0)
        if used + extra > max_chars:
            break
        lines.append(line)
        used += extra
    return "\n".join(lines), len(lines)


def failure_memory_text(store: GraphStore, project_id: str, max_chars: int | None = None) -> tuple[str, int, int]:
    """Memória de falhas do projeto pronta para o prompt do Developer.

    Args:
        store: Grafo.
        project_id: Projeto da sessão.
        max_chars: Teto de caracteres (padrão: ``FAILURE_MEMORY_MAX_CHARS``; 0 desliga).

    Returns:
        ``(texto, itens que couberam, itens cortados)``; texto vazio quando desligada ou sem falhas.
    """
    limit = config.FAILURE_MEMORY_MAX_CHARS if max_chars is None else max_chars
    if limit <= 0:
        return "", 0, 0
    items = build_failure_items(store, project_id)
    text, fitted = format_failure_memory(items, limit)
    return text, fitted, len(items) - fitted
