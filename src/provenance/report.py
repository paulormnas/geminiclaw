"""Seção determinística "Proveniência das execuções" do relatório final (design §8), gerada sem LLM."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.logger import get_logger
from src.provenance.errors import ProvenanceError, ProvenanceUnavailable
from src.provenance.export import export_session
from src.provenance.ledger import NO_PROJECT_PREFIX, ExecutionLedger
from src.provenance.store import TIPO_TERMINO
from src.provenance.verify import LIMITS, verify_session

logger = get_logger(__name__)

SECTION_TITLE = "Proveniência das execuções"
ONE_LINE_LIMIT = (
    "A cadeia detecta alteração acidental ou parcial dos registros e dos arquivos; não impede que quem controla o "
    "banco e o disco a reescreva por inteiro (guarde a ponta fora do nó) nem prova que a métrica foi bem calculada."
)


def provenance_section(
    ledger: ExecutionLedger,
    session_id: str,
    output_dir: Path | str,
    *,
    divergences: list[str] | None = None,
    export: bool = True,
) -> str:
    """Texto Markdown da seção (sem o título ``##``): ponta, contagem por ``status``, verificação e limite.

    Efeitos: acrescenta à cadeia os términos pendentes e, com ``export``, grava ``outputs/<sessão>/provenance/``.
    Qualquer falha do armazenamento vira uma linha explícita; a seção nunca impede o relatório.
    """
    lines: list[str] = []
    try:
        flush = ledger.flush_pending(session_id, output_dir)
        records = ledger.store.by_session(session_id)
        if not records:
            return "Nenhuma execução de código foi registrada nesta sessão.\n\n" + ONE_LINE_LIMIT
        reports = verify_session(ledger.store, session_id, output_dir)
        exported: Path | None = None
        export_error = ""
        if export:
            try:
                exported = export_session(ledger.store, session_id, output_dir)
            except ProvenanceError as exc:
                export_error = str(exc)
        for report in reports:
            scope = "cadeia da sessão (sem projeto)" if report.project_id.startswith(NO_PROJECT_PREFIX) else "projeto"
            tip = report.ponta
            lines.append(
                f"- **Cadeia ({scope})**: `{report.project_id}`"
                + (f" · ponta `seq={tip['seq']}` `{tip['record_hash']}`" if tip else "")
            )
        statuses = Counter(
            str(r.corpo.get("status")) for r in records if r.tipo == TIPO_TERMINO
        )
        starts = sum(1 for r in records if r.tipo != TIPO_TERMINO)
        by_status = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())) or "nenhum término"
        lines.append(f"- **Execuções da sessão**: {starts} (por status: {by_status})")
        orphans = [o for rep in reports for o in rep.orfas]
        pending = sorted({p for rep in reports for p in rep.pendencias} | set(flush.remaining))
        lines.append(
            f"- **Órfãs**: {len(orphans)}"
            + (f" ({', '.join(o['exec_id'] + '=' + o['classe'] for o in orphans[:5])})" if orphans else "")
            + f" · **Pendências locais**: {len(pending)}"
        )
        integra = all(rep.integra for rep in reports)
        problems = sum(
            len(rep.problemas_cadeia) + len(rep.problemas_pares) + len(rep.arquivos_alterados)
            + len(rep.checkpoints_divergentes) + len(rep.conflitos_pendencia)
            for rep in reports
        )
        lines.append(
            "- **Verificação da sessão**: " + ("íntegra" if integra else f"INCONSISTENTE ({problems} problema(s); rode "
            "`geminiclaw provenance verify`)")
        )
        no_hash = sum(
            1
            for r in records
            if r.tipo == TIPO_TERMINO
            for a in r.corpo.get("ativos") or []
            if not a.get("hash_declarado")
        )
        with_network = sum(1 for r in records if r.tipo == TIPO_TERMINO and r.corpo.get("rede_na_execucao"))
        lines.append(
            f"- **Ativos sem hash declarado**: {no_hash} · **Execuções com rede na fase execute**: {with_network}"
        )
        if exported is not None:
            lines.append(f"- **Exportação**: `{Path(exported).name}/execution_records.jsonl` e `chain_tip.json`")
        elif export_error:
            lines.append(f"- **Exportação**: não gravada ({export_error})")
        for message in divergences or []:
            lines.append(f"- **Ponta divergente na retomada**: {message}")
        lines.append(f"\n{ONE_LINE_LIMIT}")
    except ProvenanceUnavailable as exc:
        logger.warning("Seção de proveniência indisponível", extra={"erro": str(exc)[:200]})
        return f"Não foi possível consultar o registro de execuções: {exc}\n\n{ONE_LINE_LIMIT}"
    return "\n".join(lines)


__all__ = ["LIMITS", "ONE_LINE_LIMIT", "SECTION_TITLE", "provenance_section"]
