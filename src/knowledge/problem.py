"""Rascunho do ``Problema`` e sua validação (v17-research-project, ADR 015 §3).

O Researcher redige o rascunho em JSON; este módulo valida o JSON do LLM contra limites
rígidos (a saída do modelo é dado não confiável) e define as edições que o pesquisador pode
fazer antes de confirmar. Nada aqui grava no grafo — a gravação e a confirmação ficam em
:mod:`src.knowledge.projects`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any

# Limites de tamanho: o rascunho vem de um LLM e vira propriedade de nó do grafo.
MAX_TITULO = 200
MAX_RESUMO = 4000
MAX_CLASSE = 64
MAX_DOMINIOS = 10
MAX_DOMINIO = 120
MAX_METRICA = 120
MAX_BASELINE = 300
MAX_CARACTERISTICAS = 20
MAX_CARACTERISTICA_CHAVE = 64
MAX_CARACTERISTICA_VALOR = 200

# Remove controles inclusive "\r" (sobrescreveria a linha no terminal ao exibir o rascunho); "\n" é mantido.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

EDITABLE_FIELDS: tuple[str, ...] = (
    "titulo", "resumo", "classe", "dominios", "tipo", "metrica", "alvo", "delta_min", "ao_atingir_objetivo",
)
# ``concorrentes`` tem sintaxe própria (``enunciado :: predicao`` separados por ``;``), por isso fica fora da lista.
CONCORRENTES_FIELD = "concorrentes"
MAX_CONCORRENTES = 10
MAX_ENUNCIADO_CONCORRENTE = 500
FRONTEIRA_RECUSADA = "tipo `fronteira` ainda não suportado; será especificado com a V19 (equipamentos)"


class ProblemDraftError(ValueError):
    """Rascunho de problema inválido (mensagem acionável, sem eco de conteúdo do LLM)."""


@dataclass(frozen=True)
class Concorrente:
    """Hipótese concorrente do objetivo de discriminação: o enunciado e o que ela prediz."""

    enunciado: str
    predicao: str


@dataclass(frozen=True)
class ProblemDraft:
    """Rascunho do ``Problema`` em alto nível, escrito como resumo de artigo sem resultados.

    Attributes:
        titulo: Título do problema.
        resumo: Contexto, lacuna, objetivo e o que seria um avanço (sem citar técnica).
        classe: Classe do problema (ex.: ``regressao``); opcional.
        caracteristicas_dados: Tamanho, modalidade, ruído etc. (chaves e valores curtos).
        dominios: Termos de domínio em texto livre (resolvidos no vocabulário na confirmação).
        metrica: Nome da métrica do critério de sucesso (texto livre).
        alvo: Valor-alvo da métrica, ou ``None``.
        delta_min: Menor melhoria relevante sobre o baseline; ``None`` até o pesquisador definir.
        baseline_descricao: Descrição do baseline de comparação; opcional.
        tipo: Tipo do objetivo (``limiar``, ``discriminacao``, ``cobertura``, ``fronteira``); ``None`` = não definido.
        ao_atingir_objetivo: Política ao atingir o objetivo (``parar``, ``perguntar``, ``continuar``); só o
            pesquisador a define.
        concorrentes: Hipóteses concorrentes do tipo ``discriminacao``.
    """

    titulo: str
    resumo: str
    classe: str | None = None
    caracteristicas_dados: dict[str, Any] = field(default_factory=dict)
    dominios: tuple[str, ...] = ()
    metrica: str | None = None
    alvo: float | None = None
    delta_min: float | None = None
    baseline_descricao: str | None = None
    tipo: str | None = None
    ao_atingir_objetivo: str | None = None
    concorrentes: tuple[Concorrente, ...] = ()

    @property
    def effective_tipo(self) -> str | None:
        """Tipo declarado; sem ele, ``limiar`` quando há campos de limiar (rascunho no formato anterior)."""
        if self.tipo:
            return self.tipo
        if self.metrica or self.alvo is not None or self.delta_min is not None:
            return "limiar"
        return None

    @property
    def missing_delta_min(self) -> bool:
        """True quando o tipo é ``limiar`` e ``delta_min`` ainda não foi definido (obrigatório para confirmar)."""
        return self.effective_tipo == "limiar" and self.delta_min is None

    def objective_gaps(self, *, objective_optional: bool = False) -> list[str]:
        """O que falta para o objetivo poder ser confirmado (vazio = completo).

        Args:
            objective_optional: No modo ``auto`` o pesquisador pode confirmar sem objetivo; o Researcher o propõe
                no primeiro plano.
        """
        kind = self.effective_tipo
        if kind is None:
            return [] if objective_optional else ["tipo do objetivo (limiar, discriminacao ou cobertura)"]
        if kind == "fronteira":
            return [FRONTEIRA_RECUSADA]
        if kind == "limiar":
            gaps = []
            if not self.metrica:
                gaps.append("metrica")
            if self.delta_min is None:
                gaps.append("delta_min")
            return gaps
        if kind == "discriminacao" and len(self.concorrentes) < 2:
            return ["ao menos duas hipóteses concorrentes, cada uma com predição"]
        return []

    def criterio_sucesso(self) -> dict[str, Any]:
        """Monta o dicionário ``criterio_sucesso`` do nó ``Problema`` (campos do tipo; design §4.1)."""
        kind = self.effective_tipo
        criterio: dict[str, Any] = {}
        if kind is not None:
            criterio["tipo"] = kind
        if self.metrica is not None or kind in (None, "limiar"):
            criterio["metrica"] = self.metrica
        if kind in (None, "limiar"):
            criterio["alvo"] = self.alvo
            criterio["delta_min"] = self.delta_min
        criterio["baseline_descricao"] = self.baseline_descricao
        if kind == "discriminacao":
            criterio["hipoteses_concorrentes"] = [
                {"enunciado": c.enunciado, "predicao": c.predicao} for c in self.concorrentes
            ]
        if self.ao_atingir_objetivo is not None:
            criterio["ao_atingir_objetivo"] = self.ao_atingir_objetivo
        return criterio


def clean_text(
    value: Any, name: str, max_len: int, *, required: bool = False, single_line: bool = False
) -> str | None:
    """Normaliza um texto livre: tipo ``str``, sem caracteres de controle, tamanho limitado.

    Args:
        value: Valor recebido.
        name: Nome do campo (para a mensagem de erro).
        max_len: Tamanho máximo após ``strip``.
        required: Se True, vazio/``None`` é erro; senão devolve ``None``.
        single_line: Se True, quebras de linha viram espaço (ex.: título).

    Raises:
        ProblemDraftError: Tipo inválido, vazio obrigatório ou acima do limite.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ProblemDraftError(f"Campo '{name}' é obrigatório.")
        return None
    if not isinstance(value, str):
        raise ProblemDraftError(f"Campo '{name}' deve ser texto.")
    if single_line:
        value = " ".join(value.split())
    text = _CONTROL_CHARS.sub("", value).strip()
    if len(text) > max_len:
        raise ProblemDraftError(f"Campo '{name}' excede {max_len} caracteres.")
    return text


