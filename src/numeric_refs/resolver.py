"""Resolução de referências numéricas (design §2): ``res`` pelo registro de execução, ``src`` pela fonte conferida e
``calc`` pelo avaliador determinístico."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.logger import get_logger
from src.numeric_refs import calc as calc_module
from src.numeric_refs import syntax
from src.numeric_refs.numbers import find_numbers, parse_digits
from src.numeric_refs.sources import extract_text, normalize_for_match, read_search_sources
from src.numeric_refs.units import is_known_unit, unit_from_text
from src.provenance.errors import ProvenanceUnavailable
from src.provenance.hashing import sha256_file
from src.provenance.ledger import ExecutionLedger
from src.provenance.store import TIPO_INICIO, TIPO_TERMINO

logger = get_logger(__name__)

# Motivos (código exibido no apêndice).
M_SEM_TERMINO = "execucao_sem_termino"
M_DESCONHECIDA = "execucao_desconhecida"
M_FALHOU = "execucao_falhou"
M_ARTEFATO_ALTERADO = "artefato_alterado"
M_ARTEFATO_AUSENTE = "artefato_ausente"
M_METRICA_AUSENTE = "metrica_ausente"
M_INSUMO_ALTERADO = "insumo_alterado"
M_INSUMO_DESCONHECIDO = "insumo_desconhecido"
M_FONTE_NAO_CONSULTADA = "fonte_nao_consultada"
M_TRECHO_NAO_ENCONTRADO = "trecho_nao_encontrado"
M_TRECHO_SEM_NUMERO = "trecho_sem_numero"
M_TRECHO_AMBIGUO = "trecho_ambiguo"
M_REGISTRO_INDISPONIVEL = "registro_indisponivel"


@dataclass(frozen=True)
class ResolvedValue:
    valor: float | None
    unidade: str | None
    origem: str  # "res" | "calc" | "src"
    detalhe: dict[str, Any]
    ok: bool
    motivo: str | None = None
    decimais: int | None = None
    inteiro: bool = False
    mensagem: str | None = None


def failure(
    origem: str, motivo: str, detalhe: dict[str, Any] | None = None, mensagem: str | None = None
) -> ResolvedValue:
    return ResolvedValue(None, None, origem, detalhe or {}, False, motivo, mensagem=mensagem)


@dataclass
class ReferenceResolver:
    """Resolve referências de uma sessão/projeto.

    Args:
        ledger: Livro de execuções (registros de término).
        output_dir: Raiz de ``outputs/``.
        graph: Grafo (nós ``Insumo``/``Metrica``), ou ``None`` (então ``src`` de insumo não resolve).
        session_ids: Sessões do projeto (insumos em ``input_snapshot/`` e ``fontes_busca.jsonl``).
        literal_metrics: ``{(exec_id, métrica)}`` sinalizadas pela verificação estática.
    """

    ledger: ExecutionLedger
    output_dir: Path
    graph: Any = None
    session_ids: list[str] = field(default_factory=list)
    literal_metrics: set[tuple[str, str]] = field(default_factory=set)
    _cache: dict[tuple, ResolvedValue] = field(default_factory=dict)

    # --- entrada pública -----------------------------------------------------------------------------------------

    def resolve(self, ref: syntax.NumericRef) -> ResolvedValue:
        key = ref.key
        if key not in self._cache:
            payload = ref.payload
            if isinstance(payload, syntax.ResTarget):
                self._cache[key] = self.resolve_res(payload)
            elif isinstance(payload, syntax.CalcExpr):
                self._cache[key] = self.resolve_calc(payload.expressao)
            else:
                self._cache[key] = self.resolve_src(payload)
        return self._cache[key]

    # --- res -------------------------------------------------------------------------------------------------------

    def resolve_res(self, target: syntax.ResTarget) -> ResolvedValue:
        detail: dict[str, Any] = {"exec_id": target.exec_id, "metrica": target.nome}
        try:
            end = self.ledger.store.get(target.exec_id, TIPO_TERMINO)
            start = None if end is not None else self.ledger.store.get(target.exec_id, TIPO_INICIO)
        except ProvenanceUnavailable as exc:
            return failure("res", M_REGISTRO_INDISPONIVEL, detail, str(exc)[:200])
        if end is None:
            return failure("res", M_SEM_TERMINO if start is not None else M_DESCONHECIDA, detail)
        body = end.corpo
        detail.update(subtarefa=end.task_name, seq=end.seq)
        if body.get("status") != "sucesso" or body.get("exit_code") not in (0, None):
            return failure("res", M_FALHOU, detail)
        wanted = "params.json" if target.is_param else "metrics.json"
        saida = next((s for s in body.get("saidas") or [] if str(s.get("caminho", "")).endswith("/" + wanted)), None)
        if saida is None:
            return failure("res", M_METRICA_AUSENTE, detail)
        path = self.output_dir / str(saida["caminho"])
        detail.update(arquivo=str(saida["caminho"]), sha256=saida.get("sha256"))
        try:
            if sha256_file(path) != saida.get("sha256"):
                return failure("res", M_ARTEFATO_ALTERADO, detail)
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return failure("res", M_ARTEFATO_AUSENTE, detail)
        except (OSError, ValueError):
            return failure("res", M_ARTEFATO_ALTERADO, detail)
        if target.is_param:
            container = data.get("parameters") if isinstance(data, dict) else None
            name = target.nome[len(syntax.PARAM_PREFIX) :]
        else:
            container = data.get("metrics") if isinstance(data, dict) else None
            name = target.nome
        value = container.get(name) if isinstance(container, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return failure("res", M_METRICA_AUSENTE, detail)
        unit = None
        if not target.is_param and isinstance(data.get("unidades"), dict):
            raw_unit = data["unidades"].get(name)
            unit = str(raw_unit) if isinstance(raw_unit, str) and raw_unit.strip() else None
        if unit is None and not target.is_param:
            unit = self._graph_unit(name)
        return ResolvedValue(float(value), unit, "res", detail, True, inteiro=isinstance(value, int))

    def _graph_unit(self, name: str) -> str | None:
        if self.graph is None:
            return None
        try:
            nodes = self.graph.find_nodes("Metrica", {"nome": name}, limit=1)
            unit = nodes[0].properties.get("unidade") if nodes else None
            return str(unit) if isinstance(unit, str) and unit else None
        except Exception:  # noqa: BLE001 - a unidade do grafo é opcional
            return None

    # --- src -------------------------------------------------------------------------------------------------------

    def resolve_src(self, target: syntax.SrcTarget) -> ResolvedValue:
        detail: dict[str, Any] = {"fonte": target.fonte, "trecho": target.trecho}
        text, error = (
            self._url_text(target, detail) if target.is_url else self._insumo_text(target, detail)
        )
        if error is not None:
            return failure("src", error, detail)
        wanted = normalize_for_match(target.trecho)
        if not wanted or wanted not in normalize_for_match(text):
            return failure("src", M_TRECHO_NAO_ENCONTRADO, detail)
        numbers = find_numbers(target.trecho)
        if not numbers:
            return failure("src", M_TRECHO_SEM_NUMERO, detail)
        if len(numbers) > 1:
            return failure("src", M_TRECHO_AMBIGUO, detail, "o trecho contém mais de um número; cite um trecho menor")
        number = numbers[0]
        value = number.value if number.value is not None else parse_digits(number.text)
        if value is None:
            return failure("src", M_TRECHO_SEM_NUMERO, detail)
        unit = "%" if "%" in number.text or "por cento" in number.text else _unit_after(target.trecho, number.end)
        return ResolvedValue(float(value), unit, "src", detail, True)

    def _url_text(self, target: syntax.SrcTarget, detail: dict[str, Any]) -> tuple[str, str | None]:
        entries = [e for e in read_search_sources(self.output_dir, self.session_ids) if e.get("url") == target.fonte]
        if not entries:
            return "", M_FONTE_NAO_CONSULTADA
        wanted = normalize_for_match(target.trecho)
        for entry in entries:
            snippet = str(entry.get("trecho") or "")
            if wanted and wanted in normalize_for_match(snippet):
                detail.update(titulo=entry.get("titulo"), obtido_em=entry.get("obtido_em"))
                return snippet, None
        return " ".join(str(e.get("trecho") or "") for e in entries), None

    def _insumo_text(self, target: syntax.SrcTarget, detail: dict[str, Any]) -> tuple[str, str | None]:
        if self.graph is None:
            return "", M_INSUMO_DESCONHECIDO
        try:
            node = self.graph.get_node(target.fonte)
        except Exception:  # noqa: BLE001
            node = None
        if node is None or node.label != "Insumo":
            return "", M_INSUMO_DESCONHECIDO
        name, digest = str(node.properties.get("caminho", "")), str(node.properties.get("hash_conteudo", ""))
        detail.update(titulo=node.properties.get("titulo"), arquivo=name, sha256=digest)
        candidates = [self.output_dir / sid / "input_snapshot" / name for sid in self.session_ids]
        existing = [p for p in candidates if p.is_file()]
        if not existing:
            return "", M_INSUMO_DESCONHECIDO
        for path in existing:
            try:
                if sha256_file(path) == digest:
                    return extract_text(path, digest), None
            except (OSError, ValueError) as exc:
                logger.warning("Texto do insumo não extraído", extra={"erro": type(exc).__name__})
        return "", M_INSUMO_ALTERADO

    # --- calc ------------------------------------------------------------------------------------------------------

    def resolve_calc(self, expression: str) -> ResolvedValue:
        detail: dict[str, Any] = {"expressao": " ".join(expression.split())}
        try:
            parsed = calc_module.parse_expression(expression)
        except calc_module.CalcError as exc:
            return failure("calc", exc.codigo, detail, str(exc))
        values: dict[str, calc_module.Quantity] = {}
        operands_detail: list[dict[str, Any]] = []
        for operand in parsed.operandos:
            ref_key = operand.target
            resolved = (
                self.resolve_res(ref_key) if isinstance(ref_key, syntax.ResTarget) else self.resolve_src(ref_key)
            )
            operands_detail.append(
                {"ident": operand.ident, "origem": operand.kind, "raw": operand.raw, **resolved.detalhe}
            )
            if not resolved.ok or resolved.valor is None:
                detail["operandos"] = operands_detail
                return failure("calc", resolved.motivo or "operando_nao_resolvido", detail, "operando não verificado")
            values[operand.ident] = calc_module.Quantity(resolved.valor, unit_from_text(resolved.unidade))
        detail["operandos"] = operands_detail
        detail["constantes"] = parsed.constantes
        try:
            result = calc_module.evaluate(parsed, values)
        except calc_module.CalcError as exc:
            return failure("calc", exc.codigo, detail, str(exc))
        return ResolvedValue(result.valor, result.unidade, "calc", detail, True, decimais=result.decimais)


def _unit_after(text: str, end: int) -> str | None:
    rest = text[end:].lstrip("  ")
    token = rest.split(" ", 1)[0].strip(".,;:)") if rest else ""
    return token if token and is_known_unit(token) else None

