"""Ativos declarados para o sandbox: validação, verificação de hash no host e cache (v18.5-sandbox-phases §3).

O download acontece no container da fase ``fetch_assets`` (``fetch_assets.py``); o hash é sempre
calculado aqui, no host, e o arquivo verificado vai para o cache por conteúdo
(``SANDBOX_ASSET_CACHE_DIR/<sha256>``), de onde é montado somente leitura na fase ``execute``.
"""

from __future__ import annotations

import errno
import hashlib
import os
import pathlib
import re
import stat
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

from src.skills.code import fetch_assets as _fetch

MAX_ASSETS = 10
MAX_DESTINO_LENGTH = 100
_DESTINO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class AssetSpec:
    """Ativo declarado pelo agente: URL, sha256 esperado (opcional) e nome em ``/assets/<destino>``."""

    url: str
    destino: str
    sha256: Optional[str] = None


@dataclass
class AssetRecord:
    """Ativo disponibilizado à execução, como registrado no resultado do sandbox."""

    url: str
    sha256: str
    destino: str
    tamanho: int
    hash_declarado: bool
    origem: Literal["download", "cache"]


def parse_assets(raw: Optional[List[Any]]) -> tuple[List[AssetSpec], List[str]]:
    """Valida a lista ``assets`` vinda do agente (texto não confiável).

    Cada item precisa de ``url`` http/https sem destino interno, ``destino`` simples (sem ``/`` nem
    ``..``) e, se presente, ``sha256`` com 64 dígitos hexadecimais. Sem ``sha256`` declarado a URL
    precisa ser ``https`` (sem hash, a integridade só vem do TLS).

    Returns:
        Tupla ``(specs, erros)``; ``erros`` traz uma mensagem por problema.
    """
    specs: List[AssetSpec] = []
    errors: List[str] = []
    items = list(raw or [])
    if len(items) > MAX_ASSETS:
        return [], [f"lista de assets com {len(items)} itens: o máximo é {MAX_ASSETS}"]
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"{item!r}: cada ativo deve ser um objeto com url, destino e sha256 opcional")
            continue
        url, destino, sha = item.get("url"), item.get("destino"), item.get("sha256")
        destino_ok = (
            isinstance(destino, str)
            and _DESTINO_RE.fullmatch(destino) is not None
            and len(destino) <= MAX_DESTINO_LENGTH
            and ".." not in destino
        )
        if not destino_ok:
            errors.append(
                f"destino {destino!r} inválido: use um nome simples (letras, dígitos, '.', '_' e '-'), sem '/' nem '..'"
            )
            continue
        if destino in seen:
            errors.append(f"destino {destino!r} repetido")
            continue
        if not isinstance(url, str) or not url.strip():
            errors.append(f"ativo {destino!r}: url ausente")
            continue
        try:
            _fetch.validate_url(url.strip())
        except _fetch.AssetError as exc:
            errors.append(f"ativo {destino!r}: URL recusada ({exc})")
            continue
        if sha is not None and not (isinstance(sha, str) and _SHA256_RE.fullmatch(sha)):
            errors.append(f"ativo {destino!r}: sha256 deve ter 64 dígitos hexadecimais")
            continue
        if sha is None and urllib.parse.urlsplit(url.strip()).scheme != "https":
            errors.append(f"ativo {destino!r}: sem sha256 declarado a URL precisa ser https")
            continue
        seen.add(destino)
        specs.append(AssetSpec(url=url.strip(), destino=destino, sha256=sha.lower() if sha else None))
    return specs, errors


def _open_nofollow(path: pathlib.Path):
    """Abre ``path`` para leitura binária sem seguir symlink no último componente (``O_NOFOLLOW``)."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    return os.fdopen(fd, "rb")


def sha256_file(path: pathlib.Path) -> str:
    """sha256 do conteúdo de ``path`` (lido em blocos), sem seguir symlink.

    Raises:
        OSError: ``path`` é um link simbólico (``ELOOP``) ou não pode ser lido.
    """
    digest = hashlib.sha256()
    with _open_nofollow(path) as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _move_nofollow(source: pathlib.Path, target: pathlib.Path) -> None:
    """Move ``source`` para ``target`` (``rename``; em ``EXDEV``, copia sem seguir symlink, renomeia e apaga a origem)."""
    try:
        os.replace(source, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    partial = target.with_name(target.name + ".part")
    try:
        with _open_nofollow(source) as src, open(partial, "wb") as dst:
            for chunk in iter(lambda: src.read(_HASH_CHUNK), b""):
                dst.write(chunk)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    source.unlink()


def cached_path(cache_dir: pathlib.Path, sha256: str) -> Optional[pathlib.Path]:
    """Caminho do ativo no cache, ou ``None`` se ausente ou se não for arquivo regular (nunca symlink)."""
    path = cache_dir / sha256
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return None
    return path if stat.S_ISREG(mode) else None


def verify_and_cache(
    specs: List[AssetSpec], staging_dir: pathlib.Path, cache_dir: pathlib.Path
) -> tuple[List[AssetRecord], Optional[str]]:
    """Verifica os arquivos baixados em ``staging_dir`` e os move para o cache por conteúdo.

    Returns:
        Tupla ``(registros, erro)``. ``erro`` descreve a primeira falha (arquivo ausente, não regular
        ou sha256 divergente, com os dois hashes); nesse caso a execução deve falhar na fase
        ``fetch_assets``.
    """
    records: List[AssetRecord] = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        staged = staging_dir / spec.destino
        try:
            mode = os.lstat(staged).st_mode
        except FileNotFoundError:
            return records, f"ativo {spec.destino!r} não foi baixado"
        if not stat.S_ISREG(mode):
            return records, f"ativo {spec.destino!r} baixado não é um arquivo regular"
        # Primeiro move o arquivo para um nome privado do cache e só então calcula o hash, sobre o arquivo já
        # movido e sem seguir symlink: o que foi hasheado é exatamente o que entra no cache.
        incoming = cache_dir / f".incoming-{uuid.uuid4().hex}"
        _move_nofollow(staged, incoming)
        try:
            if not stat.S_ISREG(os.lstat(incoming).st_mode):
                return records, f"ativo {spec.destino!r} baixado não é um arquivo regular"
            calculated = sha256_file(incoming)
            if spec.sha256 and spec.sha256 != calculated:
                return records, (
                    f"sha256 do ativo {spec.destino!r} diverge: declarado {spec.sha256}, calculado {calculated}"
                )
            size = os.lstat(incoming).st_size
            if cached_path(cache_dir, calculated) is None:
                os.replace(incoming, cache_dir / calculated)
            else:
                incoming.unlink()
        finally:
            incoming.unlink(missing_ok=True)
        records.append(
            AssetRecord(
                url=spec.url,
                sha256=calculated,
                destino=spec.destino,
                tamanho=size,
                hash_declarado=spec.sha256 is not None,
                origem="download",
            )
        )
    return records, None
