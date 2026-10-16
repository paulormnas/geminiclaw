"""Ciclo de correção ponta a ponta em ``AutonomousLoop._finalize_report`` (spec: ciclos de correção do relatório)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import config
from src.claims.runtime import ClaimRuntime
from src.claims.store import ClaimStore
from src.llm.base import LLMResponse
from src.orchestration.autonomous_loop import AutonomousLoop
from tests.unit.claims.helpers import FakeVerifier, evidence_for

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

SOURCE = (
    "# Relatório\n\n## Resultados\n\nO modelo melhora em tudo e piora em nada.\n\n"
    "Outra conclusão que não precisa de correção alguma.\n"
)


def verifier_pedindo_correcao():
    state = {"n": 0}

    def responder(frases, itens):
        state["n"] += 1
        if "melhora em tudo" in frases[0]:
            return [{"texto": "o modelo melhora em tudo", "frase": 1, "status": "parcial", "evidencias": ["ev1"],
                     "parte_nao_suportada": "piora em nada"}]
        if "Outra conclusão" in frases[0]:
            return [{"texto": "outra", "frase": 1, "status": "suportada", "evidencias": ["ev1"]}]
        return [{"texto": "o modelo melhora em parte", "frase": 1, "status": "suportada", "evidencias": ["ev1"]}]

    return FakeVerifier(responder)


def build_loop(tmp_path, fake):
    orchestrator = MagicMock()
    orchestrator.output_manager.base_dir = tmp_path
    orchestrator._resumes = {}
    runtime = ClaimRuntime(tmp_path, graph_getter=lambda: (_ for _ in ()).throw(RuntimeError("sem grafo")),
                           tracker_getter=lambda sid: None, validator=fake)
    orchestrator.claim_runtime.return_value = runtime
    return AutonomousLoop(orchestrator), runtime


async def finalize(loop, tmp_path, summarizer_text):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=summarizer_text))
    session_dir = tmp_path / "s1"
    with patch("src.orchestration.autonomous_loop.ModelRouter.get_provider", return_value=provider), \
         patch("src.report.claims_report.report_evidence_builder", lambda *a, **k: evidence_for("res:e1/acuracia")), \
         patch("src.llm.metering.record_llm_call"), \
         patch("src.provenance.ledger.get_ledger", return_value=MagicMock()), \
         patch.object(AutonomousLoop, "_graph_for_report", return_value=None), \
         patch.object(AutonomousLoop, "_report_counts", return_value={}):
        text = await loop._finalize_report(SOURCE, "s1", session_dir)
    return text, provider


async def test_conclusao_parcial_volta_ao_summarizer_e_e_reverificada(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLAIM_REVISION_MAX_CYCLES", 1)
    monkeypatch.setattr(config, "CLAIM_VERIFY_SECTIONS", ("Resultados",))
    fake = verifier_pedindo_correcao()
    loop, _ = build_loop(tmp_path, fake)
    revision = json.dumps({"conclusoes": [
        {"conclusao_id": "rel:resultados:1", "texto": "O modelo melhora em parte dos casos."}
    ]})
    text, provider = await finalize(loop, tmp_path, revision)
    assert provider.generate.await_count == 1                       # uma chamada ao Summarizer por ciclo
    assert "O modelo melhora em parte dos casos." in text           # texto novo no relatório
    assert "melhora em tudo e piora em nada" not in text.split("<!-- claims:begin -->")[0]
    assert "### Afirmações revisadas" in text and "melhora em tudo" in text
    store = ClaimStore.load(tmp_path / "s1", "s1")
    entry = store.conclusoes["rel:resultados:1"]
    assert entry["ciclos"] == 1 and entry["aprovada"] is True
    old = [c for c in store.afirmacoes if c.substituida_por]
    assert len(old) == 1 and old[0].status_afirmacao == "parcial"
    assert (tmp_path / "s1" / "relatorio_final.fonte.md").read_text(encoding="utf-8").count("melhora em parte") == 1
    # a conclusão que já estava suportada não foi reverificada
    assert sum(1 for c in fake.calls if "Outra conclusão" in c["frases"][0]) == 1


async def test_ciclos_zero_desliga_a_correcao(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLAIM_REVISION_MAX_CYCLES", 0)
    monkeypatch.setattr(config, "CLAIM_VERIFY_SECTIONS", ("Resultados",))
    loop, _ = build_loop(tmp_path, verifier_pedindo_correcao())
    text, provider = await finalize(loop, tmp_path, "{}")
    assert provider.generate.await_count == 0
    assert "[A1 · parcial]" in text and "melhora em tudo e piora em nada." in text


async def test_summarizer_com_resposta_invalida_mantem_o_relatorio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLAIM_REVISION_MAX_CYCLES", 1)
    monkeypatch.setattr(config, "CLAIM_VERIFY_SECTIONS", ("Resultados",))
    loop, _ = build_loop(tmp_path, verifier_pedindo_correcao())
    text, provider = await finalize(loop, tmp_path, "isto não é JSON")
    assert provider.generate.await_count == 1
    assert "[A1 · parcial]" in text


async def test_verificacao_desligada_nao_acrescenta_a_secao(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CLAIM_VERIFY_ENABLED", False)
    loop, _ = build_loop(tmp_path, verifier_pedindo_correcao())
    text, _ = await finalize(loop, tmp_path, "{}")
    assert "claims:begin" not in text
