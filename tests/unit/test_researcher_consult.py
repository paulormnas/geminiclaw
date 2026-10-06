"""Testes da mudança OpenSpec `v18-researcher-consult` (Researcher consultor em semi/auto).

O provedor LLM e as ferramentas de busca são simulados: nenhum teste usa rede, provedor pago ou
busca real. Cada teste cita o ``#### Scenario`` da spec que cobre.
"""

from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.researcher.consult import consult_tools, run_consult
from src import config as cfg
from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
from src.llm.base import LLMProvider, LLMResponse, ToolCall
from src.orchestrator import AgentTask, Orchestrator
from src.output_manager import OutputManager
from src.research_consult import DECISOES_RESERVADAS
from src.research_consult.query_guard import Ok, Recusa, check_query, protected_file_names
from src.skills.base import SkillResult
from src.skills.human_feedback.skill import HumanFeedbackSkill
from src.usage import UsageBudget, UsageTracker

SESSION = "sess_consult"


# --------------------------------------------------------------------------- dublês


def _final(payload: dict[str, Any], usage: dict | None = None) -> LLMResponse:
    return LLMResponse(text=json.dumps(payload), usage=usage or {"prompt_tokens": 10, "completion_tokens": 5})


def _answer(resposta: str = "Use stratify=y", confianca: str = "alta", **extra: Any) -> LLMResponse:
    return _final({"resposta": resposta, "confianca": confianca, "fontes": [], "suposicoes": [], **extra})


def _tool(name: str, **args: Any) -> ToolCall:
    return ToolCall(id=f"call_{name}_{len(args)}", name=name, arguments=args)


class ScriptedProvider(LLMProvider):
    """Provedor LLM simulado: devolve as respostas na ordem e registra as chamadas."""

    def __init__(self, responses: list[LLMResponse], delay: float = 0.0) -> None:
        self.responses = list(responses)
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        self.calls.append({"messages": list(messages), "tools": tools, "system": system})
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses.pop(0)

    async def generate_stream(self, messages, system=None):  # pragma: no cover - não usado
        yield ""

    async def health_check(self) -> bool:  # pragma: no cover - não usado
        return True

    @property
    def model_name(self) -> str:
        return "fake-researcher"


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def run(self, query: str, max_results: int = 5, **_: Any) -> SkillResult:
        self.queries.append(query)
        return SkillResult(success=True, output=[{"title": "Doc", "url": "https://docs.example.org/a"}],
                           metadata={"source": "ddg"})


class FakeReader:
    BODY = "CORPO_DA_PAGINA_LIDA"

    def __init__(self) -> None:
        self.urls: list[str] = []

    async def run(self, url: str, max_chars: int = 4000, **_: Any) -> SkillResult:
        self.urls.append(url)
        return SkillResult(success=True, output=self.BODY)


class FakeSessions:
    """SessionManager mínimo em memória (get/update)."""

    def __init__(self) -> None:
        self.payload: dict[str, Any] = {}

    def get(self, _key: str):
        return SimpleNamespace(payload=self.payload)

    def update(self, _key: str, payload: dict | None = None, **_: Any) -> None:
        if payload is not None:
            self.payload = payload


