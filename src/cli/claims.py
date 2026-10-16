"""``geminiclaw claims list|resolve`` (v18.5-claim-verification, design §10).

``list`` é determinístico e somente leitura. ``resolve`` registra a decisão do pesquisador sobre uma afirmação
``contestada`` no histórico dela, **sem alterar a evidência do grafo** (alterações no grafo seguem pelo Curator,
ADR 015 §11). Códigos de saída: 0 (ok), 1 (afirmação não encontrada ou decisão inválida), 2 (uso incorreto).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.claims.model import ATOR_PESQUISADOR, STATUSES, Afirmacao
from src.claims.store import FILENAME, ClaimStore, ClaimStoreError, now_iso
from src.logger import get_logger
from src.report.claims_report import STATUS_LABEL

logger = get_logger(__name__)

DECISOES = ("mantida", "descartada")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geminiclaw claims", description="Revisão das afirmações verificadas (ADR 019 §6)."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("list", help="Lista as afirmações (somente leitura).")
    listing.add_argument("--project", help="Só as sessões deste projeto.")
    listing.add_argument("--session", help="Só esta sessão.")
    listing.add_argument("--status", choices=STATUSES, help="Só este status.")
    listing.add_argument("--json", action="store_true", help="Saída em JSON.")
    resolve = sub.add_parser("resolve", help="Registra a decisão do pesquisador sobre uma afirmação contestada.")
    resolve.add_argument("afirmacao_id")
    resolve.add_argument("--decisao", required=True, choices=DECISOES)
    resolve.add_argument("--motivo", required=True, help="Justificativa da decisão (obrigatória).")
    return parser


def _session_dirs(output_dir: Path, session: str | None, project: str | None) -> list[Path]:
    if session:
        return [output_dir / session]
    if not output_dir.is_dir():
        return []
    dirs = sorted(p for p in output_dir.iterdir() if p.is_dir() and (p / FILENAME).is_file())
    if not project:
        return dirs
    from src.session.continuity import CheckpointError, read_checkpoint

    selected: list[Path] = []
    for directory in dirs:
        try:
            checkpoint, _ = read_checkpoint(directory, expected_session_id=directory.name)
        except CheckpointError:
            continue
        if checkpoint.project_id == project:
            selected.append(directory)
    return selected


def _load_all(output_dir: Path, session: str | None, project: str | None) -> list[ClaimStore]:
    stores: list[ClaimStore] = []
    for directory in _session_dirs(output_dir, session, project):
        if (directory / FILENAME).is_file():
            stores.append(ClaimStore.load(directory, directory.name))
    return stores


def _row(store: ClaimStore, claim: Afirmacao) -> dict[str, Any]:
    return {
        "afirmacao_id": claim.afirmacao_id,
        "sessao": store.session_id,
        "codigo": claim.codigo,
        "conclusao": claim.conclusao_id,
        "status": claim.status_afirmacao,
        "texto": claim.texto,
        "revisao": (claim.revisao_pesquisador or {}).get("decisao"),
    }


def _list(args: argparse.Namespace, output_dir: Path) -> int:
    rows: list[dict[str, Any]] = []
    for store in _load_all(output_dir, args.session, args.project):
        for claim in store.active():
            if args.status and claim.status_afirmacao != args.status:
                continue
            rows.append(_row(store, claim))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("Nenhuma afirmação encontrada.")
        return 0
    for row in rows:
        review = f" (revisão: {row['revisao']})" if row["revisao"] else ""
        print(f"{row['afirmacao_id']}  {row['sessao']}  {row['codigo']}  {STATUS_LABEL[row['status']]}{review}")
        print(f"    {row['conclusao']}: {row['texto']}")
    return 0


def _find(output_dir: Path, claim_id: str) -> tuple[ClaimStore, Afirmacao] | None:
    for store in _load_all(output_dir, None, None):
        claim = store.get(claim_id)
        if claim is not None:
            return store, claim
    return None


def _resolve(args: argparse.Namespace, output_dir: Path) -> int:
    found = _find(output_dir, args.afirmacao_id)
    if found is None:
        print(f"Afirmação '{args.afirmacao_id}' não encontrada.", file=sys.stderr)
        return 1
    store, claim = found
    if claim.status_afirmacao != "contestada":
        print(
            f"Só afirmações contestadas são revisadas (esta está '{STATUS_LABEL[claim.status_afirmacao]}').",
            file=sys.stderr,
        )
        return 1
    if not args.motivo.strip():
        print("Informe --motivo com a justificativa da decisão.", file=sys.stderr)
        return 2
    review = {"decisao": args.decisao, "motivo": args.motivo.strip(), "em": now_iso()}
    previous = claim.status_afirmacao
    claim.revisao_pesquisador = review
    if args.decisao == "descartada":
        store.change_status(claim, "suportada", ATOR_PESQUISADOR, motivo=review["motivo"], anterior=previous)
    else:
        claim.historico.append(
            {"status": previous, "em": review["em"], "session_id": store.session_id, "ator": ATOR_PESQUISADOR,
             "revisao": "mantida", "motivo": review["motivo"]}
        )
    store.save()
    notes = _after_decision(output_dir, store, claim, args.decisao)
    print(f"Afirmação {claim.codigo} ({claim.afirmacao_id}): contestação {args.decisao}; status agora "
          f"'{STATUS_LABEL[claim.status_afirmacao]}'.")
    for note in notes:
        print(note)
    return 0


def _after_decision(output_dir: Path, store: ClaimStore, claim: Afirmacao, decision: str) -> list[str]:
    """Sinalização ao Curator (mantida em Descoberta) e atualização do nó ``Afirmacao``; falhas viram avisos."""
    notes: list[str] = []
    if not claim.conclusao_id.startswith("desc:"):
        return notes
    if decision == "mantida":
        try:
            from src.knowledge.curator_flags import record_flag

            record_flag(
                output_dir / store.session_id,
                agente="pesquisador",
                subtarefa="claims_resolve",
                tipo="falha_relevante",
                texto=f"O pesquisador manteve a contestação da afirmação: {claim.texto}"[:1000],
                refs=[claim.conclusao_id.removeprefix("desc:")],
            )
            notes.append("Sinalização enviada ao Curator (a evidência do grafo não foi alterada).")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Aviso: sinalização ao Curator não gravada ({type(exc).__name__}).")
    if claim.no_grafo:
        try:
            from src.claims.graph import update_discovery_claim
            from src.knowledge.factory import open_raw_graph_store
            from src.knowledge.provenance import Actor

            graph = open_raw_graph_store()
            try:
                update_discovery_claim(graph, claim.no_grafo, claim, actor=Actor("pesquisador"))
            finally:
                close = getattr(graph, "close", None)
                if callable(close):
                    close()
        except Exception as exc:  # noqa: BLE001 - o arquivo da sessão já guarda a decisão
            notes.append(
                f"Aviso: nó Afirmacao do grafo não atualizado ({type(exc).__name__}); o arquivo da sessão foi."
            )
    return notes


def handle_claims_command(argv: list[str], output_dir: Path | str | None = None) -> int:
    """Trata ``geminiclaw claims <ação>``.

    Args:
        argv: Argumentos após ``claims``.
        output_dir: Raiz de ``outputs/`` (padrão: ``OUTPUT_BASE_DIR``); injetável em testes.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    from src import config

    base = Path(output_dir or config.OUTPUT_BASE_DIR)
    try:
        return _list(args, base) if args.action == "list" else _resolve(args, base)
    except ClaimStoreError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2


def run(argv: list[str]) -> Any:
    """Ponto de entrada de ``main()``."""
    return handle_claims_command(argv)
