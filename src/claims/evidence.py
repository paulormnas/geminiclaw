"""Pacotes de evidência das conclusões (v18.5-claim-verification, design §5).

O pacote nunca é instrução: cada item é conteúdo observado, entregue ao ``EgressGate`` com a origem do trecho
(``saida_execucao``, ``grafo`` ou ``documento``) e delimitado como dado.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from src.claims.decompose import Sentence
from src.claims.deterministic import CODE_RE, CodeValue
from src.claims.model import Conclusao
from src.claims.verifier import EvidenceItem
from src.logger import get_logger
from src.utils.egress_fragments import ContentOrigin

logger = get_logger(__name__)

MAX_ITEM_CHARS = 1500


def codes_from_render(codigos: list[Any]) -> dict[str, CodeValue]:
    """Valores por código a partir dos ``RenderedCode`` do relatório."""
    out: dict[str, CodeValue] = {}
    for code in codigos:
        if code.valor_exato is None:
            continue
        metric = (code.detalhe or {}).get("metrica") if code.tipo == "res" else None
        out[code.codigo] = CodeValue(code.codigo, float(code.valor_exato), code.unidade, metric)
    return out


def codes_from_payload(codigos: list[dict[str, Any]]) -> dict[str, CodeValue]:
    """Valores por código a partir de ``proveniencia_numerica.json`` (sessões anteriores)."""
    out: dict[str, CodeValue] = {}
    for item in codigos:
        value = item.get("valor_exato")
        if value is None or not item.get("codigo"):
            continue
        detail = item.get("detalhe") or {}
        metric = detail.get("metrica") if item.get("tipo") == "res" else None
        out[item["codigo"]] = CodeValue(item["codigo"], float(value), item.get("unidade"), metric)
    return out


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _cap(text: str) -> str:
    return text if len(text) <= MAX_ITEM_CHARS else text[:MAX_ITEM_CHARS] + " […]"


def _divergence_note(output_dir: Path | None, relative: str | None) -> str | None:
    if output_dir is None or not relative:
        return None
    try:
        data = json.loads((Path(output_dir) / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    note = data.get("divergence_note") if isinstance(data, dict) else None
    return str(note) if note else None


_ACCEPTED_RESULTS = ("validado", "divergente_documentado")
_MAX_RESULT_ROWS = 200


def session_results_item(graph: Any, session_id: str) -> EvidenceItem | None:
    """Tabela dos ``Resultado``s validados da sessão (nome, qualificador, valor, subtarefa, ``exec_id``).

    Evidência das frases do relatório que não citam código de referência (``v18.6-hypothesis-closure`` §6.1).
    Devolve ``None`` sem grafo, sem resultados ou em falha de leitura (o verificador devolve ``sem_evidencia``).
    """
    if graph is None:
        return None
    try:
        nodes = graph.find_nodes("Resultado", {"sessao_id": session_id}, limit=_MAX_RESULT_ROWS)
        rows: list[str] = []
        for node in nodes:
            p = node.properties
            if p.get("status_validacao") not in _ACCEPTED_RESULTS:
                continue
            exps = [n for n in graph.neighbors(node.id, ["PRODUZIU"], direction="in", depth=1).nodes
                    if n.label == "Experimento"]
            subtask = str(exps[0].properties.get("subtarefa_id", "—")).split(":")[-1] if exps else "—"
            rows.append(
                f"{p.get('nome_original')} | {p.get('qualificador') or '—'} | {p.get('valor')!r} | {subtask} | "
                f"{p.get('exec_id') or '—'}"
            )
    except Exception as exc:  # noqa: BLE001 - sem a tabela a frase fica sem evidência
        logger.warning("Tabela de resultados da sessão indisponível", extra={"erro": type(exc).__name__})
        return None
    if not rows:
        return None
    from src import config

    limit = max(200, config.CLAIM_EVIDENCE_MAX_CHARS // 2)
    text = "nome | qualificador | valor | subtarefa | exec_id\n" + "\n".join(sorted(rows))
    if len(text) > limit:
        text = text[:limit] + " […]"
    return EvidenceItem("", f"resultados:{session_id}", "Resultados validados da sessão", text, ContentOrigin.GRAFO)


def report_evidence_builder(
    codigos: list[Any] | list[dict[str, Any]],
    output_dir: Path | None,
    result_status: Callable[[str, str], str | None] = lambda _exec, _metric: None,
    session_results: Callable[[], EvidenceItem | None] | None = None,
) -> Callable[[Conclusao, list[Sentence]], list[EvidenceItem]]:
    """Construtor de pacotes para conclusões do relatório: um item por código de origem citado.

    Args:
        codigos: ``RenderedCode`` (ou os dicionários de ``proveniencia_numerica.json``).
        output_dir: Raiz de ``outputs/`` (para ler a ``divergence_note`` do ``metrics.json``).
        result_status: ``(exec_id, métrica) -> status_validacao`` do ``Resultado`` no grafo, se existir.
        session_results: Item com a tabela dos resultados validados da sessão; vale para toda frase sem código.
    """
    by_code: dict[str, dict[str, Any]] = {}
    for code in codigos:
        if isinstance(code, dict):
            by_code[code["codigo"]] = {
                "tipo": code.get("tipo"), "valor": code.get("valor_exato"), "unidade": code.get("unidade"),
                "detalhe": code.get("detalhe") or {},
            }
        else:
            by_code[code.codigo] = {
                "tipo": code.tipo, "valor": code.valor_exato, "unidade": code.unidade, "detalhe": code.detalhe or {},
            }

    def build(_conclusao: Conclusao, sentences: list[Sentence]) -> list[EvidenceItem]:
        seen: dict[str, set[int]] = {}
        for sentence in sentences:
            for match in CODE_RE.finditer(sentence.texto):
                code = match.group(1) + match.group(2)
                if code in by_code:
                    seen.setdefault(code, set()).add(sentence.indice)
        items: list[EvidenceItem] = []
        for code, frases in seen.items():
            info = by_code[code]
            detail = info["detalhe"]
            value = f"valor exato {info['valor']!r}" + (f" {info['unidade']}" if info["unidade"] else "")
            if info["tipo"] == "res":
                lines = [
                    f"{code}: execução registrada {detail.get('exec_id')}, subtarefa {detail.get('subtarefa')}, "
                    f"métrica {detail.get('metrica')}; {value}"
                ]
                status = result_status(str(detail.get("exec_id")), str(detail.get("metrica")))
                if status:
                    lines.append(f"status_validacao do resultado: {status}")
                note = _divergence_note(output_dir, detail.get("arquivo"))
                if note:
                    lines.append(f"divergence_note: {note}")
                ref = f"res:{detail.get('exec_id')}/{detail.get('metrica')}"
                origin = ContentOrigin.SAIDA_EXECUCAO
            elif info["tipo"] == "calc":
                operands = "; ".join(
                    f"{o.get('ident')}={o.get('metrica') or o.get('trecho')}" for o in detail.get("operandos", [])
                )
                lines = [f"{code}: cálculo {detail.get('expressao')} [{operands}]; {value}"]
                ref = f"calc:{detail.get('expressao')}"
                origin = ContentOrigin.SAIDA_EXECUCAO
            else:
                source = detail.get("titulo") or detail.get("fonte")
                lines = [f"{code}: fonte {source}, trecho “{detail.get('trecho')}”; {value}"]
                ref = f"src:{detail.get('fonte')}#{detail.get('trecho')}"
                origin = ContentOrigin.DOCUMENTO
            items.append(
                EvidenceItem("", ref, code, _cap("\n".join(lines)), origin, frozenset(frases))
            )
        covered = {i for frases in seen.values() for i in frases}
        uncoded = frozenset(s.indice for s in sentences if s.indice not in covered)
        if uncoded and session_results is not None:
            table = session_results()
            if table is not None:
                items.append(replace(table, frases=uncoded))
        return _number(items)

    return build


def discovery_evidence_builder(graph: Any) -> Callable[[Conclusao, list[Sentence]], list[EvidenceItem]]:
    """Pacotes para ``Descoberta``: ``Resultado``/``Experimento``/``Decisao`` de ``BASEADA_EM`` e o veredito."""

    def build(conclusao: Conclusao, _sentences: list[Sentence]) -> list[EvidenceItem]:
        node_id = conclusao.conclusao_id.removeprefix("desc:")
        items: list[EvidenceItem] = []
        try:
            node = graph.get_node(node_id)
            if node is not None:
                p = node.properties
                keys = ("tipo", "veredito", "confianca", "n_evidencias", "condicoes")
                verdict = {k: p.get(k) for k in keys if p.get(k) is not None}
                items.append(
                    EvidenceItem("", f"descoberta:{node_id}", "Descoberta e veredito", _cap(_dump(verdict)),
                                 ContentOrigin.GRAFO)
                )
            sub = graph.neighbors(node_id, ["BASEADA_EM"], direction="out", depth=1)
            for target in sub.nodes:
                if target.id == node_id:
                    continue
                kind = {"Resultado": "resultado", "Experimento": "experimento", "Decisao": "decisao"}.get(target.label)
                if kind is None:
                    continue
                keep = {k: v for k, v in target.properties.items() if k in _KEEP.get(target.label, ())}
                items.append(
                    EvidenceItem("", f"{kind}:{target.id}", f"{target.label} {target.id}", _cap(_dump(keep)),
                                 ContentOrigin.GRAFO)
                )
        except Exception as exc:  # noqa: BLE001 - sem evidência o verificador devolve nao_verificavel (sem_evidencia)
            logger.warning("Evidência da descoberta indisponível", extra={"erro": type(exc).__name__})
        return _number(items)

    return build


_KEEP = {
    "Resultado": ("nome_original", "valor", "unidade", "baseline", "status_validacao", "exec_id"),
    "Experimento": ("status", "causa_falha", "hash_params", "seed", "exec_id", "no_execucao"),
    "Decisao": ("contexto", "justificativa", "criterio", "resultado_posterior"),
}


def _number(items: list[EvidenceItem]) -> list[EvidenceItem]:
    from src.claims.verifier import renumber

    return renumber(items)
