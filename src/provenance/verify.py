"""Verificação da cadeia de execuções (design §7): ``geminiclaw provenance verify``.

Passos: cadeia (sequência, ``prev_hash`` e hash recalculado), pares ``inicio``/``termino``, arquivos em disco, órfãs,
pendências e pontas gravadas nos checkpoints. Códigos de saída: 0 (íntegra), 1 (inconsistência), 2 (verificação
impossível; tratado pelo chamador a partir de :class:`ProvenanceUnavailable`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.provenance.canonical import ZERO_HASH
from src.provenance.errors import ProvenanceError
from src.provenance.hashing import HashCache, hash_file
from src.provenance.ledger import PENDING_FILE, corpo_sha256
from src.provenance.store import TIPO_INICIO, TIPO_TERMINO, LedgerStore, StoredRecord

EXIT_OK = 0
EXIT_INCONSISTENT = 1
EXIT_IMPOSSIBLE = 2

FILE_OK = "ok"
FILE_ALTERADO = "alterado"
FILE_AUSENTE = "ausente"
FILE_SUBSTITUIDO = "substituido"  # reescrito por execução posterior (o último escritor é quem vale)
ORFA_PENDENTE_LOCAL = "pendente_local"
ORFA_SEM_TERMINO = "sem_termino"

LIMITS = (
    "A cadeia é evidência de adulteração, não prevenção: quem controla o banco e o disco pode reescrevê-la por "
    "inteiro; "
    "só uma ponta guardada fora do nó revela isso. O registro prova que código, entradas e saídas correspondem ao que "
    "está em disco, não que a métrica foi calculada corretamente. Arquivos ausentes não distinguem limpeza legítima de "
    "remoção. Sem --full a verificação confia no cache de hash."
)


@dataclass
class VerifyReport:
    """Resultado da verificação de um projeto (ou de uma exportação)."""

    project_id: str
    registros: int = 0
    ponta: dict[str, Any] | None = None
    ancora_prev_hash: str | None = None
    problemas_cadeia: list[dict[str, Any]] = field(default_factory=list)
    problemas_pares: list[dict[str, Any]] = field(default_factory=list)
    arquivos: list[dict[str, Any]] = field(default_factory=list)
    orfas: list[dict[str, Any]] = field(default_factory=list)
    pendencias: list[str] = field(default_factory=list)
    conflitos_pendencia: list[str] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    do_export: bool = False

    @property
    def arquivos_alterados(self) -> list[dict[str, Any]]:
        return [a for a in self.arquivos if a["estado"] == FILE_ALTERADO]

    @property
    def checkpoints_divergentes(self) -> list[dict[str, Any]]:
        return [c for c in self.checkpoints if c["estado"] == "divergente"]

    @property
    def integra(self) -> bool:
        return not (
            self.problemas_cadeia or self.problemas_pares or self.arquivos_alterados or self.checkpoints_divergentes
            or self.conflitos_pendencia
        )

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.integra else EXIT_INCONSISTENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "integra": self.integra,
            "registros": self.registros,
            "ponta": self.ponta,
            "ancora_prev_hash": self.ancora_prev_hash,
            "problemas_cadeia": self.problemas_cadeia,
            "problemas_pares": self.problemas_pares,
            "arquivos": self.arquivos,
            "orfas": self.orfas,
            "pendencias": self.pendencias,
            "conflitos_pendencia": self.conflitos_pendencia,
            "checkpoints": self.checkpoints,
            "limites": LIMITS,
        }

    def render(self) -> str:
        lines = [f"Cadeia de proveniência: {self.project_id}"]
        tip = f"seq {self.ponta['seq']}, {self.ponta['record_hash'][:16]}…" if self.ponta else "vazia"
        lines.append(f"Registros: {self.registros} | ponta: {tip}")
        if self.do_export:
            lines.append(f"Âncora (prev_hash do primeiro registro do segmento): {self.ancora_prev_hash}")
        lines.append("Resultado: " + ("ÍNTEGRA" if self.integra else "INCONSISTENTE"))
        for problem in self.problemas_cadeia:
            lines.append(f"  [cadeia] seq {problem.get('seq')}: {problem['problema']}")
        for problem in self.problemas_pares:
            lines.append(f"  [par] {problem.get('exec_id')}: {problem['problema']}")
        for item in self.arquivos:
            if item["estado"] in (FILE_ALTERADO, FILE_AUSENTE):
                lines.append(f"  [arquivo {item['estado']}] {item['caminho']} ({item['papel']}, {item['exec_id']})")
        for orphan in self.orfas:
            lines.append(f"  [órfã {orphan['classe']}] {orphan['exec_id']} ({orphan['task_name']})")
        for exec_id in self.conflitos_pendencia:
            lines.append(f"  [pendência em conflito] {exec_id}")
        for check in self.checkpoints:
            if check["estado"] == "divergente":
                lines.append(f"  [checkpoint divergente] sessão {check['session_id']}: {check['detalhe']}")
        lines.append("Limites: " + LIMITS)
        return "\n".join(lines)


def verify_chain(records: list[StoredRecord], *, genesis: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(problemas_cadeia, problemas_pares)`` de uma lista de registros ordenada por ``seq`` de UM projeto.

    Args:
        records: Registros do projeto (completos, ou um segmento contíguo exportado).
        genesis: ``True`` exige começar em ``seq=1`` com ``prev_hash`` de zeros; ``False`` aceita o segmento e usa o
            ``prev_hash`` do primeiro registro como âncora.
    """
    chain: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    previous: StoredRecord | None = None
    for rec in records:
        if previous is None:
            if genesis:
                if rec.seq != 1:
                    chain.append({"seq": rec.seq, "problema": "a cadeia não começa em seq=1 (lacuna no início)"})
                if rec.prev_hash != ZERO_HASH:
                    chain.append({"seq": rec.seq, "problema": "o primeiro prev_hash não é zero"})
        else:
            if rec.seq != previous.seq + 1:
                chain.append({"seq": rec.seq, "problema": f"lacuna ou repetição de seq (anterior {previous.seq})"})
            if rec.prev_hash != previous.record_hash:
                chain.append({"seq": rec.seq, "problema": "prev_hash difere do record_hash do registro anterior"})
        if rec.recompute_hash() != rec.record_hash:
            chain.append({"seq": rec.seq, "problema": "record_hash difere do hash recalculado (registro alterado)"})
        previous = rec
    starts = {r.exec_id: r for r in records if r.tipo == TIPO_INICIO}
    for rec in records:
        if rec.tipo != TIPO_TERMINO:
            continue
        start = starts.get(rec.exec_id)
        if start is None:
            if genesis:
                pairs.append({"exec_id": rec.exec_id, "problema": "término sem início na cadeia"})
        elif rec.corpo.get("inicio_hash") != start.record_hash:
            pairs.append({"exec_id": rec.exec_id, "problema": "inicio_hash do término não confere com o início"})
        elif rec.seq <= start.seq:
            pairs.append({"exec_id": rec.exec_id, "problema": "término com seq anterior ao do início"})
    return chain, pairs


