"""``geminiclaw provenance verify|export`` (v18.5-execution-provenance, design §7 e §8).

Códigos de saída de ``verify``: 0 (íntegra, possivelmente com órfãs e ausentes listados), 1 (cadeia quebrada, arquivo
alterado, checkpoint divergente ou conflito de pendência) e 2 (verificação impossível, ex.: banco indisponível).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.provenance.errors import ProvenanceError, ProvenanceUnavailable
from src.provenance.export import export_session
from src.provenance.hashing import HashCache
from src.provenance.ledger import ExecutionLedger, get_ledger
from src.provenance.verify import LIMITS, VerifyReport, verify_export, verify_project, verify_session

VERIFY_HELP = (
    "Recalcula a cadeia de hash do projeto, confere os pares início/término, os hashes das entradas e saídas em disco, "
    "lista execuções órfãs e confere as pontas gravadas nos checkpoints. Limites: " + LIMITS
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geminiclaw provenance", description="Registro de execuções encadeado por hash (ADR 019 §4)."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    verify = sub.add_parser("verify", help="Verifica a cadeia de execuções de um projeto.", description=VERIFY_HELP)
    verify.add_argument("project", nargs="?", help="Projeto (ou sem_projeto:<sessão>) a verificar.")
    verify.add_argument("--session", help="Verifica só as execuções de uma sessão.")
    verify.add_argument("--full", action="store_true", help="Ignora o cache de hash dos arquivos.")
    verify.add_argument("--json", action="store_true", help="Saída em JSON.")
    verify.add_argument("--from-export", metavar="DIR", help="Verifica, sem banco, um diretório provenance/ exportado.")
    export = sub.add_parser("export", help="Exporta o segmento da cadeia de uma sessão.")
    export.add_argument("--session", required=True, help="Sessão a exportar.")
    return parser


def _emit(reports: list[VerifyReport], as_json: bool) -> int:
    if as_json:
        print(json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(r.render() for r in reports))
    return max((r.exit_code for r in reports), default=0)


def handle_provenance_command(argv: list[str], ledger: ExecutionLedger | None = None) -> int:
    """Trata ``geminiclaw provenance <ação>``.

    Args:
        argv: Argumentos após ``provenance``.
        ledger: Livro a usar (padrão: o do processo); injetável em testes.
    """
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    from src import config

    book = ledger or get_ledger()
    output_dir: Path = Path(config.OUTPUT_BASE_DIR)
    try:
        if args.action == "export":
            target = export_session(book.store, args.session, output_dir)
            if target is None:
                print(f"A sessão '{args.session}' não tem execuções registradas.")
                return 0
            print(f"Segmento da cadeia exportado em {target}")
            return 0
        if args.from_export:
            reports = verify_export(args.from_export)
            return _emit(reports, args.json)
        cache = (
            None
            if args.full
            else HashCache(config.PROVENANCE_HASH_CACHE_PATH, config.PROVENANCE_HASH_CACHE_MIN_BYTES)
        )
        if args.session:
            reports = verify_session(book.store, args.session, output_dir, full=args.full, cache=cache)
            if not reports:
                print(f"A sessão '{args.session}' não tem execuções registradas.")
                return 0
        elif args.project:
            reports = [verify_project(book.store, args.project, output_dir, full=args.full, cache=cache)]
        else:
            print("Informe o projeto ou --session <id> (ou --from-export <dir>).", file=sys.stderr)
            return 2
        return _emit(reports, args.json)
    except ProvenanceUnavailable as exc:
        print(f"Verificação impossível: {exc}", file=sys.stderr)
        return 2
    except ProvenanceError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2


def run(argv: list[str]) -> Any:
    """Ponto de entrada de ``main()``: abre o pool do banco e fecha ao terminar."""
    from src.db import close_pool

    try:
        return handle_provenance_command(argv)
    finally:
        close_pool()
