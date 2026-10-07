"""Checkpoint incremental e atômico (v18-research-continuity, requisito "Checkpoint incremental e atômico")."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.continuity import (
    BACKUP_FILENAME,
    CHECKPOINT_FILENAME,
    ESTADO_FECHADO,
    CheckpointError,
    CheckpointRecorder,
    CheckpointVersionError,
    list_task_artifacts,
    plan_entry,
    read_checkpoint,
    resolve_session_dir,
)
from src.orchestrator import AgentTask

pytestmark = pytest.mark.unit


@pytest.fixture
def sdir(tmp_path: Path) -> Path:
    d = tmp_path / "out" / "sessao-1"
    d.mkdir(parents=True)
    return d


def _recorder(sdir: Path) -> CheckpointRecorder:
    return CheckpointRecorder.start(
        sdir, session_id="sessao-1", project_id=None, continues_session_id=None, prompt="p", modo="auto",
        orcamento={"max_tokens": 1000},
    )


def _plan(*names: str) -> list[dict]:
    return [plan_entry(AgentTask(agent_id="developer", prompt=f"faz {n}", task_name=n, subtask_id=f"id-{n}"))
            for n in names]


def test_apos_cada_subtarefa(sdir):
    """Scenario: Após cada subtarefa — o checkpoint reflete status, tentativas, artefatos e resumo."""
    rec = _recorder(sdir)
    rec.set_plan(_plan("coleta", "treino"))
    (sdir / "coleta").mkdir()
    (sdir / "coleta" / "metrics.json").write_text("{}", encoding="utf-8")

    rec.subtask_started("coleta", 1)
    cp, _ = read_checkpoint(sdir)
    assert cp.find("coleta").status == "em_andamento"

    rec.subtask_finished(
        "coleta", status="concluida", tentativas=2, resumo="dados prontos",
        artefatos=list_task_artifacts(sdir, "coleta"),
    )
    cp, origem = read_checkpoint(sdir)
    sub = cp.find("coleta")
    assert (sub.status, sub.tentativas, sub.resultado_resumo) == ("concluida", 2, "dados prontos")
    assert sub.artefatos == ["coleta/metrics.json"]
    assert cp.find("treino").status == "pendente"
    assert origem == "principal" and cp.plano_versao == 1
    assert cp.orcamento == {"max_tokens": 1000}
    # arquivo privado e versionado
    assert (os.stat(sdir / CHECKPOINT_FILENAME).st_mode & 0o777) == 0o600
    assert json.loads((sdir / CHECKPOINT_FILENAME).read_text(encoding="utf-8"))["versao_checkpoint"] == 1


def test_queda_durante_a_gravacao_mantem_o_anterior(sdir):
    """Scenario: Queda durante a gravação — o checkpoint anterior permanece íntegro e legível."""
    rec = _recorder(sdir)
    rec.set_plan(_plan("a"))
    rec.subtask_finished("a", status="concluida", tentativas=1, resumo="ok")
    before = (sdir / CHECKPOINT_FILENAME).read_bytes()

    with patch("src.continuity.os.replace", side_effect=OSError("queda")):
        assert rec.subtask_started("a", 2) is False  # falha isolada, sem levantar
    assert rec.failures == 1
    assert (sdir / CHECKPOINT_FILENAME).read_bytes() == before
    assert not list(sdir.glob(".checkpoint.json.*.tmp"))  # temporário removido
    cp, _ = read_checkpoint(sdir)
    assert cp.find("a").status == "concluida"


def test_gravacao_interrompida_no_meio_do_arquivo(sdir):
    """Scenario: Queda durante a gravação — temporário truncado órfão não afeta a leitura."""
    rec = _recorder(sdir)
    rec.set_plan(_plan("a"))
    (sdir / ".checkpoint.json.1.deadbeef.tmp").write_bytes(b'{"versao_checkpoint": 1, "sess')
    cp, origem = read_checkpoint(sdir)
    assert cp.find("a") is not None and origem == "principal"
    rec.subtask_started("a", 1)  # próxima gravação limpa a sobra
    assert not list(sdir.glob(".checkpoint.json.*.tmp"))


def test_principal_corrompido_usa_o_backup(sdir):
    rec = _recorder(sdir)
    rec.set_plan(_plan("a"))
    rec.subtask_finished("a", status="concluida", tentativas=1)
    (sdir / CHECKPOINT_FILENAME).write_bytes(b'{"truncado":')
    cp, origem = read_checkpoint(sdir)
    assert origem == "backup" and cp.find("a") is not None
    # um principal corrompido não sobrescreve o backup bom na próxima gravação
    good_backup = (sdir / BACKUP_FILENAME).read_bytes()
    rec.subtask_started("a", 2)
    assert (sdir / BACKUP_FILENAME).read_bytes() == good_backup


def test_sem_nenhum_valido_erro_acionavel(sdir):
    (sdir / CHECKPOINT_FILENAME).write_text("{}", encoding="utf-8")
    os.chmod(sdir / CHECKPOINT_FILENAME, 0o600)
    with pytest.raises(CheckpointError, match="nenhum checkpoint válido"):
        read_checkpoint(sdir)


# -- segurança: o arquivo é dado não confiável --------------------------------------------------


def _valid_dict(sdir: Path) -> dict:
    _recorder(sdir)
    return json.loads((sdir / CHECKPOINT_FILENAME).read_text(encoding="utf-8"))


def _put(sdir: Path, data: object | str, mode: int = 0o600) -> None:
    for name in (BACKUP_FILENAME,):
        (sdir / name).unlink(missing_ok=True)
    path = sdir / CHECKPOINT_FILENAME
    path.unlink(missing_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    os.chmod(path, mode)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d.update(versao_checkpoint=99), "mais nova"),
        (lambda d: d.update(versao_checkpoint="1"), "nenhum checkpoint válido"),
        (lambda d: d.update(session_id="outra-sessao"), "não corresponde"),
        (lambda d: d.update(session_id="../x"), "nenhum checkpoint válido"),
        (lambda d: d.update(project_id="nao-e-uuid"), "nenhum checkpoint válido"),
        (lambda d: d.update(estado="hackeado"), "nenhum checkpoint válido"),
        (lambda d: d.update(motivo_parada="inventado"), "nenhum checkpoint válido"),
        (lambda d: d["plano"].update(subtarefas=[{"task_name": "../../etc", "status": "pendente"}]), "nenhum"),
        (lambda d: d["plano"].update(subtarefas=[{"task_name": "a", "status": "pwn"}]), "nenhum"),
        (lambda d: d["plano"].update(subtarefas=[{"task_name": "a", "status": "pendente"}] * 2), "nenhum"),
        (lambda d: d.update(prompt_original="x" * 30_000), "nenhum"),
        (lambda d: d.update(curator_pendente="sim"), "nenhum"),
    ],
)
def test_schema_estrito_recusa_dado_invalido(sdir, mutate, match):
    data = _valid_dict(sdir)
    mutate(data)
    _put(sdir, data)
    with pytest.raises(CheckpointError, match=match):
        read_checkpoint(sdir)


def test_recusa_nan_infinity_e_json_invalido(sdir):
    data = _valid_dict(sdir)
    data["consumo"] = {"tokens": 1}
    _put(sdir, json.dumps(data).replace('"tokens": 1', '"tokens": NaN'))
    with pytest.raises(CheckpointError):
        read_checkpoint(sdir)
    _put(sdir, "[" * 100000)  # aninhamento absurdo: sem estourar a pilha
    with pytest.raises(CheckpointError):
        read_checkpoint(sdir)


def test_recusa_arquivo_grande_demais(sdir):
    data = _valid_dict(sdir)
    _put(sdir, data)
    with patch("src.continuity.config.CHECKPOINT_MAX_BYTES", 50):
        with pytest.raises(CheckpointError, match="excede"):
            read_checkpoint(sdir)


def test_recusa_link_simbolico_e_permissao_aberta(sdir, tmp_path):
    data = _valid_dict(sdir)
    real = tmp_path / "alvo.json"
    real.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(real, 0o600)
    (sdir / CHECKPOINT_FILENAME).unlink()
    (sdir / BACKUP_FILENAME).unlink(missing_ok=True)
    os.symlink(real, sdir / CHECKPOINT_FILENAME)
    with pytest.raises(CheckpointError):
        read_checkpoint(sdir)
    _put(sdir, data, mode=0o666)
    with pytest.raises(CheckpointError, match="permissão"):
        read_checkpoint(sdir)


def test_versao_nova_nao_cai_para_o_backup(sdir):
    rec = _recorder(sdir)
    rec.set_plan(_plan("a"))
    data = json.loads((sdir / CHECKPOINT_FILENAME).read_text(encoding="utf-8"))
    data["versao_checkpoint"] = 2
    (sdir / CHECKPOINT_FILENAME).write_text(json.dumps(data), encoding="utf-8")
    os.chmod(sdir / CHECKPOINT_FILENAME, 0o600)
    with pytest.raises(CheckpointVersionError):
        read_checkpoint(sdir)


def test_resolve_session_dir_confina_e_recusa_link(tmp_path):
    base = tmp_path / "outputs"
    (base / "ok").mkdir(parents=True)
    outside = tmp_path / "fora"
    outside.mkdir()
    os.symlink(outside, base / "link")
    assert resolve_session_dir(base, "ok") == (base / "ok").resolve()
    for bad in ("../fora", "a/b", "link", "nao-existe", "", "..", ".hidden/.."):
        with pytest.raises(CheckpointError):
            resolve_session_dir(base, bad)


def test_escrita_recusa_checkpoint_gigante(sdir):
    rec = _recorder(sdir)
    with patch("src.continuity.config.CHECKPOINT_MAX_BYTES", 100):
        assert rec.set_plan(_plan("a")) is False
    assert rec.failures >= 1


def test_plano_preserva_concluidas_ao_replanejar(sdir):
    rec = _recorder(sdir)
    rec.set_plan(_plan("a", "b"))
    rec.subtask_finished("a", status="concluida", tentativas=1, resumo="r")
    rec.set_plan(_plan("b", "c"))  # novo plano omite "a"
    cp, _ = read_checkpoint(sdir)
    assert {s.task_name for s in cp.subtarefas} == {"a", "b", "c"}
    assert cp.find("a").status == "concluida" and cp.plano_versao == 2


def test_fechamento_marca_estado_e_nada_fica_em_andamento(sdir):
    rec = _recorder(sdir)
    rec.set_plan(_plan("a"))
    rec.subtask_started("a", 1)
    rec.close(ESTADO_FECHADO, "limite_tokens", curator_pendente=True)
    cp, _ = read_checkpoint(sdir)
    assert (cp.estado, cp.motivo_parada, cp.curator_pendente) == ("fechado", "limite_tokens", True)
    assert cp.find("a").status == "pendente"
