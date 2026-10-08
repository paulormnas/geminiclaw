"""Continuidade da pesquisa entre execuções (V18 — mudança ``v18-research-continuity``).

Atingir um limite (ou uma queda de energia) interrompe a **execução**, não a **pesquisa**: o avanço da
sessão é gravado de forma incremental em ``outputs/<sessão>/checkpoint.json`` e a execução seguinte parte
dele (ADR 010, "Continuidade entre execuções"; ADR 012 §5).

Este módulo reúne o modelo do checkpoint, a gravação atômica, a leitura validada e o ``CheckpointRecorder``
que o laço autônomo e o orquestrador usam. Não depende do orquestrador nem do grafo.

Segurança — o que se lê do disco é **dado não confiável** (o arquivo pode estar truncado por uma queda de
energia, corrompido ou adulterado):

- a escrita é atômica (arquivo temporário no mesmo diretório, ``fsync``, ``os.replace``), com permissão
  ``0600``, ``O_EXCL`` e ``O_NOFOLLOW``; o último checkpoint válido é mantido em ``checkpoint.json.bak``;
- a leitura só aceita arquivo comum (nunca link simbólico), do próprio usuário, sem permissão de escrita para
  grupo/outros, com tamanho limitado, JSON estrito (sem ``NaN``/``Infinity``) e schema validado campo a campo;
  nada é desserializado além de JSON (sem ``pickle`` nem ``yaml.load``);
- ``session_id`` e ``project_id`` são validados por expressão fechada e o ``session_id`` do arquivo precisa
  coincidir com o nome do diretório (um checkpoint copiado de outra sessão é recusado);
- o diretório da sessão é resolvido sem link simbólico e confinado ao diretório base de outputs.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src import config
from src.logger import get_logger

logger = get_logger(__name__)

CHECKPOINT_FILENAME = "checkpoint.json"
BACKUP_FILENAME = "checkpoint.json.bak"
CHECKPOINT_VERSION = 1

ESTADO_EM_EXECUCAO = "em_execucao"
ESTADO_FECHADO = "fechado"
ESTADO_INTERROMPIDO = "interrompido"
ESTADOS = (ESTADO_EM_EXECUCAO, ESTADO_FECHADO, ESTADO_INTERROMPIDO)

ST_CONCLUIDA = "concluida"
ST_EM_ANDAMENTO = "em_andamento"
ST_PENDENTE = "pendente"
ST_ABANDONADA = "abandonada"
ST_FALHOU = "falhou"
STATUS_SUBTAREFA = (ST_CONCLUIDA, ST_EM_ANDAMENTO, ST_PENDENTE, ST_ABANDONADA, ST_FALHOU)

CAUSAS_FALHA = ("infraestrutura", "abordagem", "ambigua")
# Categoria estruturada (``AgentResult.error_category``) de uma subtarefa que estava em andamento quando o processo
# parou sem aviso (``classify_failure`` a classifica como causa ``infraestrutura``). O nome é neutro de propósito: a
# única evidência é a falta de batimento (pode ter sido queda de energia, OOM-kill, ``kill -9`` ou erro fatal).
INTERRUPTION_CATEGORY = "interrupcao_inesperada"

# Motivos de parada que permitem retomar sem perguntar; ``solucao_encontrada`` pede confirmação.
MOTIVOS_RETOMAVEIS = frozenset(
    {
        "limite_tokens", "limite_tempo", "limite_retentativas", "limite_conexao", "limite_execucoes", "limite_ciclos",
        "versao_modelo", "interrompida",
    }
)
MOTIVO_RESOLVIDA = "solucao_encontrada"

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
# Artefato: caminho relativo à sessão, componentes de [A-Za-z0-9._-] (sem "..", sem barra inicial, sem controles,
# crases nem quebras de linha): vira texto de prompt das subtarefas dependentes.
_ARTIFACT_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")

MAX_PROMPT_CHARS = 20_000
MAX_SUMMARY_CHARS = 1_000
MAX_DESCRIPTION_CHARS = 500
MAX_ARTIFACTS_PER_SUBTASK = 50
MAX_ARTIFACT_CHARS = 300
MAX_DEPENDS = 50
MAX_HYPOTHESES = 200
MAX_IDS = 500
MAX_SHORT_TEXT = 64

_BUDGET_KEYS = frozenset(
    {
        "max_tokens", "max_minutes", "max_task_retries", "max_connection_retries",
        "closing_reserve_pct", "exploration_token_ceiling",
    }
)
_CONSUMO_KEYS = frozenset({"tokens", "minutos", "retentativas_conexao"})


class CheckpointError(ValueError):
    """Checkpoint ausente, ilegível, inválido ou inseguro (mensagem acionável, sem eco do conteúdo)."""


class ResumeConflictError(RuntimeError):
    """Outra retomada da mesma sessão chegou antes (reivindicação atômica perdida)."""


def safe_artifact_path(value: object) -> bool:
    """``True`` se ``value`` é caminho relativo seguro de artefato (ver ``_ARTIFACT_RE``)."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_ARTIFACT_CHARS
        and bool(_ARTIFACT_RE.fullmatch(value))
        and all(part not in (".", "..") for part in value.split("/"))
    )


class CheckpointVersionError(CheckpointError):
    """O arquivo foi gravado por uma versão mais nova do framework."""


# ---------------------------------------------------------------------------
# Validação de campos
# ---------------------------------------------------------------------------


