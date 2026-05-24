"""WorkspaceManifest — registro estruturado de execução por sessão.

Implementa V13.3.1: criação, atualização e leitura do manifest.json
da sessão com escrita atômica (tmp + rename) para evitar corrupção.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.logger import get_logger

logger = get_logger(__name__)

_MANIFEST_FILENAME = "manifest.json"
_MANIFEST_TMP_SUFFIX = ".manifest.tmp.json"


def _now_iso() -> str:
    """Retorna timestamp ISO-8601 UTC sem microsegundos."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WorkspaceManifest:
    """Gerencia o manifest.json de uma sessão de agente.

    O manifest é a fonte de verdade sobre o que foi executado em cada
    tool call: artefatos produzidos, erros encontrados e sugestões para
    o próximo step.

    Escrita atômica: os dados são escritos em um arquivo temporário e
    depois renomeados sobre o manifest definitivo, garantindo que uma
    falha durante a escrita não corrompa o manifest anterior.

    Args:
        session_dir: Diretório da sessão no host (ex: outputs/<session_id>/).
        session_id: Identificador canônico da sessão.
        task_name: Nome da subtarefa associada.
    """

    def __init__(
        self,
        session_dir: pathlib.Path,
        session_id: str,
        task_name: str,
    ) -> None:
        self._session_dir = pathlib.Path(session_dir)
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._session_dir / _MANIFEST_FILENAME
        self._session_id = session_id
        self._task_name = task_name

        if not self._path.exists():
            self._write(self._empty_manifest())

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def record_step(
        self,
        step: int,
        status: str,
        artifacts: List[str],
        summary: str,
        error: Optional[Dict[str, str]] = None,
        code_file: Optional[str] = None,
    ) -> None:
        """Registra o resultado de um step de execução.

        Args:
            step: Número sequencial do step (começa em 1).
            status: ``"success"`` ou ``"failed"``.
            artifacts: Lista de nomes de arquivo criados neste step.
            summary: Resumo legível do que aconteceu.
            error: Dicionário com ``error_type``, ``error_message`` e
                ``error_location`` (apenas quando ``status="failed"``).
            code_file: Nome do arquivo de snapshot do código (ex: ``step_01.py``).

        Raises:
            ValueError: Se ``status`` não for ``"success"`` ou ``"failed"``.
        """
        if status not in ("success", "failed"):
            raise ValueError(f"status deve ser 'success' ou 'failed', recebeu: {status!r}")

        manifest = self.read()

        step_entry: Dict[str, Any] = {
            "step": step,
            "status": status,
            "timestamp": _now_iso(),
            "artifacts_created": artifacts,
            "summary": summary,
        }
        if code_file:
            step_entry["code_file"] = code_file
        if status == "failed" and error:
            step_entry["error_type"] = error.get("error_type", "")
            step_entry["error_message"] = error.get("error_message", "")
            step_entry["error_location"] = error.get("error_location", "")

        manifest["steps"].append(step_entry)

        # Atualizar lista cumulativa de artefatos disponíveis
        existing = set(manifest.get("artifacts_available", []))
        existing.update(artifacts)
        if code_file:
            existing.add(code_file)
        manifest["artifacts_available"] = sorted(existing)

        manifest["last_updated"] = _now_iso()
        self._write(manifest)

        logger.info(
            "Manifest atualizado",
            extra={
                "session_id": self._session_id,
                "step": step,
                "status": status,
                "artifacts_count": len(artifacts),
            },
        )

    def update_next_hint(self, hint: str) -> None:
        """Atualiza a sugestão de próximo step no manifest.

        Args:
            hint: Texto descrevendo o que o agente deveria fazer em seguida.
        """
        manifest = self.read()
        manifest["next_step_hint"] = hint
        manifest["last_updated"] = _now_iso()
        self._write(manifest)

    def read(self) -> Dict[str, Any]:
        """Lê e retorna o manifest atual como dicionário.

        Returns:
            Dicionário com os dados do manifest. Nunca retorna None —
            se o arquivo não existir, retorna um manifest vazio.
        """
        if not self._path.exists():
            return self._empty_manifest()
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Falha ao ler manifest; retornando manifest vazio",
                extra={"error": str(exc), "path": str(self._path)},
            )
            return self._empty_manifest()

    def get_artifacts_available(self) -> List[str]:
        """Retorna a lista cumulativa de artefatos disponíveis na sessão.

        Returns:
            Lista de nomes de arquivo (relativa ao session_dir).
        """
        return self.read().get("artifacts_available", [])

    def get_last_error(self) -> Optional[Dict[str, str]]:
        """Retorna o erro do último step se — e somente se — ele falhou.

        Semântica de retry: o contexto de erro só é relevante quando o step
        imediatamente anterior ao próximo falhou. Se o último step foi bem-sucedido,
        não há erro a injetar no próximo prompt.

        Returns:
            Dicionário com ``error_type``, ``error_message`` e
            ``error_location`` se o último step tiver ``status="failed"``,
            ou ``None`` caso contrário (incluindo quando não há steps).
        """
        steps: List[Dict[str, Any]] = self.read().get("steps", [])
        if not steps:
            return None
        last = steps[-1]
        if last.get("status") != "failed":
            return None
        return {
            "error_type": last.get("error_type", ""),
            "error_message": last.get("error_message", ""),
            "error_location": last.get("error_location", ""),
        }

    def get_step_count(self) -> int:
        """Retorna o número total de steps registrados.

        Returns:
            Inteiro >= 0.
        """
        return len(self.read().get("steps", []))

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _empty_manifest(self) -> Dict[str, Any]:
        """Retorna a estrutura inicial do manifest."""
        return {
            "session_id": self._session_id,
            "task_name": self._task_name,
            "created_at": _now_iso(),
            "last_updated": _now_iso(),
            "steps": [],
            "artifacts_available": [],
            "next_step_hint": "",
        }

    def _write(self, data: Dict[str, Any]) -> None:
        """Escrita atômica: tmp file + os.replace().

        Args:
            data: Dicionário a serializar como JSON.
        """
        dir_path = self._session_dir
        # Criar arquivo temporário no mesmo sistema de arquivos
        fd, tmp_path = tempfile.mkstemp(
            suffix=_MANIFEST_TMP_SUFFIX, dir=dir_path
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Rename atômico: substitui manifest.json de forma segura
            os.replace(tmp_path, self._path)
        except Exception:
            # Limpar tmp em caso de falha
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
