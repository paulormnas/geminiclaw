"""Registro de egresso (v18.5-egress-gate, design §8).

Uma linha em ``egress_log`` (PostgreSQL) por envio externo, inclusive recusas e destinos ``no_no``; o payload exato
enviado é acrescentado a ``outputs/<sessão>/egress/envios.jsonl.gz`` (auditoria no nó). O conteúdo em si não vai ao
banco. **Fail-fast:** falha ao gravar levanta :class:`EgressLogError` e o envio não ocorre.
"""

from __future__ import annotations

import gzip
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

ENVIOS_FILENAME = "envios.jsonl.gz"


class EgressError(RuntimeError):
    """Erro da camada de saída."""


class EgressLogError(EgressError):
    """Não foi possível gravar o registro de egresso: o envio não ocorre."""


@dataclass
class EgressRecord:
    """Linha de ``egress_log`` (design §8)."""

    session_id: str
    canal: str
    provedor: str
    localidade: str
    aceita_dados_brutos: bool
    bytes_enviados: int
    papel: str | None = None
    modelo: str | None = None
    versao_efetiva: str | None = None
    trust: str | None = None
    bytes_saida_execucao_novos: int = 0
    fragmentos: list[dict[str, Any]] = field(default_factory=list)
    intervencoes: dict[str, int] = field(default_factory=dict)
    recusado: bool = False
    motivo_recusa: str | None = None
    id: str = field(default_factory=lambda: f"egr_{uuid.uuid4()}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_INSERT_SQL = """
    INSERT INTO egress_log (
        id, session_id, created_at, canal, papel, provedor, modelo, versao_efetiva, trust, localidade,
        aceita_dados_brutos, bytes_enviados, bytes_saida_execucao_novos, fragmentos, intervencoes,
        recusado, motivo_recusa
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
"""
_SUM_SQL = "SELECT COALESCE(SUM(bytes_saida_execucao_novos), 0) AS total FROM egress_log WHERE session_id = %s"


class EgressLog:
    """Grava o registro de egresso de uma sessão (banco + cópia local compactada)."""

    def __init__(self, session_id: str, output_dir: Path | str | None = None) -> None:
        self.session_id = session_id
        self._output_dir = Path(output_dir) if output_dir is not None else None
        self._lock = threading.Lock()

    @property
    def envios_path(self) -> Path | None:
        if self._output_dir is None:
            return None
        return self._output_dir / self.session_id / "egress" / ENVIOS_FILENAME

    def write(self, record: EgressRecord, payload: dict[str, Any] | None = None) -> None:
        """Grava a linha e acrescenta o payload exato à cópia local.

        Raises:
            EgressLogError: Banco indisponível ou disco sem escrita (o envio não deve ocorrer).
        """
        try:
            from src import db

            with db.get_connection() as conn:
                conn.execute(
                    _INSERT_SQL,
                    (
                        record.id,
                        record.session_id,
                        record.created_at,
                        record.canal,
                        record.papel,
                        record.provedor,
                        record.modelo,
                        record.versao_efetiva,
                        record.trust,
                        record.localidade,
                        record.aceita_dados_brutos,
                        record.bytes_enviados,
                        record.bytes_saida_execucao_novos,
                        json.dumps(record.fragmentos, ensure_ascii=False),
                        json.dumps(record.intervencoes, ensure_ascii=False),
                        record.recusado,
                        record.motivo_recusa,
                    ),
                )
        except Exception as exc:  # noqa: BLE001 — qualquer falha de gravação impede o envio
            raise EgressLogError(
                f"Falha ao gravar o registro de egresso ({type(exc).__name__}): o envio não foi feito. "
                "Verifique o PostgreSQL (docker compose up -d) e a migração scripts/migrations/v18_5_egress_log.sql."
            ) from exc
        self._append_local(record, payload)

    def _append_local(self, record: EgressRecord, payload: dict[str, Any] | None) -> None:
        path = self.envios_path
        if path is None or payload is None:
            return
        line = json.dumps(
            {
                "id": record.id,
                "created_at": record.created_at.isoformat(),
                "canal": record.canal,
                "provedor": record.provedor,
                "modelo": record.modelo,
                "recusado": record.recusado,
                "payload": payload,
            },
            ensure_ascii=False,
        )
        try:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "at", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            raise EgressLogError(
                f"Falha ao gravar a cópia local dos envios em '{path}' ({type(exc).__name__}): o envio não foi feito. "
                "Verifique permissão e espaço em disco."
            ) from exc

    def bytes_for_session(self, session_id: str | None = None) -> int:
        """Soma de ``bytes_saida_execucao_novos`` da sessão (design §9)."""
        return egress_bytes_for_session(session_id or self.session_id)


def egress_bytes_for_session(session_id: str) -> int:
    """Volume de egresso de saídas de execução (já contado uma vez por destino) de uma sessão.

    Raises:
        EgressLogError: Banco indisponível (o volume não pode ser conferido).
    """
    try:
        from src import db

        with db.get_connection() as conn:
            row = conn.execute(_SUM_SQL, (session_id,)).fetchone()
    except Exception as exc:  # noqa: BLE001
        raise EgressLogError(
            f"Não foi possível ler o volume de egresso da sessão '{session_id}' ({type(exc).__name__})."
        ) from exc
    if row is None:
        return 0
    value = row["total"] if isinstance(row, dict) else row[0]
    return int(value or 0)
