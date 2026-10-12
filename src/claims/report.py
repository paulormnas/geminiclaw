"""Estágio ``claims`` e seção "Verificação das afirmações" do relatório (v18.5-claim-verification, design §3 e §9).

O pipeline do relatório é síncrono e roda numa thread (``asyncio.to_thread``); a verificação é assíncrona e deve
rodar no laço de eventos do orquestrador (os provedores LLM têm afinidade com o laço). O estágio despacha a
corrotina para esse laço com ``run_coroutine_threadsafe`` e espera o resultado.

As marcas ``[A<n> · <status>]`` entram **depois** da verificação de números (o estágio ``claims`` vem depois de
``verify``), para que o dígito da marca não seja tomado por número sem origem; o texto das conclusões não é alterado.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from src import config
from src.claims.decompose import extract_report_conclusions
from src.claims.evidence import codes_from_render, report_evidence_builder
from src.claims.model import Afirmacao, Conclusao
from src.claims.service import ClaimService
from src.claims.store import ClaimStore
from src.logger import get_logger
from src.report.pipeline import ReportPipeline, ReportState

logger = get_logger(__name__)

CLAIMS_SECTION = "claims"
CLAIMS_SECTION_TITLE = "Verificação das afirmações"
STAGE_NAME = "claims"

MARK_LABEL = {
    "parcial": "parcial",
    "refutada_deterministica": "refutada",
    "contestada": "contestada",
    "nao_verificavel": "não verificável",
    "pendente": "pendente",
}
STATUS_LABEL = {
    "suportada": "suportada",
    "parcial": "parcial",
    "refutada_deterministica": "refutada (determinística)",
    "contestada": "contestada",
    "nao_verificavel": "não verificável",
    "pendente": "pendente",
}
METHOD_LABEL = {"deterministico": "determinístico", "modelo": "modelo", None: "—"}


def format_mark(claim: Afirmacao) -> str | None:
    """Marca inline da afirmação, ou ``None`` para ``suportada`` (sem marca)."""
    label = MARK_LABEL.get(claim.status_afirmacao)
    return f"[{claim.codigo} · {label}]" if label else None


def insert_marks(text: str, conclusions: list[Conclusao], store: ClaimStore) -> str:
    """Insere as marcas depois da frase de origem de cada afirmação, sem alterar o texto das conclusões."""
    inserts: dict[int, list[tuple[int, str]]] = {}
    for conclusao in conclusions:
        for claim in store.for_conclusion(conclusao.conclusao_id):
            mark = format_mark(claim)
            if mark is None:
                continue
            position = conclusao.inicio + min(claim.span[1], len(conclusao.texto))
            inserts.setdefault(position, []).append((int(claim.codigo[1:] or 0), mark))
    for position in sorted(inserts, reverse=True):
        marks = " ".join(m for _, m in sorted(inserts[position]))
        text = text[:position] + " " + marks + text[position:]
    return text


@dataclass
class ClaimsRunner:
    """Executa a verificação do relatório no laço do orquestrador.

    Args:
        loop: Laço de eventos onde o Validator roda.
        make_service: Constrói o ``ClaimService`` da sessão a partir do estado do relatório.
        result_status: ``(exec_id, métrica) -> status_validacao`` (grafo), para o pacote de evidência.
        timeout: Espera máxima (segundos) pela verificação; ``None`` espera sem limite.
    """

    loop: asyncio.AbstractEventLoop
    make_service: Callable[[ReportState], ClaimService]
    result_status: Callable[[str, str], str | None] = lambda _e, _m: None
    timeout: float | None = None
    sections: tuple[str, ...] = field(default_factory=lambda: tuple(config.CLAIM_VERIFY_SECTIONS))

    def __call__(self, state: ReportState) -> ReportState:
        if not config.CLAIM_VERIFY_ENABLED or state.render is None:
            return state
        try:
            conclusions = extract_report_conclusions(state.text, self.sections)
            service = self.make_service(state)
            codes = codes_from_render(state.render.codigos)
            evidence = report_evidence_builder(state.render.codigos, state.session_dir.parent, self.result_status)
            future = asyncio.run_coroutine_threadsafe(
                service.verify_conclusions(conclusions, codes, evidence), self.loop
            )
            future.result(self.timeout)
            service.store.save()
            state.text = insert_marks(state.text, conclusions, service.store)
            state.extras["claims"] = {"store": service.store, "conclusoes": conclusions}
        except Exception as exc:  # noqa: BLE001 - falha explícita no relatório; o resto do pipeline segue
            logger.error(
                "Verificação das afirmações falhou", extra={"erro": type(exc).__name__, "detalhe": str(exc)[:300]}
            )
            state.extras["claims_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return state


def _cell(value: Any) -> str:
    text = str(value if value not in (None, "") else "—")
    return text.replace("\n", " ").replace("|", "\\|")


def _observation(claim: Afirmacao) -> str:
    parts: list[str] = []
    if claim.parte_nao_suportada:
        parts.append(f"não suportado: {claim.parte_nao_suportada}")
    if claim.valores_registrados:
        values = "; ".join(
            f"{k}={v.get('valor')}" for k, v in claim.valores_registrados.items() if isinstance(v, dict)
        )
        if values:
            parts.append(f"valores: {values}")
    if claim.motivo_pendencia:
        parts.append(f"pendência: {claim.motivo_pendencia}")
    if claim.motivo_nao_verificavel:
        parts.append(f"motivo: {claim.motivo_nao_verificavel}")
    if claim.verificador and claim.verificador.get("familia_diferente") is False:
        parts.append("mesma família do autor")
    if claim.revisao_pesquisador:
        parts.append(f"revisão do pesquisador: {claim.revisao_pesquisador.get('decisao')}")
    return "; ".join(parts) or claim.justificativa


def _verifier(claim: Afirmacao) -> str:
    if claim.metodo == "deterministico":
        return "—"
    info = claim.verificador or {}
    if not info:
        return "—"
    return f"{info.get('provedor_modelo')} ({info.get('familia_modelo')}, {info.get('versao_efetiva')})"


def _table(claims: list[Afirmacao]) -> list[str]:
    lines = ["| Código | Afirmação | Conclusão | Status | Método | Evidência | Verificador | Observação |",
             "|---|---|---|---|---|---|---|---|"]
    for claim in claims:
        lines.append(
            f"| {claim.codigo} | {_cell(claim.texto)} | {_cell(claim.conclusao_id)} | "
            f"{STATUS_LABEL[claim.status_afirmacao]} | {METHOD_LABEL.get(claim.metodo, '—')} | "
            f"{_cell(', '.join(claim.evidencias))} | {_cell(_verifier(claim))} | {_cell(_observation(claim))} |"
        )
    return lines


def claims_section(state: ReportState) -> str:
    """Seção do orquestrador: resumo por status, tabela com todas as afirmações e subseções de revisão."""
    if not config.CLAIM_VERIFY_ENABLED:
        return ""
    error = state.extras.get("claims_error")
    if error:
        return f"Verificação das afirmações indisponível nesta execução ({error}). O relatório NÃO foi conferido."
    data = state.extras.get("claims")
    if not data:
        return ""
    store: ClaimStore = data["store"]
    active = [c for c in store.active() if c.conclusao_id in {k.conclusao_id for k in data["conclusoes"]}]
    revised = [c for c in store.afirmacoes if c.substituida_por is not None]
    counts = store.counts(active)
    summary = ", ".join(f"{STATUS_LABEL[k]}: {v}" for k, v in counts.items())
    lines = [f"**Resumo:** {len(active)} afirmações · {summary}", ""]
    lines += _table(active) if active else ["Nenhuma conclusão com afirmações verificáveis neste relatório."]
    if revised:
        lines += ["", "### Afirmações revisadas", ""] + _table(revised)
    previous = state.extras.get("claims_previous") or []
    if previous:
        lines += ["", "### Afirmações de sessões anteriores verificadas nesta execução", ""]
        lines += _table(previous)
    return "\n".join(lines)


def register_claims(pipeline: ReportPipeline, runner: ClaimsRunner) -> None:
    """Acrescenta o estágio ``claims`` (depois de ``verify``) e a seção do orquestrador ao pipeline."""
    after = "verify" if "verify" in pipeline.stage_names else None
    pipeline.register_stage(STAGE_NAME, runner, after=after)
    pipeline.register_section(CLAIMS_SECTION, claims_section, CLAIMS_SECTION_TITLE)
