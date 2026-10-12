"""Utilitário de plataforma e imagens (v16-platform-images, design §3).

Uso::

    uv run python -m scripts.platform_images detect [--json]
    uv run python -m scripts.platform_images plan   [--imagens a,b] [--com-ollama] [--json] [--estrito]
    uv run python -m scripts.platform_images ensure [--imagens a,b] [--com-ollama] [--yes] [--json] [--estrito]

``detect`` mostra a plataforma; ``plan`` calcula o que fazer em cada imagem sem alterar nada; ``ensure`` obtém
(``pull``/``build``) com ``platform=linux/<arquitetura do daemon>``, confere a arquitetura e grava
``store/platform.json``. Códigos de saída: 0 tudo certo; 1 erro; 2 há imagem ``nao_validada`` (só com ``--estrito``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from src.platform_images import (
    PLATFORM_FILE,
    PROJECT_ROOT,
    WARNING_NOT_VALIDATED,
    PlatformImageError,
    current_platform,
    docker_client,
    ensure_images,
    load_manifest,
    plan_images,
    select_images,
)
from src.platform_info import PlatformInfo, detect_current

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_VALIDATED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform_images", description="Plataforma e imagens do GeminiClaw.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("detect", "Mostra a plataforma detectada."),
        ("plan", "Calcula o que fazer em cada imagem, sem alterar nada."),
        ("ensure", "Obtém as imagens necessárias e confere a arquitetura."),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--json", action="store_true", help="Saída em JSON.")
        if name != "detect":
            p.add_argument("--imagens", default="", help="Nomes separados por vírgula (padrão: as não opcionais).")
            p.add_argument("--com-ollama", action="store_true", help="Inclui a imagem opcional do Ollama.")
            p.add_argument("--estrito", action="store_true", help="Código 2 se alguma imagem estiver nao_validada.")
        if name == "ensure":
            p.add_argument("--yes", action="store_true", help="Não pede confirmação antes de baixar/construir.")
    return parser


def _split(value: str) -> list[str] | None:
    names = [part.strip() for part in value.split(",") if part.strip()]
    return names or None


def _print_platform(info: PlatformInfo, as_json: bool, out: Callable[[str], Any]) -> None:
    if as_json:
        out(json.dumps(info.to_dict(), indent=2, ensure_ascii=False))
        return
    out(f"Plataforma: {info.id}")
    out(f"  host: {info.host_os}/{info.host_arch} | daemon: {info.daemon_os}/{info.daemon_arch}")
    out(f"  placa: {info.board or '-'} | tamanho de página: {info.page_size or '-'}")
    out(f"  alvo das imagens: {info.target or 'desconhecido (daemon inacessível)'}")


def run(
    argv: Sequence[str] | None = None,
    *,
    client: Any | None = None,
    out: Callable[[str], Any] = print,
    input_fn: Callable[[str], str] = input,
    platform_file: Path | None = PLATFORM_FILE,
    project_root: Path = PROJECT_ROOT,
) -> int:
    """Executa o subcomando e devolve o código de saída."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "detect":
            try:
                client = client or docker_client(timeout=5)
                info = current_platform(client)
            except PlatformImageError as exc:
                out(f"Aviso: {exc}")
                info = detect_current()  # parcial: só o host
            _print_platform(info, args.json, out)
            return EXIT_OK
        client = client or docker_client()
        info = current_platform(client)
        specs = select_images(load_manifest(), _split(args.imagens), with_ollama=args.com_ollama)
        if args.command == "plan":
            items = plan_images(specs, info, client)
            avisos = [i for i in items if WARNING_NOT_VALIDATED in i.avisos]
            if args.json:
                out(json.dumps({"plataforma": info.to_dict(), "plano": [i.to_dict() for i in items]},
                               indent=2, ensure_ascii=False))
            else:
                out(f"Plataforma: {info.id}")
                for item in items:
                    flag = f"  [aviso: {', '.join(item.avisos)}]" if item.avisos else ""
                    out(f"  {item.nome:<10} {item.estado:<12} {item.referencia}{flag}")
                    if item.detalhe:
                        out(f"             {item.detalhe}")
            return EXIT_NOT_VALIDATED if args.estrito and avisos else EXIT_OK
        result = ensure_images(
            specs, info, client, assume_yes=args.yes, input_fn=input_fn, out=out,
            platform_file=platform_file, project_root=project_root,
        )
        if args.json:
            out(json.dumps({"plataforma": info.to_dict(), "imagens": result.imagens, "avisos": result.avisos},
                           indent=2, ensure_ascii=False))
        else:
            for name, entry in result.imagens.items():
                out(f"  {name:<10} {entry['referencia']} ({entry.get('arquitetura') or '-'})")
            for warning in result.avisos:
                out(f"  Aviso: {warning}")
            out("Resultado gravado em store/platform.json.")
        return EXIT_NOT_VALIDATED if args.estrito and result.avisos else EXIT_OK
    except PlatformImageError as exc:
        out(f"Erro: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(run())
