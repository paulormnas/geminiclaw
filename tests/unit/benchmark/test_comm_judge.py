"""Juiz LLM, redação, orçamento e calibração (v16-agent-communication-eval)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.benchmark import comm_judge as cj
from scripts.benchmark.communication import main as comm_main
from src.llm.base import LLMResponse

pytestmark = pytest.mark.unit

DEV = "google/gemini-3.8-flash"
LITE = "google/gemini-3.1-flash-lite"
SONNET = "anthropic/claude-sonnet-5-5"
GOOD = json.dumps({"necessidade": 3, "clareza": 2, "justificativa": "ok"})


def models(**kw):
    base = {"developer": DEV, "researcher": DEV, "reviewer": LITE}
    base.update(kw)
    return base


def event(i=1, asker="developer", asker_model=DEV, answer=None, options=None, context="ctx"):
    payload = {"question": f"Qual split? {i}", "why_cant_proceed": "ambíguo", "options": options or ["80/20"],
               "context": context}
    if answer:
        payload["resposta"] = answer
    return {"ref": f"r{i}", "session_id": "s", "agent_id": asker, "task_name": "t", "ts": float(i),
            "payload": payload, "asker_model": asker_model}


def factory(*texts, usage=None):
    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=[LLMResponse(text=t, usage=usage or {}) for t in texts])
    return provider, (lambda name, model: provider)


# --- seleção -----------------------------------------------------------------------------------

def test_selecao_entre_os_demais_papeis():
    """Scenario: Seleção entre os demais papéis."""
    sel = cj.select_judge(models())
    assert sel.key == LITE and sel.excluded == [DEV]


def test_preferencia_por_outro_provedor():
    """Scenario: Preferência por outro provedor."""
    sel = cj.select_judge(models(), candidates=[SONNET])
    assert sel.key == SONNET and "provedor diferente" in sel.reason


def test_sem_candidato_valido_lista_os_excluidos():
    """Scenario: Sem candidato válido."""
    with pytest.raises(cj.JudgeUnavailable) as err:
        cj.select_judge({"developer": DEV, "researcher": DEV, "reviewer": DEV})
    assert DEV in str(err.value) and "COMM_EVAL_JUDGE_CANDIDATES" in str(err.value)


def test_modelo_do_agente_que_perguntou_gera_same_model():
    """Scenario: Modelo do agente que perguntou."""
    assert cj.select_judge(models(), asking_model=LITE) is None
    out = cj.judge_events([event(asker_model=LITE)], models(), provider_factory=lambda *a: None,
                          allow_external=True, max_usd=1.0)
    assert out["events"][0]["reason"] == "same_model" and out["skipped"] == {"same_model": 1}


def test_sobrescrita_igual_a_modelo_excluido_e_recusada():
    """Scenario: Sobrescrita igual a modelo excluído."""
    with pytest.raises(cj.JudgeUnavailable):
        cj.select_judge(models(), override=DEV)


def test_juiz_sem_candidato_nao_derruba_o_resto():
    out = cj.judge_events([event()], {"developer": DEV, "researcher": DEV}, provider_factory=lambda *a: None)
    assert "error" in out and out["events"] == []


# --- notas -------------------------------------------------------------------------------------

def run(events, texts=(), provider_models=None, **kw):
    provider, fac = factory(*texts, usage=kw.pop("usage", None))
    kw.setdefault("allow_external", True)
    kw.setdefault("max_usd", 1.0)
    out = cj.judge_events(events, provider_models or models(), provider_factory=fac, **kw)
    return out, provider


def test_nota_valida_grava_modelo_e_versao_da_rubrica():
    """Scenario: Nota válida."""
    out, _ = run([event()], [GOOD], provider_models=models(reviewer=LITE), allow_external=True)
    entry = out["events"][0]
    assert entry["status"] == "judged" and entry["scores"]["necessidade"] == 3
    assert entry["judge"] == LITE and entry["rubric_version"] == cj.RUBRIC_VERSION


def test_saida_invalida_duas_vezes_vira_judge_error():
    """Scenario: Saída inválida."""
    out, provider = run([event()], ["não é json", '{"necessidade": 9}'])
    assert out["events"][0]["status"] == "judge_error" and "scores" not in out["events"][0]
    assert provider.generate.await_count == 2


def test_saida_invalida_seguida_de_valida_usa_a_segunda():
    out, _ = run([event()], ["lixo", GOOD])
    assert out["events"][0]["status"] == "judged"


def test_criterios_de_resposta_so_com_resposta():
    """Scenario: Critérios de resposta só com resposta."""
    out, provider = run([event()], [GOOD])
    assert set(out["events"][0]["scores"]) == {"necessidade", "clareza", "justificativa"}
    assert "RESPOSTA:" not in provider.generate.call_args.kwargs["messages"][0]["content"]


def test_efeito_deterministico_sem_chamar_o_juiz_para_ele():
    """Scenario: Efeito determinístico."""
    answer = json.dumps({"necessidade": 3, "clareza": 3, "resposta": 3, "justificativa": "ok"})
    out, provider = run([event(answer="Use 80/20", options=["80/20"])], [answer],
                        texts_by_task={"t": ["Aplicar split 80/20 nos dados"]})
    scores = out["events"][0]["scores"]
    assert scores["efeito"] == 3 and scores["efeito_origem"] == "codigo"
    assert "TEXTOS POSTERIORES" not in provider.generate.call_args.kwargs["messages"][0]["content"]


def test_efeito_pedido_ao_juiz_quando_o_codigo_nao_decide():
    full = json.dumps({"necessidade": 2, "clareza": 2, "resposta": 3, "efeito": 1, "justificativa": "x"})
    out, provider = run([event(answer="Use 70/30", options=["80/20"])], [full], texts_by_task={"t": ["algo"]})
    assert out["events"][0]["scores"]["efeito"] == 1
    assert "TEXTOS POSTERIORES" in provider.generate.call_args.kwargs["messages"][0]["content"]


def test_deterministic_effect_unidade():
    assert cj.deterministic_effect("Use 80/20", ["80/20"], ["split 80/20"]) == 3
    assert cj.deterministic_effect("Use 80/20", ["80/20"], ["outro"]) is None
    assert cj.deterministic_effect(None, ["a"], ["a"]) is None


# --- dados enviados ----------------------------------------------------------------------------

def test_juiz_externo_nao_habilitado():
    """Scenario: Juiz externo não habilitado."""
    provider, fac = factory(GOOD)
    out = cj.judge_events([event()], models(), provider_factory=fac, allow_external=False, max_usd=1.0)
    assert "COMM_EVAL_ALLOW_EXTERNAL_JUDGE" in out["error"] and provider.generate.await_count == 0


def test_juiz_local_roda_sem_opt_in_nem_teto():
    provider, fac = factory(GOOD)
    out = cj.judge_events([event()], models(reviewer="ollama/qwen3:8b"), provider_factory=fac,
                          allow_external=False, max_usd=0.0)
    assert out["events"][0]["status"] == "judged"


def test_redacao():
    """Scenario: Redação."""
    text = "acurácia 0.9667 em iris.csv, ver https://exemplo.org e a@b.com, id 1234567"
    out = cj.redact_for_judge(text, ["iris.csv"], max_chars=500)
    assert "<num>" in out and "<arquivo>" in out and "<url>" in out and "<email>" in out
    for original in ("0.9667", "iris.csv", "exemplo.org", "a@b.com", "1234567"):
        assert original not in out


def test_truncamento_do_contexto():
    """Scenario: Truncamento."""
    assert len(cj.redact_for_judge("x" * 2000, max_chars=400)) == 400


def test_prompt_enviado_ao_juiz_vai_redigido():
    _, provider = run([event(context="dataset iris.csv acurácia 0.9667")], [GOOD], protected_names=["iris.csv"])
    sent = provider.generate.call_args.kwargs["messages"][0]["content"]
    assert "iris.csv" not in sent and "0.9667" not in sent


# --- teto de custo -----------------------------------------------------------------------------

def test_teto_zero_nao_faz_chamada_paga():
    """Scenario: Teto zero."""
    out, provider = run([event(1), event(2)], [GOOD], provider_models=models(reviewer=SONNET),
                        max_usd=0.0)
    assert {e["reason"] for e in out["events"]} == {"budget"} and provider.generate.await_count == 0


def test_teto_atingido_no_meio():
    """Scenario: Teto atingido no meio."""
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 0}  # sonnet: US$ 2,00 por chamada
    out, _ = run([event(i) for i in range(1, 6)], [GOOD] * 5, provider_models=models(reviewer=SONNET),
                 max_usd=5.0, usage=usage)
    statuses = [e["status"] for e in out["events"]]
    assert statuses == ["judged"] * 3 + ["judge_skipped"] * 2
    assert out["events"][3]["reason"] == "budget" and out["cost_usd"] == 6.0


def test_preco_desconhecido_de_modelo_externo_e_recusado():
    out, provider = run([event()], [GOOD], provider_models=models(reviewer="openai/modelo-sem-preco"))
    assert "Preço desconhecido" in out["error"] and provider.generate.await_count == 0


# --- calibração --------------------------------------------------------------------------------

def sample_events():
    return [{**event(i, asker=role), "session_id": sid, "ref": f"{sid}{role}{i}"}
            for sid in ("s1", "s2") for role in ("developer", "researcher") for i in range(5)]


def test_amostra_reprodutivel_e_estratificada():
    """Scenario: Amostra reprodutível."""
    a = cj.calibration_sample(sample_events(), 8, seed=7)
    b = cj.calibration_sample(sample_events(), 8, seed=7)
    assert [e["ref"] for e in a] == [e["ref"] for e in b] and len(a) == 8
    assert {(e["session_id"], e["agent_id"]) for e in a} == {
        (s, r) for s in ("s1", "s2") for r in ("developer", "researcher")}


def test_planilha_em_branco(tmp_path):
    cj.write_sheet(cj.calibration_sample(sample_events(), 3, 1), tmp_path / "sheet.jsonl")
    rows = [json.loads(line) for line in (tmp_path / "sheet.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and all(r["necessidade"] is None and r["rotulador"] is None for r in rows)


def test_kappa_concordancia_total_e_valores_conhecidos():
    """Scenario: Concordância total."""
    assert cj.weighted_kappa([1, 2, 3, 3, 2], [1, 2, 3, 3, 2]) == 1.0
    assert cj.weighted_kappa([1, 2, 3, 1, 2, 3], [3, 2, 1, 3, 2, 1]) < 0
    # Cálculo à mão: n=4, a=[1,1,3,3], b=[1,2,3,3] com pesos quadráticos em 3 categorias
    # observado ponderado = 0,25 (um par 1x2); esperado ponderado = 7,0 / 4 = 1,75 -> kappa = 1 - 0,25 / 1,75
    assert cj.weighted_kappa([1, 1, 3, 3], [1, 2, 3, 3]) == round(6 / 7, 4)


def _write_calibration(tmp_path, kappa, n=20, model=LITE, version=cj.RUBRIC_VERSION):
    path = tmp_path / "resultado.json"
    path.write_text(json.dumps({"n": n, "kappa": kappa, "judge_model": model, "rubric_version": version}))
    return path


def test_calibrado_quando_tudo_bate(tmp_path):
    path = _write_calibration(tmp_path, {"necessidade": 0.8, "clareza": 0.7})
    assert cj.calibration_status(path, LITE, cj.RUBRIC_VERSION)["calibrated"] is True


def test_concordancia_baixa_marca_nao_calibrado(tmp_path):
    """Scenario: Concordância baixa."""
    status = cj.calibration_status(_write_calibration(tmp_path, {"necessidade": 0.4, "clareza": 0.9}), LITE,
                                   cj.RUBRIC_VERSION)
    assert status["calibrated"] is False and status["kappa"]["necessidade"] == 0.4


def test_poucos_rotulos(tmp_path):
    """Scenario: Poucos rótulos."""
    status = cj.calibration_status(_write_calibration(tmp_path, {"necessidade": 0.9, "clareza": 0.9}, n=12), LITE,
                                   cj.RUBRIC_VERSION)
    assert status["calibrated"] is False and "20" in status["reason"]


def test_mudanca_de_modelo_invalida_a_calibracao(tmp_path):
    """Scenario: Mudança de modelo invalida a calibração."""
    path = _write_calibration(tmp_path, {"necessidade": 0.9, "clareza": 0.9})
    assert cj.calibration_status(path, SONNET, cj.RUBRIC_VERSION)["calibrated"] is False
    assert cj.calibration_status(path, LITE, "2")["calibrated"] is False


def test_sem_arquivo_de_calibracao(tmp_path):
    assert cj.calibration_status(tmp_path / "nao_existe.json", LITE, cj.RUBRIC_VERSION)["calibrated"] is False


def test_calibrate_calcula_kappa_por_criterio(tmp_path):
    judged = [{"event_ref": f"r{i}", "status": "judged", "judge": LITE, "rubric_version": "1",
               "scores": {"necessidade": s, "clareza": s}} for i, s in enumerate([1, 2, 3, 2])]
    (tmp_path / "j.json").write_text(json.dumps({"events": judged}))
    labels = [{"event_ref": f"r{i}", "necessidade": s, "clareza": 2} for i, s in enumerate([1, 2, 3, 2])]
    (tmp_path / "l.jsonl").write_text("\n".join(json.dumps(x) for x in labels))
    out = cj.calibrate(tmp_path / "j.json", tmp_path / "l.jsonl")
    assert out["n"] == 4 and out["kappa"]["necessidade"] == 1.0 and out["judge_model"] == LITE


def test_rotulo_invalido_e_recusado(tmp_path):
    (tmp_path / "l.jsonl").write_text(json.dumps({"event_ref": "r", "necessidade": 5, "clareza": 1}))
    with pytest.raises(ValueError):
        cj.read_labels(tmp_path / "l.jsonl")


# --- integração com o benchmark ----------------------------------------------------------------

def test_summarize_events_inalterado():
    """Scenario: Saída atual preservada."""
    from scripts.benchmark import interactions

    events = [{"event_type": "plan_validation", "payload": {"approved": True}},
              {"event_type": "subtask_review", "payload": {"approved": False, "issues": ["x"]}}]
    assert interactions.summarize_events(events)["subtask_reviews"] == {"total": 1, "approved": 0,
                                                                       "rejections": [["x"]]}


def test_eval_comm_roda_depois_da_execucao_e_nao_executa_combinacoes(tmp_path, monkeypatch):
    """Scenario: Ordem de execução."""
    from scripts.benchmark import run_benchmark as rb

    results = tmp_path / "results.json"
    results.write_text(json.dumps([{"name": "c1", "session": "sess1", "status": "exit 0"}]))
    calls = []
    monkeypatch.setattr(rb, "run_combination", lambda *a, **k: calls.append("run"))
    monkeypatch.setattr("scripts.benchmark.communication.fetch_session_data",
                        lambda sid: {"events": [], "models_by_role": {}})
    monkeypatch.setattr("sys.argv", ["run_benchmark", "matrix.json", "--results", str(results), "--eval-comm"])
    rb.main()
    saved = json.loads(results.read_text())
    assert calls == [] and saved[0]["comm_eval"]["reviewer"]["reviews"] == 0
    assert (tmp_path / "results-comm-sess1.json").exists()


def test_cli_avalia_sessao_sem_juiz(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.benchmark.communication.fetch_session_data",
                        lambda sid: {"events": [], "models_by_role": {}})
    out = tmp_path / "out.json"
    assert comm_main(["evaluate", "s1", "--output-dir", str(tmp_path), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["session_id"] == "s1"
