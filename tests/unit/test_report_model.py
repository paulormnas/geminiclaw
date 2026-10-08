"""Relatório a partir de dados estruturados (v16-pipeline-robustness §6)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentResult
from src.report.report_model import (
    NarrativeError,
    ReportMetadata,
    build_report_data,
    parse_narrative,
    render_report_markdown,
    unavailable_narrative,
)
from src.skills.code.sandbox import SandboxResult
from src.skills.code.skill import CodeSkill

pytestmark = pytest.mark.unit

SECTIONS = [
    "## Resumo Executivo", "## Contexto e Objetivo", "## Metodologia", "## Resultados",
    "## Análise das Divergências", "## Decisões do Pesquisador", "## Limitações Identificadas",
    "## Próximos Passos Sugeridos", "## Dados de Entrada e Marcações", "## Metadados de Execução",
]


def narrative_json(resumo="resumo"):
    return json.dumps({
        "resumo_executivo": resumo, "contexto_e_objetivo": "c", "metodologia": "m",
        "analise_divergencias": "a", "limitacoes": "l", "proximos_passos": "p",
        "confianca_nivel": "alto", "confianca_justificativa": "j",
    })


def metadata(**kw):
    base = dict(duration_s=12.0, tokens_in=100, tokens_out=50, cost_usd=0.0123,
                agent_runs={"developer": 5, "researcher": 2}, sandbox_runs=3,
                models_by_role={"developer": "google/gemini-3.8-flash"})
    base.update(kw)
    return ReportMetadata(**base)


def render(metrics=None, interactions=None, **kw):
    data = build_report_data(title="T", request="pedido", metrics_by_task=metrics or {},
                             metadata=metadata(), interactions=interactions, **kw)
    return data, render_report_markdown(data, parse_narrative(narrative_json()))


def test_tabela_de_resultados_com_valores_exatos_e_origem():
    """Scenario: Tabela de resultados."""
    _, md = render({"a": {"metrics": {"accuracy": 0.967}}, "b": {"metrics": {"accuracy": 0.953}}})
    assert "| a | accuracy | 0.967 |" in md and "a/metrics.json" in md
    assert "| b | accuracy | 0.953 |" in md


def test_divergencia_percentual_com_valor_esperado():
    data, _ = render({"a": {"metrics": {"accuracy": 0.9}, "expected": {"accuracy": 1.0}}})
    assert data.results[0].divergence_pct == -10.0


def test_metadados_de_execucao_sem_containers():
    """Scenario: Metadados de execução."""
    _, md = render()
    assert "developer: 5, researcher: 2" in md
    assert "**Execuções no sandbox**: 3" in md and "google/gemini-3.8-flash" in md
    assert "US$ 0.0123" in md and "100 de entrada, 50 de saída" in md
    assert "Containers" not in md


def test_secoes_fixas_na_ordem():
    """Scenario: Seções fixas."""
    _, md = render()
    positions = [md.index(s) for s in SECTIONS]
    assert positions == sorted(positions)


def test_sessao_sem_interacoes_declara_autonomia():
    """Scenario: Sessão sem interações com o pesquisador."""
    _, md = render(interactions=[])
    assert "totalmente autônoma" in md


def test_interacoes_aparecem_com_pergunta_e_resposta():
    _, md = render(interactions=[{"question": "Qual split?", "researcher_response": "80/20"}])
    assert "Qual split?" in md and "80/20" in md


def test_parse_narrative_invalida():
    with pytest.raises(NarrativeError):
        parse_narrative("texto solto")
    with pytest.raises(NarrativeError):
        parse_narrative(json.dumps({"resumo_executivo": "x"}))
    bad = json.loads(narrative_json())
    bad["confianca_nivel"] = "altíssimo"
    with pytest.raises(NarrativeError):
        parse_narrative(json.dumps(bad))


def test_narrativa_indisponivel_nao_inventa_texto():
    note = unavailable_narrative("erro x")
    assert "[narrativa indisponível: erro x]" in note.resumo_executivo


def _loop(tmp_path, responses):
    orch = MagicMock()
    orch.output_manager.base_dir = tmp_path
    orch.output_manager.list_artifacts.return_value = []
    orch.session_manager.get.return_value = None
    orch._execute_agent = AsyncMock(side_effect=[
        AgentResult(agent_id="summarizer", session_id="s", status="success", response={"text": t})
        for t in responses
    ])
    return AutonomousLoop(orch), orch


async def _synth(loop):
    results = [AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})]
    with patch("src.autonomous_loop.get_telemetry") as tel:
        tel.return_value.flush = AsyncMock()
        tel.return_value.get_token_summary.return_value = {"by_provider_model": [
            {"total_prompt_tokens": 10, "total_completion_tokens": 5, "total_cost_usd": 0.5}]}
        tel.return_value.get_derived_metrics.return_value = {"replans": 1}
        tel.return_value.get_event_counts.return_value = {
            "spawn": {"developer": 5}, "sandbox_run": {"developer": 3}}
        return await loop._synthesize_results("Treinar modelo", results, "sess")


@pytest.mark.asyncio
async def test_narrativa_invalida_duas_vezes_marca_indisponivel(tmp_path):
    """Scenario: Narrativa inválida."""
    loop, orch = _loop(tmp_path, ["não é json", "ainda não"])
    await _synth(loop)
    report = (tmp_path / "sess" / "relatorio_final.md").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "sess" / "report_data.json").read_text(encoding="utf-8"))
    assert "[narrativa indisponível:" in report and data["narrativa_indisponivel"] is True
    assert orch._execute_agent.await_count == 2


@pytest.mark.asyncio
async def test_reparo_da_narrativa_na_segunda_tentativa(tmp_path):
    """Scenario: Reparo da narrativa."""
    loop, orch = _loop(tmp_path, ["não é json", narrative_json("resumo reparado")])
    await _synth(loop)
    report = (tmp_path / "sess" / "relatorio_final.md").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "sess" / "report_data.json").read_text(encoding="utf-8"))
    assert "resumo reparado" in report and data["narrativa_indisponivel"] is False
    retry_prompt = orch._execute_agent.call_args.args[0].prompt
    assert "recusada" in retry_prompt


@pytest.mark.asyncio
async def test_metadados_do_relatorio_vem_da_telemetria(tmp_path):
    loop, _ = _loop(tmp_path, [narrative_json()])
    await _synth(loop)
    data = json.loads((tmp_path / "sess" / "report_data.json").read_text(encoding="utf-8"))
    meta = data["metadata"]
    assert meta["tokens_in"] == 10 and meta["tokens_out"] == 5 and meta["cost_usd"] == 0.5
    assert meta["agent_runs"] == {"developer": 5} and meta["sandbox_runs"] == 3 and meta["replans"] == 1


@pytest.mark.asyncio
async def test_summarizer_nao_recebe_ferramentas_e_o_prompt_traz_os_dados(tmp_path):
    loop, orch = _loop(tmp_path, [narrative_json()])
    await _synth(loop)
    task = orch._execute_agent.call_args.args[0]
    assert task.agent_id == "summarizer" and "CONTEXTO DO RELATÓRIO" in task.prompt
    # v18.5-numeric-references: o Summarizer recebe o catálogo de referências, não os números.
    assert "CATÁLOGO DE REFERÊNCIAS" in task.prompt


def test_sandbox_run_emite_evento_sem_o_conteudo_do_script():
    """Scenario: Execução com falha."""
    result = SandboxResult(stdout="", stderr="boom", exit_code=1)
    with patch("src.telemetry.get_telemetry") as tel:
        CodeSkill._record_sandbox_run("sess", "treinar", result, 250)
    kwargs = tel.return_value.record_agent_event.call_args.kwargs
    assert kwargs["event_type"] == "sandbox_run"
    assert kwargs["payload"] == {"task_name": "treinar", "exit_code": 1, "duration_ms": 250, "timed_out": False}


@pytest.mark.parametrize("fmt", ["html", "latex"])
def test_conversores_seguem_funcionando_sobre_o_markdown_novo(tmp_path, fmt):
    from src.report.base_converter import ReportConverterFactory

    _, md = render({"a": {"metrics": {"accuracy": 0.9}}})
    source = tmp_path / "relatorio_final.md"
    source.write_text(md, encoding="utf-8")
    out = tmp_path / f"relatorio_final.{'tex' if fmt == 'latex' else fmt}"
    ReportConverterFactory.create(fmt).convert(source, out)
    assert out.exists() and out.stat().st_size > 0