def validate_session_id(value: object) -> str:
    """Valida o ``session_id`` (nome de pasta seguro).

    Raises:
        CheckpointError: Se não for texto no formato ``[A-Za-z0-9][A-Za-z0-9._-]{0,127}``.
    """
    if not isinstance(value, str) or not SESSION_ID_RE.fullmatch(value) or ".." in value:
        raise CheckpointError("session_id inválido: use letras, dígitos, '.', '_' e '-', sem '..'.")
    return value


def safe_task_name(value: object) -> bool:
    """``True`` se ``value`` serve de nome de subtarefa (vira pasta em ``outputs/<sessão>/``)."""
    return isinstance(value, str) and bool(_NAME_RE.fullmatch(value)) and ".." not in value


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(data: Mapping[str, Any], key: str, limit: int, *, required: bool = False, default: str = "") -> str:
    value = data.get(key, default)
    if value is None and not required:
        return default
    if not isinstance(value, str):
        raise CheckpointError(f"campo '{key}' deve ser texto.")
    if required and not value.strip():
        raise CheckpointError(f"campo '{key}' ausente.")
    if len(value) > limit:
        raise CheckpointError(f"campo '{key}' excede {limit} caracteres.")
    return value


def _opt_id(value: object, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _NODE_ID_RE.fullmatch(value):
        raise CheckpointError(f"campo '{key}' com identificador inválido.")
    return value


def _id_list(value: object, key: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise CheckpointError(f"campo '{key}' deve ser uma lista de até {limit} itens.")
    return [_opt_id(v, key) or "" for v in value if v is not None]


def _numeric_map(value: object, key: str, allowed: frozenset[str]) -> dict[str, float | int]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 32:
        raise CheckpointError(f"campo '{key}' deve ser um objeto pequeno.")
    out: dict[str, float | int] = {}
    for k, v in value.items():
        if k in allowed and _is_number(v):
            out[k] = v
    return out


def _iso_text(value: object, key: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_SHORT_TEXT:
        raise CheckpointError(f"campo '{key}' deve ser um instante ISO-8601.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckpointError(f"campo '{key}' deve ser um instante ISO-8601.") from exc
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------


@dataclass
class SubtaskState:
    """Estado de uma subtarefa no checkpoint.

    Attributes:
        task_name: Nome da subtarefa (pasta em ``outputs/<sessão>/``).
        subtask_id: ID da subtarefa (telemetria e grafo).
        agent_id: Agente executor.
        status: Um de ``STATUS_SUBTAREFA``.
        tentativas: Tentativas já feitas (cumulativas na sessão).
        depends_on: Subtarefas das quais esta depende.
        hypothesis_id: ID da ``Hipotese`` do grafo testada por ela, quando conhecido.
        artefatos: Caminhos relativos a ``outputs/<sessão>/`` produzidos por ela.
        resultado_resumo: Resumo textual do resultado (dado de pesquisa, limitado).
        descricao: Descrição curta do que a subtarefa faz (para o replanejamento).
        causa_falha: ``infraestrutura``/``abordagem``/``ambigua`` quando ``status="falhou"``.
    """

    task_name: str
    subtask_id: str | None = None
    agent_id: str = ""
    status: str = ST_PENDENTE
    tentativas: int = 0
    depends_on: list[str] = field(default_factory=list)
    hypothesis_id: str | None = None
    artefatos: list[str] = field(default_factory=list)
    resultado_resumo: str = ""
    descricao: str = ""
    causa_falha: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa para o JSON do checkpoint."""
        return {
            "task_name": self.task_name,
            "subtask_id": self.subtask_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "tentativas": self.tentativas,
            "depends_on": list(self.depends_on),
            "hypothesis_id": self.hypothesis_id,
            "artefatos": list(self.artefatos),
            "resultado_resumo": self.resultado_resumo,
            "descricao": self.descricao,
            "causa_falha": self.causa_falha,
        }

    @classmethod
    def from_dict(cls, data: object) -> "SubtaskState":
        """Reconstrói com checagem estrita de tipos e tamanhos.

        Raises:
            CheckpointError: Estrutura inválida.
        """
        if not isinstance(data, dict):
            raise CheckpointError("subtarefa inválida.")
        name = data.get("task_name")
        if not safe_task_name(name):
            raise CheckpointError("subtarefa com task_name inválido.")
        status = data.get("status")
        if status not in STATUS_SUBTAREFA:
            raise CheckpointError("subtarefa com status inválido.")
        tentativas = data.get("tentativas", 0)
        if not isinstance(tentativas, int) or isinstance(tentativas, bool) or not 0 <= tentativas <= 10_000:
            raise CheckpointError("subtarefa com tentativas inválidas.")
        depends = data.get("depends_on", [])
        if not isinstance(depends, list) or len(depends) > MAX_DEPENDS or not all(safe_task_name(d) for d in depends):
            raise CheckpointError("subtarefa com depends_on inválido.")
        artefatos = data.get("artefatos", [])
        if (
            not isinstance(artefatos, list)
            or len(artefatos) > MAX_ARTIFACTS_PER_SUBTASK
            or not all(safe_artifact_path(a) for a in artefatos)
        ):
            raise CheckpointError("subtarefa com artefatos inválidos.")
        causa = data.get("causa_falha")
        if causa is not None and causa not in CAUSAS_FALHA:
            raise CheckpointError("subtarefa com causa_falha inválida.")
        return cls(
            task_name=str(name),
            subtask_id=_opt_id(data.get("subtask_id"), "subtask_id"),
            agent_id=_text(data, "agent_id", MAX_SHORT_TEXT),
            status=str(status),
            tentativas=tentativas,
            depends_on=list(depends),
            hypothesis_id=_opt_id(data.get("hypothesis_id"), "hypothesis_id"),
            artefatos=list(artefatos),
            resultado_resumo=_text(data, "resultado_resumo", MAX_SUMMARY_CHARS),
            descricao=_text(data, "descricao", MAX_DESCRIPTION_CHARS),
            causa_falha=causa,
        )


@dataclass
class Checkpoint:
    """Registro incremental do avanço de uma sessão (ver o design de ``v18-research-continuity`` §1)."""

    session_id: str
    project_id: str | None = None
    continues_session_id: str | None = None
    atualizado_em: str = field(default_factory=_now)
    estado: str = ESTADO_EM_EXECUCAO
    motivo_parada: str | None = None
    prompt_original: str = ""
    modo: str = ""
    orcamento: dict[str, float | int] = field(default_factory=dict)
    consumo: dict[str, float | int] = field(default_factory=dict)
    plano_versao: int = 0
    subtarefas: list[SubtaskState] = field(default_factory=list)
    hipoteses: list[dict[str, Any]] = field(default_factory=list)
    decisoes: list[str] = field(default_factory=list)
    descobertas_sessao: list[str] = field(default_factory=list)
    sinalizacoes_pendentes: int = 0
    curator_pendente: bool = False
    detalhe_parada: str = ""

    def find(self, task_name: str) -> SubtaskState | None:
        """Subtarefa pelo nome, ou ``None``."""
        return next((s for s in self.subtarefas if s.task_name == task_name), None)

    def concluidas(self) -> dict[str, SubtaskState]:
        """Subtarefas concluídas, por nome."""
        return {s.task_name: s for s in self.subtarefas if s.status == ST_CONCLUIDA}

    def to_dict(self) -> dict[str, Any]:
        """Serializa para o formato do design (``versao_checkpoint`` 1)."""
        return {
            "versao_checkpoint": CHECKPOINT_VERSION,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "continues_session_id": self.continues_session_id,
            "atualizado_em": self.atualizado_em,
            "estado": self.estado,
            "motivo_parada": self.motivo_parada,
            "prompt_original": self.prompt_original,
            "modo": self.modo,
            "orcamento": dict(self.orcamento),
            "consumo": dict(self.consumo),
            "plano": {"versao": self.plano_versao, "subtarefas": [s.to_dict() for s in self.subtarefas]},
            "hipoteses": [dict(h) for h in self.hipoteses],
            "decisoes": list(self.decisoes),
            "descobertas_sessao": list(self.descobertas_sessao),
            "sinalizacoes_pendentes": self.sinalizacoes_pendentes,
            "curator_pendente": self.curator_pendente,
            "detalhe_parada": self.detalhe_parada,
        }

    @classmethod
    def from_dict(cls, data: object, *, expected_session_id: str) -> "Checkpoint":
        """Reconstrói e valida um checkpoint lido do disco (dado não confiável).

        Args:
            data: JSON já decodificado.
            expected_session_id: Nome do diretório da sessão (o ``session_id`` do arquivo precisa coincidir).

        Raises:
            CheckpointVersionError: ``versao_checkpoint`` mais nova que a suportada.
            CheckpointError: Qualquer outra violação do schema.
        """
        if not isinstance(data, dict):
            raise CheckpointError("o checkpoint deve ser um objeto JSON.")
        if "versao_checkpoint" not in data and ("completed_tasks" in data or "pending_tasks" in data):
            raise CheckpointError(
                "checkpoint em formato legado (anterior à continuidade V18, sem versao_checkpoint); não é retomável. "
                "Inicie uma nova sessão a partir do prompt original."
            )
        version = data.get("versao_checkpoint")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise CheckpointError("versao_checkpoint ausente ou inválida.")
        if version > CHECKPOINT_VERSION:
            raise CheckpointVersionError(
                f"checkpoint na versão {version}, mais nova que a suportada ({CHECKPOINT_VERSION}); "
                "atualize o framework."
            )
        session_id = validate_session_id(data.get("session_id"))
        if session_id != expected_session_id:
            raise CheckpointError("o session_id do checkpoint não corresponde ao diretório da sessão.")
        project_id = data.get("project_id")
        if project_id is not None:
            from src.knowledge.errors import GraphStoreError
            from src.knowledge.projects import validate_project_id

            try:
                project_id = validate_project_id(project_id)
            except GraphStoreError as exc:
                raise CheckpointError("project_id inválido no checkpoint.") from exc
        continues = data.get("continues_session_id")
        if continues is not None:
            continues = validate_session_id(continues)
        estado = data.get("estado")
        if estado not in ESTADOS:
            raise CheckpointError("estado inválido.")
        motivo = data.get("motivo_parada")
        if motivo is not None:
            from src.knowledge.ingestion import MOTIVOS_PARADA

            if motivo not in MOTIVOS_PARADA:
                raise CheckpointError("motivo_parada inválido.")
        plano = data.get("plano")
        if not isinstance(plano, dict):
            raise CheckpointError("plano ausente.")
        plano_versao = plano.get("versao", 0)
        if not isinstance(plano_versao, int) or isinstance(plano_versao, bool) or not 0 <= plano_versao <= 1_000_000:
            raise CheckpointError("plano.versao inválida.")
        raw_tasks = plano.get("subtarefas", [])
        if not isinstance(raw_tasks, list) or len(raw_tasks) > config.CHECKPOINT_MAX_SUBTASKS:
            raise CheckpointError(f"plano.subtarefas deve ser uma lista de até {config.CHECKPOINT_MAX_SUBTASKS} itens.")
        tasks = [SubtaskState.from_dict(t) for t in raw_tasks]
        if len({t.task_name for t in tasks}) != len(tasks):
            raise CheckpointError("plano.subtarefas com nomes repetidos.")
        pendentes = data.get("sinalizacoes_pendentes", 0)
        if not isinstance(pendentes, int) or isinstance(pendentes, bool) or not 0 <= pendentes <= 1_000_000:
            raise CheckpointError("sinalizacoes_pendentes inválido.")
        curator = data.get("curator_pendente", False)
        if not isinstance(curator, bool):
            raise CheckpointError("curator_pendente deve ser booleano.")
        return cls(
            session_id=session_id,
            project_id=project_id,
            continues_session_id=continues,
            atualizado_em=_iso_text(data.get("atualizado_em"), "atualizado_em"),
            estado=str(estado),
            motivo_parada=motivo,
            prompt_original=_text(data, "prompt_original", MAX_PROMPT_CHARS),
            modo=_text(data, "modo", MAX_SHORT_TEXT),
            orcamento=_numeric_map(data.get("orcamento"), "orcamento", _BUDGET_KEYS),
            consumo=_numeric_map(data.get("consumo"), "consumo", _CONSUMO_KEYS),
            plano_versao=plano_versao,
            subtarefas=tasks,
            hipoteses=_hypotheses(data.get("hipoteses")),
            decisoes=_id_list(data.get("decisoes"), "decisoes", MAX_IDS),
            descobertas_sessao=_id_list(data.get("descobertas_sessao"), "descobertas_sessao", MAX_IDS),
            sinalizacoes_pendentes=pendentes,
            curator_pendente=curator,
            detalhe_parada=_text(data, "detalhe_parada", 200),
        )


def _hypotheses(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_HYPOTHESES:
        raise CheckpointError(f"hipoteses deve ser uma lista de até {MAX_HYPOTHESES} itens.")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise CheckpointError("hipótese inválida.")
        hid = _opt_id(item.get("id"), "hipoteses.id")
        status = item.get("status")
        if hid is None or not isinstance(status, str) or len(status) > MAX_SHORT_TEXT:
            raise CheckpointError("hipótese inválida.")
        entry: dict[str, Any] = {"id": hid, "status": status}
        veredito = item.get("veredito")
        if veredito is not None:
            if not _is_number(veredito):
                raise CheckpointError("veredito da hipótese inválido.")
            entry["veredito"] = veredito
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Diretório da sessão, leitura e escrita atômica
# ---------------------------------------------------------------------------


def resolve_session_dir(base_dir: Path | str, session_id: str) -> Path:
    """Diretório ``<base>/<session_id>`` resolvido, sem link simbólico e confinado a ``base_dir``.

    Raises:
        CheckpointError: ``session_id`` inválido, diretório inexistente, link simbólico ou fora de ``base_dir``.
    """
    sid = validate_session_id(session_id)
    base = Path(base_dir).resolve()
    candidate = base / sid
    if candidate.is_symlink():
        raise CheckpointError("o diretório da sessão é um link simbólico; recusado.")
    if not candidate.is_dir():
        raise CheckpointError(f"diretório da sessão '{sid}' não encontrado em {base}.")
    resolved = candidate.resolve()
    if resolved.parent != base:
        raise CheckpointError("o diretório da sessão está fora do diretório de outputs; recusado.")
    return resolved


def _reject_constant(name: str) -> Any:
    raise CheckpointError(f"constante JSON não permitida: {name}.")


def _read_bytes_safely(path: Path, limit: int) -> bytes:
    """Lê um arquivo comum do próprio usuário, sem seguir link simbólico, com tamanho limitado."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise CheckpointError(f"arquivo '{path.name}' ilegível ou é um link simbólico ({type(exc).__name__}).") from exc
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise CheckpointError(f"'{path.name}' não é um arquivo comum.")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise CheckpointError(f"'{path.name}' pertence a outro usuário; recusado.")
        if info.st_mode & 0o022:
            raise CheckpointError(f"'{path.name}' tem permissão de escrita para grupo/outros; recusado.")
        if info.st_size > limit:
            raise CheckpointError(f"'{path.name}' excede o limite de {limit} bytes.")
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise CheckpointError(f"'{path.name}' excede o limite de {limit} bytes.")
    return data


def _load_file(path: Path, expected_session_id: str) -> Checkpoint:
    raw = _read_bytes_safely(path, int(config.CHECKPOINT_MAX_BYTES))
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except CheckpointError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise CheckpointError(f"'{path.name}' não é um JSON válido ({type(exc).__name__}).") from exc
    return Checkpoint.from_dict(data, expected_session_id=expected_session_id)


def read_checkpoint(session_dir: Path | str, *, expected_session_id: str | None = None) -> tuple[Checkpoint, str]:
    """Lê o checkpoint da sessão; se o principal estiver inválido, usa o ``.bak`` (último válido).

    Args:
        session_dir: ``outputs/<sessão>/`` (use ``resolve_session_dir`` para obtê-lo de um ``session_id``).
        expected_session_id: Padrão: o nome do diretório.

    Returns:
        ``(checkpoint, origem)`` com ``origem`` ``"principal"`` ou ``"backup"``.

    Raises:
        CheckpointVersionError: Versão mais nova que a suportada (não cai para o backup).
        CheckpointError: Nenhum dos dois arquivos é válido.
    """
    directory = Path(session_dir)
    expected = validate_session_id(expected_session_id or directory.name)
    problems: list[str] = []
    for name, origin in ((CHECKPOINT_FILENAME, "principal"), (BACKUP_FILENAME, "backup")):
        try:
            return _load_file(directory / name, expected), origin
        except FileNotFoundError:
            problems.append(f"{name}: ausente")
        except CheckpointVersionError:
            raise
        except CheckpointError as exc:
            problems.append(f"{name}: {exc}")
            logger.warning("Checkpoint inválido", extra={"extra": {"arquivo": name, "motivo": str(exc)[:200]}})
    raise CheckpointError("nenhum checkpoint válido na sessão (" + "; ".join(problems) + ").")


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_private(path: Path, data: bytes) -> None:
    """Cria ``path`` (novo, ``0600``, sem seguir link) com ``data`` e força a gravação em disco."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _rotate_backup(target: Path, backup: Path, expected_session_id: str) -> None:
    """Preserva o checkpoint atual **se for válido** como ``.bak`` (atômico); nunca troca um bom por um corrompido."""
    try:
        _load_file(target, expected_session_id)
        data = _read_bytes_safely(target, int(config.CHECKPOINT_MAX_BYTES))
    except (FileNotFoundError, CheckpointError):
        return
    tmp = backup.with_name(f".{backup.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        _write_private(tmp, data)
        os.replace(tmp, backup)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def write_checkpoint(session_dir: Path | str, checkpoint: Checkpoint) -> None:
    """Grava o checkpoint de forma atômica, mantendo o anterior válido em ``checkpoint.json.bak``.

    Sequência: arquivo temporário no mesmo diretório -> ``fsync`` -> cópia do atual válido para o ``.bak`` ->
    ``os.replace`` -> ``fsync`` do diretório. Uma queda em qualquer ponto deixa o arquivo principal ou o ``.bak``
    íntegro; o temporário órfão é removido na próxima gravação.

    Raises:
        CheckpointError: Diretório inseguro ou checkpoint maior que ``CHECKPOINT_MAX_BYTES``.
        OSError: Falha de E/S.
    """
    directory = Path(session_dir)
    if directory.is_symlink():
        raise CheckpointError("o diretório da sessão é um link simbólico; recusado.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(payload) > int(config.CHECKPOINT_MAX_BYTES):
        raise CheckpointError(f"checkpoint excede o limite de {config.CHECKPOINT_MAX_BYTES} bytes.")
    target = directory / CHECKPOINT_FILENAME
    for stale in directory.glob(f".{CHECKPOINT_FILENAME}.*.tmp"):  # sobras de uma queda no meio da gravação
        try:
            if stale.is_file() and not stale.is_symlink():
                stale.unlink()
        except OSError:
            pass
    tmp = directory / f".{CHECKPOINT_FILENAME}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        _write_private(tmp, payload)
        _rotate_backup(target, directory / BACKUP_FILENAME, checkpoint.session_id)
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(directory)


# ---------------------------------------------------------------------------
# Plano -> estado das subtarefas
# ---------------------------------------------------------------------------


def plan_entry(task: Any) -> dict[str, Any]:
    """Resumo de uma tarefa do plano (``AgentTask``) para o checkpoint (sem importar o orquestrador)."""
    prompt = str(getattr(task, "prompt", "") or "")
    return {
        "task_name": getattr(task, "task_name", "") or "",
        "subtask_id": getattr(task, "subtask_id", None),
        "agent_id": str(getattr(task, "agent_id", "") or "")[:MAX_SHORT_TEXT],
        "depends_on": [d for d in (getattr(task, "depends_on", None) or []) if safe_task_name(d)][:MAX_DEPENDS],
        "descricao": " ".join(prompt.split())[:MAX_DESCRIPTION_CHARS],
    }


def list_task_artifacts(session_dir: Path, task_name: str, *, limit: int = MAX_ARTIFACTS_PER_SUBTASK) -> list[str]:
    """Arquivos comuns da pasta da subtarefa (relativos à sessão), até ``limit``; sem seguir links simbólicos."""
    if not safe_task_name(task_name):
        return []
    root = Path(session_dir) / task_name
    found: list[str] = []
    try:
        if root.is_symlink() or not root.is_dir():
            return []
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not Path(current, d).is_symlink())[:20]
            depth = len(Path(current).relative_to(root).parts)
            if depth >= 3:
                dirs[:] = []
            for name in sorted(files):
                path = Path(current) / name
                if path.is_symlink() or not path.is_file():
                    continue
                rel = path.relative_to(session_dir).as_posix()
                if safe_artifact_path(rel):
                    found.append(rel)
                if len(found) >= limit:
                    return found
    except OSError:
        return found
    return found


# ---------------------------------------------------------------------------
# Gravador incremental
# ---------------------------------------------------------------------------


class CheckpointRecorder:
    """Mantém o checkpoint da sessão em memória e o grava a cada mudança relevante.

    Todo método público é seguro: falha de E/S vira aviso (``failures`` conta as ocorrências), nunca derruba a
    pesquisa. É seguro entre threads (o Curator e a ingestão rodam fora do laço de eventos).
    """

    def __init__(self, session_dir: Path | str, checkpoint: Checkpoint) -> None:
        self.session_dir = Path(session_dir)
        self._cp = checkpoint
        self._lock = threading.RLock()
        self.failures = 0

    @classmethod
    def start(
        cls,
        session_dir: Path | str,
        *,
        session_id: str,
        project_id: str | None,
        continues_session_id: str | None,
        prompt: str,
        modo: str,
        orcamento: Mapping[str, Any] | None = None,
    ) -> "CheckpointRecorder":
        """Cria o gravador de uma sessão nova e grava o checkpoint inicial."""
        cp = Checkpoint(
            session_id=validate_session_id(session_id),
            project_id=project_id,
            continues_session_id=continues_session_id,
            prompt_original=prompt[:MAX_PROMPT_CHARS],
            modo=str(modo)[:MAX_SHORT_TEXT],
            orcamento=_numeric_map(dict(orcamento or {}), "orcamento", _BUDGET_KEYS),
        )
        recorder = cls(session_dir, cp)
        recorder._flush()
        return recorder

    # -- leitura ------------------------------------------------------------

    def snapshot(self) -> Checkpoint:
        """Cópia do estado atual."""
        with self._lock:
            return replace(
                self._cp,
                subtarefas=[
                    replace(s, depends_on=list(s.depends_on), artefatos=list(s.artefatos))
                    for s in self._cp.subtarefas
                ],
                hipoteses=[dict(h) for h in self._cp.hipoteses],
                decisoes=list(self._cp.decisoes),
                descobertas_sessao=list(self._cp.descobertas_sessao),
                orcamento=dict(self._cp.orcamento),
                consumo=dict(self._cp.consumo),
            )

    # -- gravação -----------------------------------------------------------

    def _flush(self) -> bool:
        with self._lock:
            self._cp.atualizado_em = _now()
            try:
                write_checkpoint(self.session_dir, self._cp)
                return True
            except (OSError, CheckpointError, ValueError) as exc:
                self.failures += 1
                logger.warning(
                    "Checkpoint da sessão não gravado; a pesquisa continua sem esta atualização",
                    extra={"extra": {"erro": type(exc).__name__, "detalhe": str(exc)[:200]}},
                )
                return False

    def _update(self, mutate: Any) -> bool:
        with self._lock:
            try:
                mutate(self._cp)
            except Exception as exc:  # noqa: BLE001 - dado de entrada inesperado nunca derruba a subtarefa
                self.failures += 1
                logger.warning("Checkpoint: atualização ignorada", extra={"extra": {"erro": type(exc).__name__}})
                return False
            return self._flush()

    def seed(self, states: Iterable[SubtaskState]) -> bool:
        """Herda subtarefas concluídas de uma sessão anterior (retomada), como histórico do plano."""
        copies = [
            replace(s, depends_on=list(s.depends_on), artefatos=list(s.artefatos))
            for s in states
            if s.status == ST_CONCLUIDA
        ][: config.CHECKPOINT_MAX_SUBTASKS]

        def mutate(cp: Checkpoint) -> None:
            cp.subtarefas = copies

        return self._update(mutate)

    # -- momentos de gravação (design §1) -------------------------------------

    def set_plan(self, entries: Iterable[Mapping[str, Any]]) -> bool:
        """Criação ou alteração do plano. Subtarefas concluídas/abandonadas são preservadas como estão."""
        items = [dict(e) for e in entries]

        def mutate(cp: Checkpoint) -> None:
            old = {s.task_name: s for s in cp.subtarefas}
            new_states: list[SubtaskState] = []
            seen: set[str] = set()
            for entry in items:
                name = entry.get("task_name")
                if not safe_task_name(name) or name in seen:
                    continue
                seen.add(str(name))
                previous = old.get(str(name))
                if previous is not None and previous.status in (ST_CONCLUIDA, ST_ABANDONADA):
                    new_states.append(previous)
                    continue
                state = previous or SubtaskState(task_name=str(name))
                state.subtask_id = entry.get("subtask_id") or state.subtask_id
                state.agent_id = str(entry.get("agent_id") or state.agent_id)[:MAX_SHORT_TEXT]
                state.depends_on = list(entry.get("depends_on") or [])
                state.descricao = str(entry.get("descricao") or state.descricao)[:MAX_DESCRIPTION_CHARS]
                if state.status != ST_EM_ANDAMENTO:
                    state.status = ST_PENDENTE
                new_states.append(state)
            for name, state in old.items():  # histórico: concluídas/abandonadas que o novo plano não repetiu
                if name not in seen and state.status in (ST_CONCLUIDA, ST_ABANDONADA):
                    new_states.append(state)
            new_states = new_states[: config.CHECKPOINT_MAX_SUBTASKS]
            changed = [(s.task_name, tuple(s.depends_on)) for s in new_states] != [
                (s.task_name, tuple(s.depends_on)) for s in cp.subtarefas
            ]
            cp.subtarefas = new_states
            if changed or cp.plano_versao == 0:
                cp.plano_versao += 1

        return self._update(mutate)

    def subtask_started(self, task_name: str, tentativas: int) -> bool:
        """Início de uma tentativa da subtarefa."""

        def mutate(cp: Checkpoint) -> None:
            state = cp.find(task_name)
            if state is None:
                return
            state.status = ST_EM_ANDAMENTO
            state.tentativas = max(int(tentativas), state.tentativas)

        return self._update(mutate)

    def subtask_finished(
        self,
        task_name: str,
        *,
        status: str,
        tentativas: int,
        resumo: str = "",
        artefatos: Iterable[str] | None = None,
        causa_falha: str | None = None,
    ) -> bool:
        """Fim da subtarefa (``concluida``, ``falhou`` ou ``abandonada``) com tentativas, artefatos e resumo."""
        if status not in (ST_CONCLUIDA, ST_FALHOU, ST_ABANDONADA, ST_PENDENTE):
            raise ValueError(f"status de fim inválido: {status!r}")

        def mutate(cp: Checkpoint) -> None:
            state = cp.find(task_name)
            if state is None:
                return
            state.status = status
            state.tentativas = max(int(tentativas), state.tentativas)
            state.resultado_resumo = " ".join(str(resumo or "").split())[:MAX_SUMMARY_CHARS]
            if artefatos is not None:
                state.artefatos = [a for a in artefatos if safe_artifact_path(a)][:MAX_ARTIFACTS_PER_SUBTASK]
            state.causa_falha = causa_falha if causa_falha in CAUSAS_FALHA else None

        return self._update(mutate)

    def set_graph_state(
        self,
        *,
        hipoteses: Iterable[Mapping[str, Any]] | None = None,
        decisoes: Iterable[str] | None = None,
        descobertas: Iterable[str] | None = None,
        sinalizacoes_pendentes: int | None = None,
        hipotese_por_subtarefa: Mapping[str, str] | None = None,
    ) -> bool:
        """Checkpoint do Curator: hipóteses (com vereditos), decisões, descobertas e sinalizações pendentes."""

        def mutate(cp: Checkpoint) -> None:
            if hipoteses is not None:
                cp.hipoteses = _hypotheses(list(hipoteses))
            if decisoes is not None:
                cp.decisoes = _id_list(list(decisoes), "decisoes", MAX_IDS)
            if descobertas is not None:
                cp.descobertas_sessao = _id_list(list(descobertas), "descobertas_sessao", MAX_IDS)
            if sinalizacoes_pendentes is not None:
                cp.sinalizacoes_pendentes = max(int(sinalizacoes_pendentes), 0)
            if hipotese_por_subtarefa:
                for state in cp.subtarefas:
                    hid = hipotese_por_subtarefa.get(state.subtask_id or "")
                    if hid and _NODE_ID_RE.fullmatch(hid):
                        state.hypothesis_id = hid

        return self._update(mutate)

    def set_usage(self, consumo: Mapping[str, Any] | None = None, orcamento: Mapping[str, Any] | None = None) -> bool:
        """Atualiza consumo e orçamento (só números; nada de dado de pesquisa)."""

        def mutate(cp: Checkpoint) -> None:
            if consumo is not None:
                cp.consumo = _numeric_map(dict(consumo), "consumo", _CONSUMO_KEYS)
            if orcamento is not None:
                cp.orcamento = _numeric_map(dict(orcamento), "orcamento", _BUDGET_KEYS)

        return self._update(mutate)

    def set_curator_pending(self, pending: bool) -> bool:
        """Marca (ou limpa) a consolidação do Curator pendente para a próxima execução."""

        def mutate(cp: Checkpoint) -> None:
            cp.curator_pendente = bool(pending)

        return self._update(mutate)

    def close(self, estado: str, motivo_parada: str | None, *, curator_pendente: bool | None = None) -> bool:
        """Fechamento (``fechado``) ou parada (``interrompido``) da sessão."""
        if estado not in (ESTADO_FECHADO, ESTADO_INTERROMPIDO):
            raise ValueError(f"estado de fechamento inválido: {estado!r}")

        def mutate(cp: Checkpoint) -> None:
            cp.estado = estado
            cp.motivo_parada = motivo_parada
            if curator_pendente is not None:
                cp.curator_pendente = bool(curator_pendente)
            for state in cp.subtarefas:
                if state.status == ST_EM_ANDAMENTO:  # nada fica "em andamento" depois de a sessão parar
                    state.status = ST_PENDENTE

        return self._update(mutate)


# ---------------------------------------------------------------------------
# Paradas inesperadas
# ---------------------------------------------------------------------------


def mark_checkpoint_interrupted(
    session_dir: Path | str, *, expected_session_id: str | None = None, detail: str = ""
) -> Checkpoint | None:
    """Marca o checkpoint de uma sessão parada sem fechamento: ``interrompido`` e subtarefas em andamento viram
    ``falhou`` com causa ``infraestrutura``.

    Idempotente: um checkpoint já ``interrompido``/``fechado`` e sem subtarefas em andamento não é reescrito.

    Returns:
        O checkpoint atualizado, ou ``None`` se a sessão não tem checkpoint válido.
    """
    directory = Path(session_dir)
    try:
        cp, _origin = read_checkpoint(directory, expected_session_id=expected_session_id)
    except CheckpointError as exc:
        logger.warning("Sessão interrompida sem checkpoint válido", extra={"extra": {"motivo": str(exc)[:200]}})
        return None
    changed = False
    for state in cp.subtarefas:
        if state.status == ST_EM_ANDAMENTO:
            state.status = ST_FALHOU
            state.causa_falha = "infraestrutura"
            changed = True
    if cp.estado == ESTADO_EM_EXECUCAO:
        cp.estado = ESTADO_INTERROMPIDO
        cp.motivo_parada = cp.motivo_parada or "interrompida"
        cp.curator_pendente = True  # a consolidação do Curator desta sessão não se perde
        cp.detalhe_parada = " ".join(detail.split())[:200] if detail else cp.detalhe_parada
        changed = True
    if changed:
        cp.atualizado_em = _now()
        write_checkpoint(directory, cp)
    return cp


# ---------------------------------------------------------------------------
# Retomabilidade
# ---------------------------------------------------------------------------

RESUME_OK = "ok"
RESUME_CONFIRM = "confirmar"
RESUME_REFUSE = "recusar"


@dataclass(frozen=True)
class Resumability:
    """Decisão sobre retomar uma sessão: ``ok``, ``confirmar`` (pedir ao pesquisador) ou ``recusar``."""

    decision: str
    message: str = ""


def evaluate_resumability(
    session_status: str,
    checkpoint: Checkpoint,
    db_motivo: str | None = None,
    *,
    seconds_since_beat: float | None = None,
) -> Resumability:
    """Decide se a sessão pode ser retomada (design §3).

    Retomáveis: ``suspended``, ``interrompida`` ou fechada por ``limite_*``. ``solucao_encontrada`` pede
    confirmação. Sessão ainda ativa, ``erro`` e fechamento sem motivo são recusados. O motivo do **banco** de
    sessões vale mais que o do arquivo; divergência entre os dois é recusada (arquivo adulterado).
    """
    if session_status == "active":
        wait = ""
        if seconds_since_beat is not None:
            left = max(float(config.SESSION_STALE_SECONDS) - seconds_since_beat, 0.0)
            wait = (
                f" (último batimento há {seconds_since_beat:.0f}s; se o processo caiu, a sessão vira obsoleta em "
                f"~{left:.0f}s; veja `geminiclaw sessions`)"
            )
        return Resumability(RESUME_REFUSE, "a sessão ainda está em execução" + wait + ".")
    motivo = checkpoint.motivo_parada
    if db_motivo is not None:
        if motivo is not None and motivo != db_motivo:
            return Resumability(RESUME_REFUSE, "o motivo de parada do checkpoint diverge do registrado no banco.")
        motivo = db_motivo
    if session_status in ("suspended", "interrompida"):
        return Resumability(RESUME_OK)
    if motivo in MOTIVOS_RETOMAVEIS:
        return Resumability(RESUME_OK)
    if motivo == MOTIVO_RESOLVIDA:
        return Resumability(
            RESUME_CONFIRM, "a pesquisa foi dada como resolvida (solucao_encontrada); continuar explorando?"
        )
    if motivo == "planos_rejeitados":
        return Resumability(
            RESUME_CONFIRM,
            "a exploração parou por planos consecutivos rejeitados (planos_rejeitados); retomar repete o mesmo "
            "planejamento — continuar mesmo assim?",
        )
    if motivo == "erro":
        return Resumability(
            RESUME_REFUSE,
            "a sessão terminou em erro (motivo_parada=erro); investigue a causa e inicie uma nova sessão.",
        )
    return Resumability(RESUME_REFUSE, "a sessão não tem um motivo de parada retomável registrado.")


@dataclass(frozen=True)
class ResumeState:
    """Estado de retomada entregue ao orquestrador (já validado).

    Attributes:
        source_session_id: Sessão continuada.
        project_id: Projeto (``None`` em sessão sem grafo).
        checkpoint: Checkpoint validado da sessão de origem.
        readable_dirs: Diretórios de outputs (somente leitura) da cadeia: origem e ancestrais do mesmo projeto.
        context_block: Contexto de retomada do Researcher (dado delimitado, não instrução).
        curator_pending: O Curator deve fechar a sessão anterior antes do novo planejamento.
        graph_available: ``False`` quando o grafo estava fora do ar ao montar o contexto.
    """

    source_session_id: str
    project_id: str | None
    checkpoint: Checkpoint
    readable_dirs: tuple[Path, ...] = ()
    context_block: str = ""
    curator_pending: bool = False
    graph_available: bool = True
    stale_claim: str | None = None

    @property
    def completed(self) -> dict[str, SubtaskState]:
        """Subtarefas concluídas da sessão de origem (nunca reexecutadas)."""
        return self.checkpoint.concluidas()


def is_within(path: Path, roots: Iterable[Path]) -> bool:
    """``True`` se ``path`` (resolvido) está dentro de algum de ``roots`` (resolvidos)."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return True
        except OSError:
            continue
    return False


def clear_curator_pending(session_dir: Path | str) -> bool:
    """Limpa ``curator_pendente`` no checkpoint de uma sessão (o Curator concluiu o fechamento na retomada)."""
    directory = Path(session_dir)
    try:
        cp, _origin = read_checkpoint(directory)
    except CheckpointError:
        return False
    if not cp.curator_pendente:
        return True
    cp.curator_pendente = False
    cp.atualizado_em = _now()
    write_checkpoint(directory, cp)
    return True
