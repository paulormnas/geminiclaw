"""Geração de identificadores para o grafo de conhecimento (ADR 015 §2).

Fornece IDs de nó estáveis, ordenáveis por tempo de criação (UUIDv7, RFC 9562)
e o identificador persistente do computador (``NODE_ID``) usado para marcar a
origem de sessões e experimentos (fator de independência, ADR 015 §9).

Python 3.11 não inclui ``uuid.uuid7`` na stdlib (adicionado apenas na 3.14),
por isso a implementação abaixo é autocontida — sem novas dependências
(princípio de footprint mínimo, ``backend-dev.md``).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from src.logger import get_logger

logger = get_logger(__name__)

_APP_CONFIG_DIRNAME = "geminiclaw"
_NODE_ID_FILENAME = "node_id"

# Estado para o método "monotonic random" (RFC 9562 §6.2, método 2): dentro do
# mesmo milissegundo, os 74 bits aleatórios (rand_a + rand_b) são tratados como
# um contador que só incrementa — garante que uuid7() chamado em sequência
# rápida (várias vezes no mesmo ms, comum em testes e em escritas em lote no
# grafo) produza IDs estritamente ordenáveis, não só "prováveis de estar
# ordenados". Fora do mesmo milissegundo, os bits voltam a ser aleatórios
# (RFC 9562 recomenda não reiniciar do zero, mas um novo valor aleatório aqui
# não compromete a ordenação, que já é garantida pelo timestamp).
_lock = threading.Lock()
_last_ts_ms: int = -1
_last_rand74: int = 0

_RAND74_MASK = (1 << 74) - 1


def uuid7() -> uuid.UUID:
    """Gera um UUID versão 7 (RFC 9562): ordenável por tempo, monotônico dentro do mesmo ms.

    Layout dos 128 bits:
        - 48 bits: timestamp Unix em milissegundos (big-endian).
        - 4 bits: versão (``0111``).
        - 12 bits: ``rand_a`` (parte do contador monotônico dentro do ms).
        - 2 bits: variante (``10``).
        - 62 bits: ``rand_b`` (parte do contador monotônico dentro do ms).

    Chamadas sucessivas no mesmo milissegundo incrementam o contador de 74
    bits (método "monotonic random" do RFC 9562 §6.2) em vez de sortear um
    valor totalmente novo — garante ordenação lexicográfica estrita mesmo em
    rajadas de chamadas na mesma thread ou entre threads (protegido por lock).

    Returns:
        Uma instância de ``uuid.UUID`` com a versão 7.
    """
    global _last_ts_ms, _last_rand74

    with _lock:
        unix_ts_ms = int(time.time() * 1000)

        if unix_ts_ms > _last_ts_ms:
            _last_ts_ms = unix_ts_ms
            _last_rand74 = int.from_bytes(os.urandom(10), byteorder="big") & _RAND74_MASK
        else:
            # Mesmo ms (ou relógio andou para trás): avança o contador. Em caso
            # de overflow dos 74 bits (bilhões de chamadas no mesmo ms — não
            # ocorre na prática), avança o timestamp lógico em 1ms para manter
            # a ordenação estrita.
            _last_rand74 = (_last_rand74 + 1) & _RAND74_MASK
            if _last_rand74 == 0:
                _last_ts_ms += 1
            unix_ts_ms = _last_ts_ms

        ts_bytes = unix_ts_ms.to_bytes(6, byteorder="big")
        rand_a = (_last_rand74 >> 62) & 0xFFF  # 12 bits altos
        rand_b = _last_rand74 & ((1 << 62) - 1)  # 62 bits baixos

        byte6 = 0x70 | ((rand_a >> 8) & 0x0F)  # versão 7 no nibble alto + 4 bits de rand_a
        byte7 = rand_a & 0xFF  # 8 bits restantes de rand_a
        rand_b_bytes = rand_b.to_bytes(8, byteorder="big")  # 62 bits em 8 bytes (2 bits altos livres)
        byte8 = 0x80 | (rand_b_bytes[0] & 0x3F)  # variante RFC (10) + 6 bits de rand_b
        rest = rand_b_bytes[1:8]  # 56 bits restantes de rand_b

        raw = ts_bytes + bytes([byte6, byte7, byte8]) + rest
        return uuid.UUID(bytes=raw)


def generate_node_id() -> str:
    """Gera um novo identificador de nó do grafo (UUIDv7, texto).

    Returns:
        Representação em texto (formato canônico) de um UUIDv7 novo.
    """
    return str(uuid7())


def _node_id_config_dir() -> Path:
    """Resolve o diretório de configuração persistente do ``NODE_ID``.

    Respeita ``XDG_CONFIG_HOME`` quando definido; caso contrário usa
    ``~/.config``.

    Returns:
        Caminho do diretório ``<config_base>/geminiclaw``.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    config_base = Path(base) if base else Path.home() / ".config"
    return config_base / _APP_CONFIG_DIRNAME


def get_or_create_node_id(config_dir: Path | None = None) -> str:
    """Obtém o identificador estável deste computador (``NODE_ID``).

    Gerado uma única vez (UUIDv7) e persistido em disco; chamadas
    subsequentes, inclusive após reinícios, retornam o mesmo valor.

    Args:
        config_dir: Diretório onde persistir o arquivo ``node_id``. Se
            omitido, usa ``~/.config/geminiclaw`` (ou ``$XDG_CONFIG_HOME``).

    Returns:
        O ``NODE_ID`` (texto) estável deste computador.
    """
    directory = config_dir if config_dir is not None else _node_id_config_dir()
    node_id_path = directory / _NODE_ID_FILENAME

    try:
        if node_id_path.exists():
            existing = node_id_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
            logger.warning(
                "Arquivo de NODE_ID vazio; gerando novo identificador.",
                extra={"extra": {"path": str(node_id_path)}},
            )
    except OSError as exc:
        logger.warning(
            "Não foi possível ler o NODE_ID existente; gerando valor efêmero para esta execução.",
            extra={"extra": {"path": str(node_id_path), "error": str(exc)}},
        )
        return generate_node_id()

    new_node_id = generate_node_id()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        node_id_path.write_text(new_node_id, encoding="utf-8")
        logger.info(
            "NODE_ID gerado e persistido.",
            extra={"extra": {"path": str(node_id_path)}},
        )
    except OSError as exc:
        logger.warning(
            "Não foi possível persistir NODE_ID; usando valor efêmero para esta execução.",
            extra={"extra": {"path": str(node_id_path), "error": str(exc)}},
        )
    return new_node_id
