"""Leitor do grupo ``verificacao`` de ``v18.5-operation-metrics`` (produtor: ``v18.5-claim-verification``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.claims.store import FILENAME, ClaimStore

GROUP = "verificacao"


class ClaimVerificationReader:
    """Lê ``afirmacoes.json`` da sessão: afirmações por status e ciclos de correção por conclusão."""

    group = GROUP
    producer = "v18.5-claim-verification"

    def __init__(self, output_dir: Path | str) -> None:
        self.output_dir = Path(output_dir)

    def read(self, session_id: str) -> dict[str, Any]:
        """``afirmacoes_por_status`` (as seis chaves) e ``ciclos_correcao_conclusoes``.

        Raises:
            FileNotFoundError: A sessão não gerou ``afirmacoes.json`` (a verificação não rodou).
            ClaimStoreError: O arquivo existe mas está ilegível.
        """
        session_dir = self.output_dir / session_id
        if not (session_dir / FILENAME).is_file():
            raise FileNotFoundError(f"{session_dir / FILENAME} não existe")
        store = ClaimStore.load(session_dir, session_id)
        cycles = [
            {
                "conclusao_id": cid,
                "ciclos": int(entry.get("ciclos") or 0),
                "aprovada": bool(entry.get("aprovada")) if entry.get("aprovada") is not None else None,
            }
            for cid, entry in store.conclusoes.items()
            if cid.startswith("rel:")
        ]
        return {"afirmacoes_por_status": store.counts(), "ciclos_correcao_conclusoes": cycles}
