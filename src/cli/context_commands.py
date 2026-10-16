"""Contexto de `input_context/` no terminal: carga com confirmação e limpeza.

Movido de ``src/cli/main.py`` sem alterar o comportamento (v18.7-background-sessions, tarefa 0.9; ADR 024 §5).
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.config import (
    CONTEXT_TOKEN_WARNING_THRESHOLD,
    INPUT_CONTEXT_DIR,
)
from src.llm.vision import VisionConfigError
from src.logger import get_logger
from src.research_data.context_loader import ContextBundle, ContextLoader
from src.research_data.manifest import ManifestError
from src.utils.terminal import DIM, GREEN, RED, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)


def load_context_with_confirmation(context_dir: str | None = None) -> ContextBundle | None:
    """Carrega `input_context/` e confirma com o pesquisador se o volume for grande
    (Roadmap V15.5 / Spec G9).

    Args:
        context_dir: Diretório de contexto a carregar (usa o padrão de config se omitido).

    Returns:
        O `ContextBundle` carregado, ou None se o pesquisador optou por não continuar.
    """
    try:
        bundle = ContextLoader(context_dir).load()
    except (ManifestError, VisionConfigError) as e:
        # v18.5-research-data-ingestion: manifesto inválido ou visão mal configurada impedem a sessão.
        print(f"\n  {STATUS_ICONS['error']} {RED}input_context/: {e}{RESET}\n")
        logger.error("Contexto de entrada inválido", extra={"error": str(e)})
        return None

    if bundle.total_files == 0:
        print(f"  {DIM}📂 Nenhum contexto encontrado em input_context/.{RESET}")
        return bundle

    print(
        f"  {GREEN}📂 Contexto carregado:{RESET} {bundle.total_files} arquivo(s) "
        f"({bundle.total_tokens_estimated} tokens estimados)"
    )
    for warning in bundle.manifest_warnings:
        print(f"  {YELLOW}⚠ {warning}{RESET}")

    if bundle.total_tokens_estimated > CONTEXT_TOKEN_WARNING_THRESHOLD:
        print(
            f"  {YELLOW}⚠ Contexto muito grande (~{bundle.total_tokens_estimated} tokens).{RESET} "
            f"Recomendado: remover arquivos menos relevantes ou usar chunking."
        )
        answer = input("  Continuar? [s/N] ").strip().lower()
        if answer not in ("s", "sim", "y", "yes"):
            print(f"  {DIM}Execução cancelada pelo pesquisador.{RESET}")
            return None

    return bundle


def print_context_lifecycle_message(session_id: str, bundle: ContextBundle) -> None:
    """Exibe a instrução de gestão do ciclo de vida do contexto ao final da sessão
    (Roadmap V15.5 / Spec G9).
    """
    if bundle.total_files == 0:
        return
    print(
        f"\n  {DIM}Contexto salvo em outputs/{session_id}/input_snapshot/. "
        f"Execute 'geminiclaw clear-context' para limpar input_context/ para a próxima sessão.{RESET}"
    )


def clear_context(context_dir: str | None = None) -> None:
    """Limpa `input_context/` após confirmação do pesquisador (Roadmap V15.5 / Spec G9)."""
    target_dir = Path(context_dir or INPUT_CONTEXT_DIR)
    if not target_dir.is_dir():
        print(f"\n  {DIM}input_context/ não existe — nada para limpar.{RESET}\n")
        return

    files = [p for p in target_dir.iterdir() if p.is_file() and p.name != "README.md"]
    dirs = [p for p in target_dir.iterdir() if p.is_dir()]
    if not files and not dirs:
        print(f"\n  {DIM}input_context/ já está vazio.{RESET}\n")
        return

    print(
        f"\n  {YELLOW}⚠ Isso removerá {len(files) + len(dirs)} item(ns) de input_context/ "
        f"(README.md é preservado).{RESET}"
    )
    answer = input("  Confirmar limpeza? [s/N] ").strip().lower()
    if answer not in ("s", "sim", "y", "yes"):
        print(f"  {DIM}Operação cancelada.{RESET}\n")
        return

    import shutil
    for p in files:
        p.unlink()
    for d in dirs:
        shutil.rmtree(d)

    print(f"  {GREEN}✅ input_context/ limpo com sucesso.{RESET}\n")