def _check_files(
    records: list[StoredRecord], output_root: Path, cache: HashCache | None, full: bool, only_session: str | None
) -> list[dict[str, Any]]:
    last_writer: dict[str, int] = {}
    for rec in records:
        if rec.tipo == TIPO_TERMINO:
            for item in rec.corpo.get("saidas") or []:
                last_writer[str(item.get("caminho"))] = rec.seq
    results: list[dict[str, Any]] = []
    for rec in records:
        if rec.tipo != TIPO_TERMINO or (only_session and rec.session_id != only_session):
            continue
        for papel, key in (("entrada", "entradas"), ("saida", "saidas")):
            for item in rec.corpo.get(key) or []:
                caminho = str(item.get("caminho"))
                entry = {"exec_id": rec.exec_id, "seq": rec.seq, "caminho": caminho, "papel": papel}
                expected = item.get("sha256")
                if last_writer.get(caminho, 0) > rec.seq:
                    results.append({**entry, "estado": FILE_SUBSTITUIDO})
                    continue
                if expected is None:
                    results.append({**entry, "estado": FILE_AUSENTE, "detalhe": "hash não registrado"})
                    continue
                path = output_root / caminho
                if not path.is_file():
                    results.append({**entry, "estado": FILE_AUSENTE})
                    continue
                try:
                    digest, _size = hash_file(path, cache, full=full)
                except OSError:
                    results.append({**entry, "estado": FILE_AUSENTE, "detalhe": "ilegível"})
                    continue
                results.append({**entry, "estado": FILE_OK if digest == expected else FILE_ALTERADO})
    return results


