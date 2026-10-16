"""Ambiente isolado para testar ``src.config`` (v18.7-resource-monitor-config).

Define as variáveis pedidas sobre um ambiente vazio, sem ler o ``.env`` local, deixa o teste reimportar ``src.config`` e,
ao sair, restaura o ambiente e o módulo. Substitui os ``importlib.reload(src.config)`` avulsos. Reutilizado pelas
mudanças V18.7 seguintes (``v18.7-exploration-limits``).
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from types import ModuleType
from unittest.mock import patch

import src.config


@contextmanager
def env_override(env: Mapping[str, str] | None = None, *, clear: bool = True) -> Iterator[Callable[[], ModuleType]]:
    """Aplica ``env`` (sobre um ambiente vazio, salvo ``clear=False``) e devolve ``load()``, que reimporta ``src.config``.

    ``load()`` levanta o que a importação levantar (por exemplo, ``ConfigurationError``).
    """
    saved = dict(os.environ)
    with patch("dotenv.load_dotenv"):
        try:
            if clear:
                os.environ.clear()
            os.environ.update(env or {})
            yield lambda: importlib.reload(src.config)
        finally:
            os.environ.clear()
            os.environ.update(saved)
            importlib.reload(src.config)