class Harness:
    """Orquestrador real com sessões, provedor e skills de busca simulados."""

    def __init__(self, tmp_path: Path, provider: ScriptedProvider, mode: str = "auto") -> None:
        self.sessions = FakeSessions()
        self.orch = Orchestrator(session_manager=self.sessions, output_manager=OutputManager(str(tmp_path)),
                                 agent_runtime=MagicMock())
        self.orch.consult_provider = provider
        self.orch.consult_search_skill = FakeSearch()
        self.orch.consult_reader_skill = FakeReader()
        self.provider = provider
        self.mode = mode
        self.events: list[dict[str, Any]] = []
        self.tmp_path = tmp_path

    def ctx(self, agent: str = "developer", task_name: str = "t1") -> AgentContext:
        task = AgentTask(agent_id=agent, prompt="p", task_name=task_name, mode=self.mode)

        async def consult(q, c, w, o, d):
            return await self.orch._consult_researcher_core(q, c, w, o, d, task, SESSION)

        return AgentContext(
            session_id=SESSION, agent_session_id="a1", agent_id=agent, mode=self.mode,
            output_dir=self.tmp_path / SESSION, model="m", task_name=task_name, execution_id=SESSION,
            consult_researcher=consult, ask_researcher=AsyncMock(return_value="resposta humana"),
        )

    async def ask(self, question: str = "Devo estratificar o split?", **kw: Any):
        bind_agent_context(self.ctx())
        return await HumanFeedbackSkill().run(question=question, why_cant_proceed="sem padrão", **kw)

    @property
    def interactions(self) -> list[dict[str, Any]]:
        return self.sessions.payload.get("researcher_interactions", [])


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    token = current_context.set(None)
    tel = MagicMock()
    monkeypatch.setattr("src.orchestrator.get_telemetry", lambda: tel)
    monkeypatch.setattr("src.llm.metering.get_telemetry", lambda: tel)
    yield tel
    current_context.reset(token)


@pytest.fixture
def telemetry(_isolate):
    return _isolate


def _make(tmp_path: Path, responses: list[LLMResponse], mode: str = "auto", delay: float = 0.0) -> Harness:
    return Harness(tmp_path, ScriptedProvider(responses, delay), mode)


# --------------------------------------------------------------------------- Requirement: respondem


@pytest.mark.unit
@pytest.mark.asyncio
class TestResearcherRespondeNosModosAutonomos:
    async def test_modo_auto(self, tmp_path: Path, monkeypatch) -> None:
        """Scenario: Modo auto."""
        monkeypatch.setattr(builtins, "input", MagicMock(side_effect=AssertionError("leu o terminal")))
        h = _make(tmp_path, [_answer()])
        result = await h.ask()
        assert result.success is True
        assert result.output.startswith("[Resposta do Researcher (consultor), confiança alta]")
        assert "Use stratify=y" in result.output
        assert h.interactions[0]["respondido_por"] == "researcher"

    async def test_modo_assisted(self, tmp_path: Path) -> None:
        """Scenario: Modo assisted."""
        h = _make(tmp_path, [], mode="assisted")
        ctx = h.ctx()
        bind_agent_context(ctx)
        result = await HumanFeedbackSkill().run(question="Onde está o dataset?", why_cant_proceed="x")
        assert result.output == "resposta humana"
        assert result.metadata["blocked"] is True
        ctx.ask_researcher.assert_awaited_once()
        assert h.provider.calls == []

    async def test_consultor_desligado(self, tmp_path: Path, monkeypatch) -> None:
        """Scenario: Consultor desligado."""
        monkeypatch.setattr(cfg, "RESEARCHER_CONSULT_ENABLED", False)
        h = _make(tmp_path, [], mode="semi")
        result = await h.ask()
        assert "suposição documentada" in result.output
        assert h.interactions[0]["respondido_por"] == "suposicao"
        assert h.interactions[0]["motivo_fallback"] == "desligado"
        assert h.provider.calls == []


# --------------------------------------------------------------------------- Requirement: ferramentas