def parse_number(value: Any, name: str, *, positive: bool = False) -> float | None:
    """Converte um número (``int``/``float``/texto decimal) em ``float`` finito, ou ``None``.

    Aceita vírgula decimal em texto (``"0,05"``). ``bool`` é recusado.

    Raises:
        ProblemDraftError: Não numérico, não finito ou, com ``positive``, não maior que zero.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ProblemDraftError(f"Campo '{name}' deve ser numérico.")
    try:
        number = float(value.replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError, OverflowError):
        raise ProblemDraftError(f"Campo '{name}' deve ser numérico.") from None
    if not math.isfinite(number):
        raise ProblemDraftError(f"Campo '{name}' deve ser um número finito.")
    if positive and number <= 0:
        raise ProblemDraftError(f"Campo '{name}' deve ser maior que zero.")
    return number


def _parse_tipo(value: Any) -> str | None:
    from src.knowledge import schema

    text = clean_text(value, "criterio_sucesso.tipo", 32, single_line=True)
    if text is not None and text not in schema.TIPOS_OBJETIVO:
        raise ProblemDraftError(f"Campo 'criterio_sucesso.tipo' deve ser um de: {', '.join(schema.TIPOS_OBJETIVO)}.")
    return text


def _parse_politica(value: Any) -> str | None:
    from src.knowledge import schema

    text = clean_text(value, "ao_atingir_objetivo", 32, single_line=True)
    if text is not None and text not in schema.POLITICAS_OBJETIVO:
        raise ProblemDraftError(f"Campo 'ao_atingir_objetivo' deve ser um de: {', '.join(schema.POLITICAS_OBJETIVO)}.")
    return text


def _parse_concorrentes(value: Any) -> tuple[Concorrente, ...]:
    from src import config

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ProblemDraftError("Campo 'hipoteses_concorrentes' deve ser uma lista.")
    if len(value) > MAX_CONCORRENTES:
        raise ProblemDraftError(f"Campo 'hipoteses_concorrentes' aceita no máximo {MAX_CONCORRENTES} itens.")
    result: list[Concorrente] = []
    for item in value:
        if not isinstance(item, dict):
            raise ProblemDraftError("Cada item de 'hipoteses_concorrentes' deve ser um objeto.")
        result.append(
            Concorrente(
                clean_text(item.get("enunciado"), "hipoteses_concorrentes.enunciado", MAX_ENUNCIADO_CONCORRENTE,
                           required=True, single_line=True),  # type: ignore[arg-type]
                clean_text(item.get("predicao"), "hipoteses_concorrentes.predicao", config.HYPOTHESIS_TEXT_MAX_CHARS,
                           required=True),  # type: ignore[arg-type]
            )
        )
    return tuple(result)


def parse_concorrentes_text(value: str) -> tuple[Concorrente, ...]:
    """Edição de ``concorrentes`` pelo pesquisador: itens ``enunciado :: predicao`` separados por ``;``."""
    items = []
    for part in value.split(";"):
        if not part.strip():
            continue
        enunciado, sep, predicao = part.partition("::")
        if not sep:
            raise ProblemDraftError("Cada concorrente deve ser 'enunciado :: predicao'.")
        items.append({"enunciado": enunciado, "predicao": predicao})
    return _parse_concorrentes(items)


def _parse_dominios(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ProblemDraftError("Campo 'dominios' deve ser uma lista de textos.")
    if len(value) > MAX_DOMINIOS:
        raise ProblemDraftError(f"Campo 'dominios' aceita no máximo {MAX_DOMINIOS} termos.")
    result: list[str] = []
    for item in value:
        text = clean_text(item, "dominios", MAX_DOMINIO)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _parse_caracteristicas(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProblemDraftError("Campo 'caracteristicas_dados' deve ser um objeto.")
    if len(value) > MAX_CARACTERISTICAS:
        raise ProblemDraftError(f"Campo 'caracteristicas_dados' aceita no máximo {MAX_CARACTERISTICAS} entradas.")
    result: dict[str, Any] = {}
    for key, item in value.items():
        clean_key = clean_text(key, "caracteristicas_dados", MAX_CARACTERISTICA_CHAVE, required=True)
        if isinstance(item, bool) or item is None:
            result[clean_key] = item  # type: ignore[index]
        elif isinstance(item, (int, float)):
            result[clean_key] = parse_number(item, "caracteristicas_dados")  # type: ignore[index]
        else:
            result[clean_key] = clean_text(item, "caracteristicas_dados", MAX_CARACTERISTICA_VALOR)  # type: ignore[index]
    return result


def parse_problem_draft(raw: Any) -> ProblemDraft:
    """Valida o JSON do rascunho devolvido pelo Researcher e o converte em ``ProblemDraft``.

    Campos desconhecidos são ignorados; tipos e tamanhos são checados. ``delta_min`` ausente
    ou ``null`` é aceito (o pesquisador o define antes de confirmar).

    Args:
        raw: Objeto JSON já decodificado.

    Returns:
        O rascunho validado.

    Raises:
        ProblemDraftError: JSON fora do contrato (mensagem sem eco do conteúdo do LLM).
    """
    if not isinstance(raw, dict):
        raise ProblemDraftError("O rascunho deve ser um objeto JSON.")
    criterio = raw.get("criterio_sucesso")
    if criterio is None:
        criterio = {}
    if not isinstance(criterio, dict):
        raise ProblemDraftError("Campo 'criterio_sucesso' deve ser um objeto.")
    return ProblemDraft(
        titulo=clean_text(raw.get("titulo"), "titulo", MAX_TITULO, required=True, single_line=True),  # type: ignore[arg-type]
        resumo=clean_text(raw.get("resumo"), "resumo", MAX_RESUMO, required=True),  # type: ignore[arg-type]
        classe=clean_text(raw.get("classe"), "classe", MAX_CLASSE),
        caracteristicas_dados=_parse_caracteristicas(raw.get("caracteristicas_dados")),
        dominios=_parse_dominios(raw.get("dominios")),
        metrica=clean_text(criterio.get("metrica"), "criterio_sucesso.metrica", MAX_METRICA),
        alvo=parse_number(criterio.get("alvo"), "criterio_sucesso.alvo"),
        delta_min=parse_number(criterio.get("delta_min"), "criterio_sucesso.delta_min", positive=True),
        baseline_descricao=clean_text(
            criterio.get("baseline_descricao"), "criterio_sucesso.baseline_descricao", MAX_BASELINE
        ),
        tipo=_parse_tipo(criterio.get("tipo")),
        # A política ao atingir o objetivo é do pesquisador: o valor do rascunho do LLM é descartado (design §4.1).
        concorrentes=_parse_concorrentes(criterio.get("hipoteses_concorrentes")),
    )


def apply_edit(draft: ProblemDraft, campo: str, valor: str) -> ProblemDraft:
    """Aplica a edição de um campo (entrada de texto do pesquisador) e devolve um novo rascunho.

    Args:
        draft: Rascunho atual.
        campo: Um de ``EDITABLE_FIELDS``.
        valor: Novo valor em texto; ``dominios`` aceita termos separados por ``;``.

    Raises:
        ProblemDraftError: Campo não editável ou valor inválido.
    """
    editable = (*EDITABLE_FIELDS, CONCORRENTES_FIELD)
    if campo not in editable:
        raise ProblemDraftError(f"Campo '{campo}' não é editável; use um de: {', '.join(editable)}.")
    if campo == "titulo":
        return replace(draft, titulo=clean_text(valor, "titulo", MAX_TITULO, required=True, single_line=True))  # type: ignore[arg-type]
    if campo == "resumo":
        return replace(draft, resumo=clean_text(valor, "resumo", MAX_RESUMO, required=True))  # type: ignore[arg-type]
    if campo == "classe":
        return replace(draft, classe=clean_text(valor, "classe", MAX_CLASSE))
    if campo == "dominios":
        return replace(draft, dominios=_parse_dominios([p for p in valor.split(";")]))
    if campo == "tipo":
        return replace(draft, tipo=_parse_tipo(valor))
    if campo == "ao_atingir_objetivo":
        return replace(draft, ao_atingir_objetivo=_parse_politica(valor))
    if campo == CONCORRENTES_FIELD:
        return replace(draft, concorrentes=parse_concorrentes_text(valor))
    if campo == "metrica":
        return replace(draft, metrica=clean_text(valor, "metrica", MAX_METRICA))
    if campo == "alvo":
        return replace(draft, alvo=parse_number(valor, "alvo"))
    return replace(draft, delta_min=parse_number(valor, "delta_min", positive=True))
