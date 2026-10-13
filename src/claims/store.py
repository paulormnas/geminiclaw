"""``outputs/<sessão>/afirmacoes.json``: gravação atômica, histórico somente acréscimo (design §2)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.claims.model import FILE_VERSION, Afirmacao, Conclusao
from src.logger import get_logger

logger = get_logger(__name__)

FILENAME = "afirmacoes.json"


class ClaimStoreError(ValueError):
    """Arquivo de afirmações ilegível ou de versão desconhecida (mensagem acionável)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def history_entry(status: str, session_id: str | None, ator: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "em": now_iso(), "session_id": session_id, "ator": ator, **extra}


class ClaimStore:
    """Afirmações e conclusões de uma sessão.

    Um status novo entra em ``historico``; o anterior nunca é apagado. ``save`` é atômico (arquivo temporário + rename).
    """

    def __init__(self, session_dir: Path | str, session_id: str) -> None:
        self.session_dir = Path(session_dir)
        self.session_id = session_id
        self.conclusoes: dict[str, dict[str, Any]] = {}
        self.afirmacoes: list[Afirmacao] = []
        # v18.6-hypothesis-closure: por que não há afirmações (gravado só quando a lista é vazia).
        self.motivo_vazio: str | None = None

    @property
    def path(self) -> Path:
        return self.session_dir / FILENAME

    @classmethod
    def load(cls, session_dir: Path | str, session_id: str) -> "ClaimStore":
        """Carrega o arquivo da sessão (vazio, se não existir).

        Raises:
            ClaimStoreError: JSON inválido ou versão mais nova que a suportada.
        """
        store = cls(session_dir, session_id)
        if not store.path.is_file():
            return store
        try:
            data = json.loads(store.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ClaimStoreError(
                f"{store.path} ilegível ({type(exc).__name__}); corrija ou remova o arquivo."
            ) from exc
        if not isinstance(data, dict) or int(data.get("versao", 0)) > FILE_VERSION:
            raise ClaimStoreError(f"{store.path}: versão não suportada (esperada ≤ {FILE_VERSION}).")
        store.conclusoes = {c["conclusao_id"]: c for c in data.get("conclusoes", []) if isinstance(c, dict)}
        store.afirmacoes = [Afirmacao.from_dict(a) for a in data.get("afirmacoes", []) if isinstance(a, dict)]
        store.motivo_vazio = data.get("motivo_vazio") if isinstance(data.get("motivo_vazio"), str) else None
        return store

    def save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "versao": FILE_VERSION,
            "session_id": self.session_id,
            "conclusoes": list(self.conclusoes.values()),
            "afirmacoes": [a.to_dict() for a in self.afirmacoes],
        }
        if not self.afirmacoes and self.motivo_vazio:
            payload["motivo_vazio"] = self.motivo_vazio
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    # --- escrita ---------------------------------------------------------------------------------------------------

    def put_conclusion(self, conclusao: Conclusao) -> None:
        self.conclusoes[conclusao.conclusao_id] = conclusao.to_dict()

    def add(self, afirmacao: Afirmacao, ator: str = "orquestrador") -> None:
        """Acrescenta a afirmação, com a primeira entrada do histórico."""
        afirmacao.session_id = afirmacao.session_id or self.session_id
        if not afirmacao.historico:
            afirmacao.historico.append(history_entry(afirmacao.status_afirmacao, self.session_id, ator))
        self.afirmacoes.append(afirmacao)

    def change_status(
        self, afirmacao: Afirmacao, status: str, ator: str, session_id: str | None = None, **extra: Any
    ) -> None:
        """Muda o status acrescentando ao histórico (nunca apaga o anterior)."""
        afirmacao.status_afirmacao = status
        afirmacao.historico.append(history_entry(status, session_id or self.session_id, ator, **extra))

    def next_code(self) -> str:
        used = [int(a.codigo[1:]) for a in self.afirmacoes if a.codigo[1:].isdigit()]
        return f"A{max(used, default=0) + 1}"

    # --- leitura ---------------------------------------------------------------------------------------------------

    def get(self, afirmacao_id: str) -> Afirmacao | None:
        return next((a for a in self.afirmacoes if a.afirmacao_id == afirmacao_id), None)

    def active(self) -> list[Afirmacao]:
        """Afirmações vigentes (as substituídas por um ciclo de correção ficam de fora)."""
        return [a for a in self.afirmacoes if a.substituida_por is None]

    def for_conclusion(self, conclusao_id: str, only_active: bool = True) -> list[Afirmacao]:
        items = self.active() if only_active else self.afirmacoes
        return [a for a in items if a.conclusao_id == conclusao_id]

    def pending(self) -> list[Afirmacao]:
        return [a for a in self.active() if a.status_afirmacao == "pendente"]

    def counts(self, claims: Iterable[Afirmacao] | None = None) -> dict[str, int]:
        from src.claims.model import STATUSES

        out = {s: 0 for s in STATUSES}
        for claim in claims if claims is not None else self.active():
            out[claim.status_afirmacao] += 1
        return out