@pytest.mark.unit
@pytest.mark.asyncio
class TestFerramentasRestritas:
    async def test_lista_de_ferramentas(self) -> None:
        """Scenario: Lista de ferramentas."""
        names = {t["function"]["name"] for t in consult_tools(web_enabled=True)}
        assert names == {"quick_search", "web_reader"}
        assert "ask_researcher" not in names

    async def test_lista_de_ferramentas_no_modelo(self, tmp_path: Path) -> None:
        """Scenario: Lista de ferramentas (o que o provedor realmente recebe)."""
        h = _make(tmp_path, [_answer()])
        await h.ask()
        sent = {t["function"]["name"] for t in h.provider.calls[0]["tools"]}
        assert sent == {"quick_search", "web_reader"}

    async def test_excesso_de_buscas(self, tmp_path: Path) -> None:
        """Scenario: Excesso de buscas."""
        calls = [_tool("quick_search", query=f"sklearn pipeline {w}") for w in "abcde"]
        provider = ScriptedProvider([LLMResponse(text=None, tool_calls=calls), _answer()])
        search = FakeSearch()
        out = await run_consult(provider, question="q", search_skill=search, reader_skill=FakeReader(),
                                max_searches=3)
        assert len(search.queries) == 3
        tool_msgs = [m["content"] for m in provider.calls[1]["messages"] if m.get("role") == "tool"]
        assert sum("limite de 3 buscas" in m for m in tool_msgs) == 2
        assert len(out.buscas_realizadas) == 3

    async def test_web_desligada(self, tmp_path: Path, monkeypatch) -> None:
        """Scenario: Web desligada."""
        monkeypatch.setattr(cfg, "RESEARCHER_CONSULT_WEB_ENABLED", False)
        assert consult_tools(web_enabled=False) == []
        h = _make(tmp_path, [_answer("Só do modelo")])
        result = await h.ask()
        assert not h.provider.calls[0]["tools"]
        assert "Só do modelo" in result.output
        assert h.orch.consult_search_skill.queries == []


# --------------------------------------------------------------------------- Requirement: guarda


async def _consult_with_search(query: str, search: FakeSearch, protected=()) -> Any:
    provider = ScriptedProvider([LLMResponse(text=None, tool_calls=[_tool("quick_search", query=query)]), _answer()])
    return await run_consult(provider, question="q", search_skill=search, reader_skill=FakeReader(),
                             protected_names=protected)


@pytest.mark.unit
@pytest.mark.asyncio
class TestGuardaDeConsulta:
    async def test_valor_de_medicao(self) -> None:
        """Scenario: Valor de medição."""
        search = FakeSearch()
        out = await _consult_with_search("acurácia 0,953 iris svm", search)
        assert search.queries == []
        assert out.recusas[0]["motivo"] == "numero_decimal"

    async def test_nome_de_arquivo_do_projeto(self, tmp_path: Path) -> None:
        """Scenario: Nome de arquivo do projeto."""
        snap = tmp_path / "input_snapshot"
        snap.mkdir()
        (snap / "medicoes_lote7.csv").write_text("x")
        names = protected_file_names(tmp_path)
        search = FakeSearch()
        out = await _consult_with_search("medicoes_lote7 formato", search, names)
        assert search.queries == []
        assert out.recusas[0]["motivo"] == "nome_de_arquivo"

    async def test_ano_permitido(self) -> None:
        """Scenario: Ano permitido."""
        search = FakeSearch()
        await _consult_with_search("scikit-learn train_test_split stratify 2026", search)
        assert search.queries == ["scikit-learn train_test_split stratify 2026"]

    async def test_url_com_dado(self) -> None:
        """Scenario: URL com dado."""
        reader = FakeReader()
        provider = ScriptedProvider(
            [LLMResponse(text=None, tool_calls=[_tool("web_reader", url="https://exemplo.org/q?v=12.75")]), _answer()]
        )
        out = await run_consult(provider, question="q", search_skill=FakeSearch(), reader_skill=reader)
        assert reader.urls == []
        assert out.recusas[0]["motivo"] == "numero_decimal"

    async def test_demais_regras_da_guarda(self) -> None:
        """Scenario: Valor de medição (regras restantes do design §4)."""
        assert isinstance(check_query("sklearn stratify"), Ok)
        assert check_query("id 123456 x") == Recusa("numero_longo", "sequência de 4 ou mais dígitos que não é ano")
        assert check_query("ano 1850").motivo == "numero_longo"
        assert check_query("a" * 121).motivo == "consulta_longa"
        assert check_query("a\nb\nc\nd").motivo == "formato"
        assert check_query("a\x00b").motivo == "formato"
        assert check_query("Medicoes_Lote7.CSV", ["medicoes_lote7.csv"]).motivo == "nome_de_arquivo"


