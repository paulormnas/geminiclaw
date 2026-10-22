"""Aponta o processo do runner para os bancos de benchmark (``src.config`` lê o ambiente na importação)."""

from __future__ import annotations

import os
import sys

from scripts.benchmark import reset_stores

CHAVES_DO_ALVO = ("DATABASE_URL", "QDRANT_URL", "KNOWLEDGE_READER_DATABASE_URL")


class AlvoNaoAplicado(RuntimeError):
    """O processo ainda aponta para o banco de desenvolvimento; nada foi escrito."""


def aplicar_alvo_ao_processo(env_base: dict[str, str]) -> None:
    """Aponta o próprio processo (ambiente e ``src.config``) para os bancos de benchmark.

    ``src.config`` lê o ambiente na importação, e o orquestrador importa módulos de ``src`` antes de conhecer o alvo;
    sem este ajuste a semeadura e a leitura do grafo usariam o banco de desenvolvimento (``DATABASE_URL`` do ``.env``).
    """
    from src import config

    for chave in CHAVES_DO_ALVO:
        valor = env_base.get(chave)
        if not valor:
            continue
        os.environ[chave] = valor
        setattr(config, chave, valor)
    for modulo, atributo in (("src.memory.qdrant", "QDRANT_URL"), ("src.cli.infrastructure", "DATABASE_URL"),
                             ("src.cli.infrastructure", "QDRANT_URL")):
        if modulo in sys.modules and env_base.get(atributo):
            setattr(sys.modules[modulo], atributo, env_base[atributo])


def conferir_alvo_do_processo(target: reset_stores.BenchmarkTarget) -> None:
    """Recusa seguir se ``src.config`` ainda aponta para outro banco que o de benchmark (fail-fast).

    Raises:
        AlvoNaoAplicado: ``DATABASE_URL`` do processo não é o banco do alvo.
    """
    from urllib.parse import urlsplit

    from src import config

    banco = urlsplit(config.DATABASE_URL or "").path.lstrip("/")
    if banco != target.database:
        raise AlvoNaoAplicado(
            f"O processo aponta para o banco '{banco}' e o alvo é '{target.database}': a semeadura escreveria no banco "
            "errado. Chame aplicar_alvo_ao_processo antes de executar as explorações."
        )