def _pending_entries(output_root: Path, session_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for session_id in sorted(set(session_ids)):
        path = output_root / session_id / PENDING_FILE
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("exec_id"):
                found[str(entry["exec_id"])] = entry
    return found


def _check_checkpoints(records: list[StoredRecord], output_root: Path) -> list[dict[str, Any]]:
    by_seq = {r.seq: r for r in records}
    results: list[dict[str, Any]] = []
    for session_id in sorted({r.session_id for r in records}):
        path = output_root / session_id / "checkpoint.json"
        if not path.is_file():
            continue
        try:
            tip = json.loads(path.read_text(encoding="utf-8")).get("provenance_chain_tip")
        except (OSError, ValueError, AttributeError):
            results.append({"session_id": session_id, "estado": "ilegivel", "detalhe": "checkpoint.json ilegível"})
            continue
        if not isinstance(tip, dict):
            results.append({"session_id": session_id, "estado": "sem_ponta", "detalhe": "sem provenance_chain_tip"})
            continue
        seq = tip.get("seq")
        record = by_seq.get(seq) if isinstance(seq, int) else None
        if record is None or record.record_hash != tip.get("record_hash"):
            results.append(
                {
                    "session_id": session_id, "estado": "divergente",
                    "detalhe": f"a ponta seq={seq} do checkpoint não existe na cadeia com o mesmo hash",
                }
            )
        else:
            results.append({"session_id": session_id, "estado": "ok", "detalhe": f"seq {seq}"})
    return results


def verify_project(
    store: LedgerStore,
    project_id: str,
    output_dir: Path | str,
    *,
    full: bool = False,
    cache: HashCache | None = None,
    only_session: str | None = None,
) -> VerifyReport:
    """Verifica a cadeia do projeto (ou os registros de uma sessão dentro dela).

    Raises:
        ProvenanceUnavailable: O armazenamento está indisponível (o chamador traduz em código de saída 2).
    """
    output_root = Path(output_dir).resolve()
    records = store.records(project_id)
    report = VerifyReport(project_id=project_id, registros=len(records))
    if records:
        last = records[-1]
        report.ponta = {"project_id": project_id, "seq": last.seq, "record_hash": last.record_hash}
    report.problemas_cadeia, report.problemas_pares = verify_chain(records, genesis=True)
    report.arquivos = _check_files(records, output_root, cache, full, only_session)

    scoped = [r for r in records if not only_session or r.session_id == only_session]
    pending = _pending_entries(output_root, {r.session_id for r in scoped})
    report.pendencias = sorted(pending)
    terminated = {r.exec_id: r for r in records if r.tipo == TIPO_TERMINO}
    for rec in scoped:
        if rec.tipo == TIPO_INICIO and rec.exec_id not in terminated:
            klass = ORFA_PENDENTE_LOCAL if rec.exec_id in pending else ORFA_SEM_TERMINO
            report.orfas.append({"exec_id": rec.exec_id, "classe": klass, "task_name": rec.task_name, "seq": rec.seq})
    for exec_id, entry in pending.items():
        corpo = entry.get("corpo")
        existing = terminated.get(exec_id)
        if not isinstance(corpo, dict) or entry.get("corpo_sha256") != corpo_sha256(corpo):
            report.conflitos_pendencia.append(exec_id)
        elif existing is not None:
            stored = {k: v for k, v in existing.corpo.items() if k != "registrado_localmente_em"}
            if stored != corpo:
                report.conflitos_pendencia.append(exec_id)
    report.checkpoints = _check_checkpoints(scoped, output_root)
    return report


def verify_session(
    store: LedgerStore, session_id: str, output_dir: Path | str, *, full: bool = False, cache: HashCache | None = None
) -> list[VerifyReport]:
    """Um :class:`VerifyReport` por cadeia que a sessão tocou (normalmente uma)."""
    return [
        verify_project(store, pid, output_dir, full=full, cache=cache, only_session=session_id)
        for pid in store.projects_of_session(session_id)
    ]


def load_export(directory: Path | str) -> list[StoredRecord]:
    """Registros de ``<directory>/execution_records.jsonl``.

    Raises:
        ProvenanceError: Arquivo ausente ou linha inválida.
    """
    path = Path(directory) / "execution_records.jsonl"
    if not path.is_file():
        raise ProvenanceError(f"exportação não encontrada: {path}")
    records: list[StoredRecord] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(StoredRecord.from_export(json.loads(line)))
        except (ValueError, KeyError, TypeError) as exc:
            raise ProvenanceError(f"linha {number} de {path.name} inválida: {exc}") from exc
    return records


def verify_export(directory: Path | str) -> list[VerifyReport]:
    """Verifica, sem banco, um segmento exportado: os elos a partir do primeiro ``prev_hash`` (a âncora)."""
    records = load_export(directory)
    reports: list[VerifyReport] = []
    for project_id in sorted({r.project_id for r in records}):
        chain = sorted((r for r in records if r.project_id == project_id), key=lambda r: r.seq)
        report = VerifyReport(project_id=project_id, registros=len(chain), do_export=True)
        if chain:
            report.ancora_prev_hash = chain[0].prev_hash
            report.ponta = {"project_id": project_id, "seq": chain[-1].seq, "record_hash": chain[-1].record_hash}
        report.problemas_cadeia, report.problemas_pares = verify_chain(chain, genesis=False)
        reports.append(report)
    return reports
