"""Avaliação de comunicação: verdade, revisor, resolução, laços e reparos (v16-agent-communication-eval)."""

import json
import os
import time

import pytest

from scripts.benchmark import communication as comm

pytestmark = pytest.mark.unit


def ev(event_type, ts, task=None, agent="x", **payload):
    return {"event_type": event_type, "agent_id": agent, "target_agent_id": None, "task_name": task,
            "ts": float(ts), "payload": payload}


def _write(root, rel, content="x"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _truth(task, tmp_path, ts=None, sandbox=None, attempt=1):
    return comm.compute_truth(task, attempt, ts, tmp_path, sandbox or [])


# --- verdade determinística --------------------------------------------------------------------

def test_artefatos_e_metrica_cumpridos(tmp_path):
    """Scenario: Artefatos e métrica cumpridos."""
    _write(tmp_path, "m/model.json")
    _write(tmp_path, "m/metrics.json", json.dumps({"metrics": {"accuracy": 0.95}}))
    task = {"task_name": "m", "expected_artifacts": ["model.json"], "validation_criteria": ["acurácia >= 0.9"]}
    assert _truth(task, tmp_path).verdict == "fulfilled"


def test_artefato_com_outro_prefixo(tmp_path):
    """Scenario: Artefato com outro prefixo (iris_*.png no lugar de eda_*.png)."""
    _write(tmp_path, "eda/iris_hist.png")
    task = {"task_name": "eda", "expected_artifacts": ["eda_hist.png"], "validation_criteria": ["gráfico"]}
    truth = _truth(task, tmp_path)
    assert truth.verdict == "fulfilled" and truth.checks[0].ok


def test_artefato_ausente(tmp_path):
    """Scenario: Artefato ausente."""
    (tmp_path / "eda").mkdir()
    truth = _truth({"task_name": "eda", "expected_artifacts": ["x.png"]}, tmp_path)
    assert truth.verdict == "unfulfilled" and truth.checks[0].subject == "x.png"


def test_so_criterios_qualitativos(tmp_path):
    """Scenario: Só critérios qualitativos."""
    truth = _truth({"task_name": "t", "validation_criteria": ["texto claro"]}, tmp_path)
    assert truth.verdict == "indeterminate"


def test_codigo_de_saida_nao_decide_sozinho(tmp_path):
    """Scenario: Código de saída não decide sozinho."""
    runs = [ev("sandbox_run", 1, "t", exit_code=0, timed_out=False)]
    truth = _truth({"task_name": "t", "validation_criteria": ["texto claro"]}, tmp_path, sandbox=runs)
    assert truth.verdict == "indeterminate"


def test_execucao_com_erro_e_artefatos_presentes_e_indeterminada(tmp_path):
    _write(tmp_path, "t/a.png")
    runs = [ev("sandbox_run", 1, "t", exit_code=1, timed_out=False)]
    truth = _truth({"task_name": "t", "expected_artifacts": ["a.png"]}, tmp_path, ts=time.time() + 100, sandbox=runs)
    assert truth.verdict == "indeterminate" and "erro" in truth.detail


def test_artefatos_sobrescritos_por_tentativa_posterior(tmp_path):
    """Scenario: Artefatos sobrescritos por tentativa posterior."""
    path = _write(tmp_path, "t/a.png")
    os.utime(path, (2000, 2000))
    truth = _truth({"task_name": "t", "expected_artifacts": ["a.png"]}, tmp_path, ts=1000.0)
    assert truth.verdict == "indeterminate" and truth.detail == "artefatos sobrescritos"


def test_metrica_abaixo_do_limiar_e_nao_cumprida(tmp_path):
    _write(tmp_path, "m/metrics.json", json.dumps({"metrics": {"accuracy": 0.5}}))
    truth = _truth({"task_name": "m", "validation_criteria": ["acurácia >= 0.9"]}, tmp_path)
    assert truth.verdict == "unfulfilled"


# --- veredito do revisor -----------------------------------------------------------------------

def test_falso_reprovado_e_falso_aprovado():
    """Scenarios: Falso reprovado / Falso aprovado."""
    out = comm.reviewer_confusion([(False, "fulfilled"), (True, "unfulfilled"), (True, "fulfilled")])
    assert out["false_reject"] == 1 and out["false_accept"] == 1 and out["hit"] == 1


def test_indeterminadas_ficam_fora_das_taxas():
    """Scenario: Indeterminadas fora das taxas."""
    pairs = [(True, "fulfilled")] * 3 + [(False, "fulfilled")] + [(True, "indeterminate")] * 2
    out = comm.reviewer_confusion(pairs)
    assert out["false_reject_rate"] == 0.25 and out["indeterminate_share"] == round(2 / 6, 4)


def test_denominador_zero_e_null():
    """Scenario: Denominador zero."""
    out = comm.reviewer_confusion([(True, "fulfilled")])
    assert out["false_accept_rate"] is None


def test_avaliacao_sem_revisoes_traz_null_sem_erro(tmp_path):
    """Scenario: Evento esperado ausente."""
    out = comm.evaluate_events([ev("spawn", 1)], {}, tmp_path, {})
    assert out["reviewer"]["reviews"] == 0 and out["reviewer"]["confusion"]["false_reject_rate"] is None


def _review(ts, task, approved, **kw):
    return ev("subtask_review", ts, task, approved=approved, status="pass" if approved else "fail", **kw)


def test_desacordos_listam_tarefa_tentativa_e_assinatura(tmp_path):
    _write(tmp_path, "t/a.png")
    plan = {"t": {"task_name": "t", "expected_artifacts": ["a.png"]}}
    out = comm.evaluate_events([_review(time.time() + 50, "t", False, attempt=2, signature="abc")], plan, tmp_path,
                               {"reviewer": "google/m"})
    mismatch = out["reviewer"]["mismatches"][0]
    assert mismatch["task_name"] == "t" and mismatch["attempt"] == 2 and mismatch["signature"] == "abc"
    assert out["reviewer"]["confusion"]["false_reject"] == 1


# --- resolução e laços -------------------------------------------------------------------------

def seq(*items):
    return [{"approved": a, "signature": s} for a, s in items]


def test_reprovacao_resolvida():
    """Scenario: Reprovação resolvida."""
    out = comm.resolution_stats({"modelo": seq((False, "a"), (False, "a"), (True, None))})
    assert out["resolved"] == 2 and out["attempts_to_resolve_max"] == 2 and out["unresolved_tail"] == 0


def test_reprovacao_final_sem_evento_seguinte():
    """Scenario: Reprovação final sem evento seguinte."""
    out = comm.resolution_stats({"eda": seq((True, None), (False, "a"))})
    assert out["unresolved_tail"] == 1 and out["resolved"] == 0 and out["resolution_rate_with_tail"] == 0.0


def test_plano_aprovado_com_avisos_resolve():
    """Scenario: Plano aprovado com avisos."""
    events = [ev("plan_validation", 1, approved=False, signature="s"),
              ev("plan_validation", 2, approved=True, approved_with_warnings=True)]
    plan_seq, _ = comm.build_sequences(events)
    assert comm.resolution_stats(plan_seq)["resolved"] == 1


def test_laco_de_tres():
    """Scenario: Laço de três."""
    out = comm.loop_stats({"modelo": seq((False, "s"), (False, "s"), (False, "s"))}, min_length=3)
    assert out["loops"] == 1 and out["max_length"] == 3 and out["rejections_in_loop_share"] == 1.0


def test_duas_reprovacoes_iguais_nao_sao_laco():
    """Scenario: Duas reprovações iguais não são laço."""
    assert comm.loop_stats({"m": seq((False, "s"), (False, "s"))}, min_length=3)["loops"] == 0


def test_assinaturas_diferentes_nao_sao_laco():
    """Scenario: Assinaturas diferentes."""
    assert comm.loop_stats({"m": seq((False, "a"), (False, "b"), (False, "c"))}, min_length=3)["loops"] == 0


def test_laco_atribuido_ao_revisor_e_ao_validator_separadamente(tmp_path):
    events = [_review(i, "t", False, signature="s") for i in range(1, 4)]
    events += [ev("plan_validation", 10 + i, approved=False, signature="p") for i in range(2)]
    out = comm.evaluate_events(events, {}, tmp_path, {})
    loops = out["resolution"]["loops"]
    assert loops["reviewer"]["loops"] == 1 and loops["validator"]["loops"] == 0


# --- reparos do planejador ---------------------------------------------------------------------

def test_contagem_de_reparos():
    """Scenario: Contagem de reparos."""
    events = [ev("plan_validation", i, approved=False) for i in range(3)]
    events += [ev("plan_normalized", 1, repairs=[{"kind": "coerce_list"}]),
               ev("plan_normalized", 2, repairs=[{"kind": "snake_case_name"}, {"kind": "coerce_list"}])]
    out = comm.planner_repairs(events)
    assert out == {"plans": 3, "with_repair": 2, "by_kind": {"coerce_list": 2, "snake_case_name": 1}}


# --- somente leitura ---------------------------------------------------------------------------

def test_avaliacao_nao_escreve_na_sessao(tmp_path):
    """Scenario: Avaliação não escreve na sessão."""
    session = tmp_path / "sess"
    _write(session, "t/a.png")
    before = sorted(p.as_posix() for p in session.rglob("*"))
    comm.evaluate_events([_review(1, "t", True)], {"t": {"task_name": "t", "expected_artifacts": ["a.png"]}},
                         session, {})
    assert sorted(p.as_posix() for p in session.rglob("*")) == before
    comm.write_result({"x": 1}, tmp_path / "out" / "r.json", session)
    assert (tmp_path / "out" / "r.json").exists()
    with pytest.raises(ValueError):
        comm.write_result({"x": 1}, session / "r.json", session)


def test_plan_json_ausente_nao_quebra(tmp_path):
    assert comm.load_plan(tmp_path) == {}
    (tmp_path / "plan.json").write_text(json.dumps([{"task_name": "a"}]))
    assert "a" in comm.load_plan(tmp_path)


# --- correções da revisão de segurança (PR #98) ------------------------------------------------

def test_nome_de_subtarefa_com_travessia_e_indeterminado(tmp_path):
    """I4: `task_name` e `depends_on` do plano não saem da pasta da sessão."""
    outside = tmp_path / "fora"
    _write(outside, "metrics.json", json.dumps({"metrics": {"accuracy": 0.99}}))
    session = tmp_path / "sess"
    session.mkdir()
    for task in ({"task_name": "../fora", "validation_criteria": ["acurácia >= 0.9"]},
                 {"task_name": "ok", "depends_on": ["../fora"], "validation_criteria": ["acurácia >= 0.9"]}):
        truth = comm.compute_truth(task, 1, None, session, [])
        assert truth.verdict == "indeterminate" and "inválido" in truth.detail


def test_metrics_json_por_link_simbolico_para_fora_nao_e_lido(tmp_path):
    outside = tmp_path / "fora"
    _write(outside, "metrics.json", json.dumps({"metrics": {"accuracy": 0.99}}))
    session = tmp_path / "sess"
    (session / "m").mkdir(parents=True)
    os.symlink(outside / "metrics.json", session / "m" / "metrics.json")
    truth = comm.compute_truth({"task_name": "m", "validation_criteria": ["acurácia >= 0.9"]}, 1, None, session, [])
    assert truth.verdict == "unfulfilled" and truth.checks[0].detail == "metrics.json ausente"


@pytest.mark.parametrize("content", ["[1, 2]", '{"metrics": [1]}', '{"metrics": "x"}', "nao é json"])
def test_metrics_json_malformado_nao_derruba_a_avaliacao(tmp_path, content):
    """I4: metrics.json com forma inesperada vira não cumprido, sem exceção."""
    _write(tmp_path, "m/metrics.json", content)
    truth = comm.compute_truth({"task_name": "m", "validation_criteria": ["acurácia >= 0.9"]}, 1, None, tmp_path, [])
    assert truth.verdict == "unfulfilled"


def test_erro_inesperado_na_verdade_vira_indeterminada(tmp_path, monkeypatch):
    monkeypatch.setattr(comm, "compute_truth", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    out = comm.evaluate_events([_review(1, "t", True)], {"t": {"task_name": "t"}}, tmp_path, {})
    assert out["reviewer"]["confusion"]["indeterminate"] == 1


def test_metrics_json_corrigido_depois_da_revisao_e_indeterminado(tmp_path):
    """I6: a sobrescrita do metrics.json também vale, não só a dos artefatos."""
    path = _write(tmp_path, "m/metrics.json", json.dumps({"metrics": {"accuracy": 0.99}}))
    os.utime(path, (2000, 2000))
    truth = comm.compute_truth({"task_name": "m", "validation_criteria": ["acurácia >= 0.9"]}, 1, 1000.0, tmp_path, [])
    assert truth.verdict == "indeterminate" and truth.detail == "artefatos sobrescritos"


def test_cli_recusa_session_id_invalido(tmp_path):
    with pytest.raises(SystemExit):
        comm.main(["evaluate", "../x", "--output-dir", str(tmp_path), "--out", str(tmp_path / "o.json")])