# --------------------------------------------------------------------------- Requirement: reservadas


@pytest.mark.unit
@pytest.mark.asyncio
class TestDecisoesReservadas:
    async def test_lista_constante(self) -> None:
        """Scenario: Aprovação de oportunidade em modo auto (lista constante, design §5)."""
        assert set(DECISOES_RESERVADAS) == {
            "aprovar_oportunidade", "confirmar_problema", "aprovar_termo_vocabulario",
            "autorizar_escrita_instrumento", "ativar_modo_sem_limite",
        }

    async def test_aprovacao_de_oportunidade_em_modo_auto(self, tmp_path: Path) -> None:
        """Scenario: Aprovação de oportunidade em modo auto."""
        h = _make(tmp_path, [])
        result = await h.ask(decisao_reservada="aprovar_oportunidade")
        assert h.provider.calls == []
        assert h.interactions[0]["respondido_por"] == "pendente_pesquisador"
        assert "reservada ao pesquisador" in result.output.lower()

    async def test_classificacao_pelo_consultor(self, tmp_path: Path) -> None:
        """Scenario: Classificação pelo consultor."""
        h = _make(tmp_path, [_final({"reservada": True})])
        result = await h.ask("Posso aprovar esta oportunidade?")
        assert h.interactions[0]["respondido_por"] == "pendente_pesquisador"
        assert "reservada ao pesquisador" in result.output.lower()


# --------------------------------------------------------------------------- Requirement: registro


@pytest.mark.unit
@pytest.mark.asyncio
class TestRegistroAuditavel:
    async def test_consulta_com_busca(self, tmp_path: Path, telemetry) -> None:
        """Scenario: Consulta com busca."""
        h = _make(tmp_path, [
            LLMResponse(text=None, tool_calls=[
                _tool("quick_search", query="sklearn stratify docs"),
                _tool("quick_search", query="sklearn split docs"),
                _tool("web_reader", url="https://docs.example.org/a"),
            ]),
            _answer(),
        ])
        await h.ask()
        rec = h.interactions[0]
        assert rec["respondido_por"] == "researcher"
        assert len(rec["consulta"]["buscas_realizadas"]) == 2
        assert len(rec["consulta"]["leituras"]) == 1
        assert rec["agente"] == "developer" and rec["subtask_name"] == "t1"
        events = [c.kwargs for c in telemetry.record_agent_event.call_args_list
                  if c.kwargs["event_type"] == "researcher_consult"]
        assert len(events) == 1
        assert FakeReader.BODY not in json.dumps(events[0]["payload"], default=str)
        assert FakeReader.BODY not in json.dumps(rec, default=str)

    async def test_pergunta_repetida(self, tmp_path: Path) -> None:
        """Scenario: Pergunta repetida."""
        h = _make(tmp_path, [_answer("Primeira resposta")])
        first = await h.ask("Devo estratificar o split dos dados?")
        second = await h.ask("Devo estratificar o split dos dados ?")
        assert second.output == first.output
        assert len(h.provider.calls) == 1
        assert len(h.interactions) == 1


# --------------------------------------------------------------------------- Requirement: limites


