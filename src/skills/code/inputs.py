"""Entrada de dados do sandbox: classificador de insumos e validação das origens de montagem (v18.5-sandbox-phases)."""

from __future__ import annotations

import os
import pathlib
import stat
from typing import List, Protocol


class InputClassifier(Protocol):
    """Decide se um insumo é ``compartilhavel`` (pode coexistir com rede na fase ``execute``).

    A rede na fase ``execute`` exige, antes de qualquer outra regra, que o classificador a **autorize
    explicitamente** (``network_allowed``): sem manifesto de dados não há base para afirmar que nada
    sensível está visível, então a ausência de insumos não equivale a "tudo compartilhável".
    """

    def network_allowed(self) -> bool:
        """True somente se o classificador tem base (manifesto de dados) para autorizar rede na execução."""
        ...

    def is_shareable(self, path: pathlib.Path) -> bool:
        """True somente se o arquivo está marcado como compartilhável."""
        ...


class NoneShareableClassifier:
    """Classificador padrão: nenhum insumo é compartilhável (fail-closed) até existir o manifesto de dados.

    A implementação real vem de ``v18.5-research-data-ingestion``; até lá nenhuma execução tem rede.
    """

    def network_allowed(self) -> bool:
        return False

    def is_shareable(self, path: pathlib.Path) -> bool:
        return False


class MountSourceError(ValueError):
    """Origem de montagem recusada (fora do lugar esperado, symlink ou arquivo não regular)."""


def list_input_files(snapshot_dir: pathlib.Path, session_dir: pathlib.Path) -> List[pathlib.Path]:
    """Lista os arquivos de ``snapshot_dir`` recusando symlinks e origens fora de ``session_dir``.

    Raises:
        MountSourceError: ``snapshot_dir`` é symlink ou resolve para fora da sessão, ou contém um symlink
            ou um arquivo que não é regular (FIFO, socket, dispositivo).
    """
    if snapshot_dir.is_symlink() or not snapshot_dir.resolve().is_relative_to(session_dir.resolve()):
        raise MountSourceError("a pasta de insumos da sessão está fora do lugar esperado (ou é um link simbólico)")
    files: List[pathlib.Path] = []
    for dirpath, dirnames, filenames in os.walk(snapshot_dir, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = pathlib.Path(dirpath) / name
            if path.is_symlink():
                rel = path.relative_to(snapshot_dir)
                raise MountSourceError(f"link simbólico em insumos recusado: {rel}")
        for name in filenames:
            path = pathlib.Path(dirpath) / name
            if not stat.S_ISREG(os.lstat(path).st_mode):
                raise MountSourceError(f"arquivo que não é regular em insumos recusado: {path.relative_to(snapshot_dir)}")
            files.append(path)
    return sorted(files)


def check_mount_source(path: pathlib.Path, allowed_root: pathlib.Path) -> pathlib.Path:
    """Resolve ``path`` e confirma que descende de ``allowed_root``, não é symlink e é diretório ou arquivo regular.

    Returns:
        Caminho resolvido.

    Raises:
        MountSourceError: Em qualquer violação.
    """
    if path.is_symlink():
        raise MountSourceError(f"origem de montagem é link simbólico: {path.name}")
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise MountSourceError(f"origem de montagem inacessível: {path.name}") from exc
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise MountSourceError(f"origem de montagem não é diretório nem arquivo regular: {path.name}")
    resolved = path.resolve()
    if not resolved.is_relative_to(allowed_root.resolve()):
        raise MountSourceError(f"origem de montagem fora de {allowed_root.name}: {path.name}")
    return resolved