@pytest.mark.unit
@pytest.mark.asyncio
class TestLimitesDeUso:
    async def test_tokens_contados(self, tmp_path: Path, telemetry) -> None:
        """Scenario: Tokens contados."""
        rows: list[dict[str, Any]] = []
        telemetry.record_token_usage.side_effect = lambda **kw: rows.append(kw)
        budget = UsageBudget(max_tokens=100_000, max_minutes=60, max_task_retries=3,
                             max_connection_retries=5, closing_reserve_pct=0.05)
        tracker = UsageTracker(budget, SESSION, token_reader=lambda: sum(
            r["prompt_tokens"] + r["completion_tokens"] for r in rows), connection_retry_reader=lambda: 0)
        h = _make(tmp_path, [_answer()])
        h.provider.responses[0].usage = {"prompt_tokens": 1000, "completion_tokens": 200}
        h.orch.register_usage_tracker(SESSION, tracker)
        before = tracker.check().tokens_used
        await h.ask()
        assert tracker.check().tokens_used - before == 1200
        assert rows[0]["execution_id"] == SESSION
        assert h.interactions[0]["consulta"]["tokens"] == 1200

    async def test_limite_por_sessao(self, tmp_path: Path, monkeypatch) -> None:
        """Scenario: Limite por sessão."""
        monkeypatch.setattr(cfg, "RESEARCHER_CONSULT_MAX_PER_SESSION", 1)
        h = _make(tmp_path, [_answer()])
        await h.ask("Devo estratificar o split?")
        result = await h.ask("Qual métrica de erro usar para regressão?")
        assert "suposição documentada" in result.output
        assert h.interactions[1]["motivo_fallback"] == "limite_consultas"
        assert h.interactions[1]["respondido_por"] == "suposicao"
        assert len(h.provider.calls) == 1

    async def test_orcamento_em_fechamento(self, tmp_path: Path) -> None:
        """Scenario: Orçamento em fechamento."""
        budget = UsageBudget(max_tokens=1000, max_minutes=60, max_task_retries=3,
                             max_connection_retries=5, closing_reserve_pct=0.05)
        tracker = UsageTracker(budget, SESSION, token_reader=lambda: 990, connection_retry_reader=lambda: 0)
        assert tracker.check().should_close
        h = _make(tmp_path, [])
        h.orch.register_usage_tracker(SESSION, tracker)
        await h.ask()
        assert h.provider.calls == []
        assert h.interactions[0]["motivo_fallback"] == "orcamento"

    async def test_timeout(self, tmp_path: Path, monkeypatch) -> None:
        """Scenario: Timeout."""
        monkeypatch.setattr(cfg, "RESEARCHER_CONSULT_TIMEOUT_SECONDS", 0.2)
        h = _make(tmp_path, [_answer()], delay=5)
        result = await h.ask()
        assert "suposição documentada" in result.output
        assert h.interactions[0]["motivo_fallback"] == "timeout"

    async def test_erro_do_consultor_vira_fallback(self, tmp_path: Path) -> None:
        """Scenario: Timeout (demais impedimentos: erro vira suposição documentada)."""
        h = _make(tmp_path, [LLMResponse(text="não é json")] * 3)
        result = await h.ask()
        assert "suposição documentada" in result.output
        assert h.interactions[0]["motivo_fallback"] == "erro"


# --------------------------------------------------------------------------- MODIFIED: semi


@pytest.mark.unit
@pytest.mark.asyncio
class TestSemiNaoLeTerminal:
    async def test_nenhuma_leitura_de_terminal_em_semi(self, tmp_path: Path, monkeypatch) -> None:
        """Scenario: Nenhuma leitura de terminal em semi."""
        monkeypatch.setattr(builtins, "input", MagicMock(side_effect=AssertionError("leu o terminal")))
        monkeypatch.setattr("sys.stdin", MagicMock(read=MagicMock(side_effect=AssertionError("stdin")),
                                                   readline=MagicMock(side_effect=AssertionError("stdin"))))
        h = _make(tmp_path, [_answer(), LLMResponse(text="lixo")], mode="semi")
        await h.ask("Devo estratificar o split dos dados?")
        await h.ask("Qual métrica de erro usar para regressão linear?")
        assert [i["respondido_por"] for i in h.interactions] == ["researcher", "suposicao"]
