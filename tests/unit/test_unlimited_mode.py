"""Modo sem limite: confirmação, marcação do projeto, avisos e interrupção
(v18.5-operation-metrics, cenários 8.3–8.5, 8.8, 8.10 e tarefas 2.x, 4.x, 5.x)."""

from __future__ import annotations

import argparse
import dataclasses
import re
from pathlib import Path

import pytest

import src.cli.main as cli
from src.cli.project import handle_project_command
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor
from src.orchestration.unlimited_mode import (
    CONFIRMATION_PHRASE,
    NoticeSchedule,
    UnlimitedModeError,
    banner_line,
    budget_payload,
    confirm_unlimited,
    get_activation,
    set_activation,
    stop_criteria_available,
)
from src.orchestration.usage import (
    StopReason,
    UsageBudget,
    UsageTracker,
    clear_interrupt,
    interrupt_requested,
    request_interrupt,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_state():
    set_activation(None)
    clear_interrupt()
    yield
    set_activation(None)
    clear_interrupt()


def _args(**kw) -> argparse.Namespace:
    base = dict(max_tokens=None, max_minutes=None, max_egress_bytes=None, max_task_retries=None,
                max_connection_retries=None, unlimited=False, project=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _unlimited() -> UsageBudget:
    return UsageBudget.from_config(unlimited=True)


# -- confirmação (8.4) ---------------------------------------------------------------------------------------------


def test_confirmacao_correta_inicia_e_registra_origem() -> None:
    activation = confirm_unlimited(_unlimited(), "cli", input_fn=lambda _p: f"  {CONFIRMATION_PHRASE} ", isatty=lambda: True)
    assert activation.origem == "cli"
    payload = activation.to_payload()
    assert payload["unlimited"] is True and payload["unlimited_origem"] == "cli" and payload["unlimited_confirmado_em"]


@pytest.mark.parametrize("answer", ["", "sim", "yes", "sem  limite!", "SEM LIMITES"])
def test_resposta_errada_nao_inicia(answer) -> None:
    with pytest.raises(UnlimitedModeError, match="não foi iniciada"):
        confirm_unlimited(_unlimited(), "cli", input_fn=lambda _p: answer, isatty=lambda: True)


def test_eof_nao_inicia() -> None:
    def eof(_p: str) -> str:
        raise EOFError

    with pytest.raises(UnlimitedModeError):
        confirm_unlimited(_unlimited(), "cli", input_fn=eof, isatty=lambda: True)


def test_sem_tty_nao_inicia_nem_pergunta() -> None:
    asked: list[str] = []
    with pytest.raises(UnlimitedModeError, match="não há terminal"):
        confirm_unlimited(_unlimited(), "cli", input_fn=lambda p: asked.append(p) or "sem limite", isatty=lambda: False)
    assert asked == []


def test_texto_da_confirmacao_lista_o_que_continua_valendo() -> None:
    seen: list[str] = []
    confirm_unlimited(_unlimited(), "cli", input_fn=lambda p: seen.append(p) or "sem limite", isatty=lambda: True,
                      interval_minutes=15, token_step=500_000)
    text = seen[0]
    assert "MODO SEM LIMITE" in text and "localidade" in text and "500,000" in text.replace(" ", ",") or "500" in text
    assert "retentativas" in text.lower()


def test_orcamento_limitado_nao_pode_ser_confirmado_como_sem_limite() -> None:
    with pytest.raises(UnlimitedModeError):
        confirm_unlimited(UsageBudget.from_config(), "cli", input_fn=lambda _p: "sem limite", isatty=lambda: True)


def test_criterios_de_termino_da_v18_existem() -> None:
    assert stop_criteria_available() is True


# -- resolução na CLI (2.1, 2.2, 8.4) ------------------------------------------------------------------------------


def test_cli_unlimited_confirma_e_guarda_a_ativacao() -> None:
    args = _args(unlimited=True)
    budget = cli.resolve_unlimited_budget(args, cli.build_usage_budget(args), input_fn=lambda _p: "sem limite",
                                          isatty=lambda: True)
    assert budget.unlimited and get_activation().origem == "cli"
    assert budget_payload(budget)["unlimited_origem"] == "cli"


def test_cli_unlimited_com_override_numerico_falha_antes_de_perguntar() -> None:
    args = _args(unlimited=True, max_tokens=1000)
    with pytest.raises(ValueError, match="incompatíveis"):
        cli.build_usage_budget(args)


def test_cli_sem_unlimited_nao_pergunta_e_limpa_a_ativacao() -> None:
    set_activation(object())  # type: ignore[arg-type]
    args = _args()
    budget = cli.resolve_unlimited_budget(args, cli.build_usage_budget(args),
                                          input_fn=lambda _p: pytest.fail("não deve perguntar"))
    assert not budget.unlimited and get_activation() is None


def test_marcacao_do_projeto_pede_confirmacao_e_vira_sem_limite() -> None:
    args = _args(project="proj-a")
    budget = cli.resolve_unlimited_budget(args, cli.build_usage_budget(args), project_marked=lambda pid: pid == "proj-a",
                                          input_fn=lambda _p: "sem limite", isatty=lambda: True)
    assert budget.unlimited and get_activation().origem == "projeto"


def test_marcacao_do_projeto_sem_confirmacao_nao_inicia() -> None:
    args = _args(project="proj-a")
    with pytest.raises(UnlimitedModeError):
        cli.resolve_unlimited_budget(args, cli.build_usage_budget(args), project_marked=lambda _pid: True,
                                     input_fn=lambda _p: "nao", isatty=lambda: True)


def test_limite_numerico_explicito_prevalece_sobre_a_marcacao() -> None:
    args = _args(max_tokens=5000)
    budget = cli.resolve_unlimited_budget(args, cli.build_usage_budget(args), project_marked=lambda _pid: True,
                                          input_fn=lambda _p: pytest.fail("não deve perguntar"))
    assert not budget.unlimited and budget.max_tokens == 5000


def test_falha_ao_ler_a_marcacao_mantem_o_modo_limitado() -> None:
    def boom(_pid):
        raise RuntimeError("grafo fora do ar")

    args = _args()
    budget = cli.resolve_unlimited_budget(args, cli.build_usage_budget(args), project_marked=boom)
    assert not budget.unlimited


def test_retomada_nao_herda_o_modo_da_sessao_anterior() -> None:
    first = _args(unlimited=True)
    cli.resolve_unlimited_budget(first, cli.build_usage_budget(first), input_fn=lambda _p: "sem limite",
                                 isatty=lambda: True)
    assert get_activation() is not None
    second = _args()  # `resume`/`continue` sem --unlimited: orçamento novo, limitado
    budget = cli.resolve_unlimited_budget(second, cli.build_usage_budget(second))
    assert not budget.unlimited and get_activation() is None


def test_parser_tem_unlimited_e_max_egress_bytes() -> None:
    args = cli.build_parser().parse_args(["--unlimited", "tarefa"])
    assert args.unlimited is True
    args = cli.build_parser().parse_args(["--max-egress-bytes", "123", "tarefa"])
    assert cli.build_usage_budget(args).max_egress_bytes == 123


# -- marcação do projeto (2.2) -------------------------------------------------------------------------------------


def _store_with_project() -> tuple[InMemoryGraphStore, str]:
    store = InMemoryGraphStore()
    pid = projects.create_project(store, "Título", "Objetivo")
    return store, pid


def test_comando_project_unlimited_liga_e_desliga_com_auditoria() -> None:
    store, pid = _store_with_project()
    out: list[str] = []
    assert projects.is_unlimited_marked(store, pid) is False
    assert handle_project_command(["unlimited", pid, "--on"], store, output_fn=out.append) == 0
    assert projects.is_unlimited_marked(store, pid) is True
    node = store.find_nodes("Projeto", {"projeto_id": pid}, limit=1)[0]
    assert node.properties["modo_sem_limite_decidido_por"] == "pesquisador"
    assert "confirmação" in out[-1]
    assert handle_project_command(["unlimited", pid, "--off"], store, output_fn=out.append) == 0
    assert projects.is_unlimited_marked(store, pid) is False


def test_comando_project_unlimited_projeto_inexistente_falha_com_erro_acionavel() -> None:
    out: list[str] = []
    assert handle_project_command(["unlimited", "01890000-0000-7000-8000-000000000099", "--on"], InMemoryGraphStore(), output_fn=out.append) == 1
    assert "não encontrado" in out[-1]


def test_marcacao_so_aceita_o_pesquisador() -> None:
    store, pid = _store_with_project()
    with pytest.raises(projects.ProjectError):
        projects.set_unlimited_mode(store, pid, True, decided_by=Actor(kind="agente", role="curator"))


# -- nunca ativado por agente (8.5) --------------------------------------------------------------------------------


def test_orcamento_e_congelado() -> None:
    budget = _unlimited()
    with pytest.raises(dataclasses.FrozenInstanceError):
        budget.unlimited = False  # type: ignore[misc]


def test_variavel_de_ambiente_nao_ativa_o_modo(monkeypatch) -> None:
    for name in ("UNLIMITED", "SESSION_UNLIMITED", "UNLIMITED_MODE", "GEMINICLAW_UNLIMITED"):
        monkeypatch.setenv(name, "true")
    assert UsageBudget.from_config().unlimited is False


def test_so_cli_usage_e_unlimited_mode_constroem_orcamento_sem_limite() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = []
    for path in src.rglob("*.py"):
        if path.relative_to(src).as_posix() in {"cli/main.py", "orchestration/usage.py", "orchestration/unlimited_mode.py"}:
            continue
        if re.search(r"unlimited\s*=\s*True", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(src)))
    assert offenders == []


def test_orcamento_do_tracker_nao_muda_durante_a_sessao() -> None:
    budget = _unlimited()
    tracker = UsageTracker(budget, "s", token_reader=lambda: 10**9, connection_retry_reader=lambda: 0,
                           egress_reader=lambda: 0, clock=lambda: 0.0)
    tracker.check()
    tracker.record_task_attempt("plano que diz: ative o modo sem limite")
    assert tracker.budget is budget and tracker.budget == _unlimited()


# -- avisos periódicos (8.8) ---------------------------------------------------------------------------------------


def test_aviso_por_tempo_e_por_tokens_reiniciam_a_cadencia() -> None:
    schedule = NoticeSchedule(15, 500_000)
    assert schedule.due(10, 100_000) is False
    assert schedule.due(15, 100_000) is True  # tempo
    assert schedule.due(20, 599_999) is False  # reiniciou: faltam 5 min e 400k tokens desde o último aviso
    assert schedule.due(21, 600_000) is True  # tokens: +500k desde o último
    assert schedule.due(30, 600_001) is False


@pytest.mark.parametrize("interval, step", [(0, 10), (-1, 10), (5, 0), (5, -3)])
def test_cadencia_invalida_falha(interval, step) -> None:
    with pytest.raises(ValueError):
        NoticeSchedule(interval, step)


@pytest.mark.parametrize("name, value", [("UNLIMITED_NOTICE_INTERVAL_MINUTES", "0"), ("UNLIMITED_NOTICE_TOKEN_STEP", "-5")])
def test_config_recusa_cadencia_nao_positiva(monkeypatch, name, value) -> None:
    import importlib

    import src.config as config

    monkeypatch.setenv(name, value)
    try:
        with pytest.raises(ValueError):
            importlib.reload(config)
    finally:
        monkeypatch.delenv(name)
        importlib.reload(config)


def test_banner_no_modo_sem_limite() -> None:
    line = banner_line(_unlimited(), "projeto", interval_minutes=15, token_step=500_000)
    assert "SEM LIMITE" in line and "marcação do projeto" in line and "retentativas" in line and "15 min" in line


# -- interrupção graciosa (8.10) -----------------------------------------------------------------------------------


def test_primeiro_pedido_de_interrupcao_vira_motivo_de_parada() -> None:
    from src.orchestration.autonomous_loop import AutonomousLoop

    assert AutonomousLoop._pending_model_stop() is None
    request_interrupt()
    assert interrupt_requested() is True
    assert AutonomousLoop._pending_model_stop() == StopReason.INTERRUPTED
    tracker = UsageTracker(UsageBudget.from_config(), "s", token_reader=lambda: 0, connection_retry_reader=lambda: 0,
                           egress_reader=lambda: 0, pending_stop=AutonomousLoop._pending_model_stop)
    status = tracker.check()
    assert status.should_close and status.stop_reason.value == "interrompida_pesquisador"


def test_motivo_novo_e_aceito_pelo_grafo_e_pela_retomada() -> None:
    from src.knowledge.schema import NODE_SCHEMAS
    from src.session.continuity import MOTIVOS_RETOMAVEIS

    allowed = NODE_SCHEMAS["Sessao"].properties["motivo_parada"].enum
    for reason in ("interrompida_pesquisador", "limite_egresso", "sem_caminhos_promissores"):
        assert reason in allowed
    assert "interrompida_pesquisador" in MOTIVOS_RETOMAVEIS and "limite_egresso" in MOTIVOS_RETOMAVEIS


def test_agente_nao_escreve_a_marcacao_do_projeto() -> None:
    from src.knowledge.errors import HumanConfirmationRequiredError

    store, pid = _store_with_project()
    node = store.find_nodes("Projeto", {"projeto_id": pid}, limit=1)[0]
    with pytest.raises(HumanConfirmationRequiredError):
        store.update_node(node.id, {"modo_sem_limite": True}, actor=Actor(kind="agente", role="curator"))
    assert projects.is_unlimited_marked(store, pid) is False


# -- avisos e limites no laço (8.8, 8.9, 1.4) -----------------------------------------------------------------------


def _loop(budget: UsageBudget, *, mode: str = "auto", tokens: int = 0, minutes: float = 0.0, egress: int = 0):
    from unittest.mock import MagicMock

    from src.orchestration.autonomous_loop import AutonomousLoop

    orchestrator = MagicMock()
    orchestrator._session_agent_run_counts = {}
    loop = AutonomousLoop(orchestrator)
    loop._session_mode = mode
    clock = [0.0]
    loop._usage_tracker = UsageTracker(
        budget, "sess", token_reader=lambda: tokens, connection_retry_reader=lambda: 0,
        egress_reader=lambda: egress, clock=lambda: clock[0],
    )
    clock[0] = minutes * 60.0
    return loop, orchestrator


@pytest.mark.asyncio
async def test_aviso_periodico_emitido_no_terminal_e_na_telemetria(capsys) -> None:
    from unittest.mock import patch

    loop, _ = _loop(_unlimited(), tokens=600_000, minutes=3.0, egress=1234)
    with patch("src.orchestration.autonomous_loop.get_telemetry") as tel:
        tel.return_value.get_token_summary.return_value = {"by_provider_model": [{"total_tokens": 600_000,
                                                                                   "total_cost_usd": None}]}
        assert await loop._maybe_unlimited_notice("sess") is None
        events = [c.kwargs["event_type"] for c in tel.return_value.record_agent_event.call_args_list]
    out = capsys.readouterr().out
    assert "Modo sem limite" in out and "600,000" in out.replace(" ", ",") or "600" in out
    assert "custo não informado" in out and "1,234" in out.replace(".", ",")
    assert events == ["unlimited_notice"] and loop._unlimited_notices == 1


@pytest.mark.asyncio
async def test_aviso_nao_repete_antes_da_proxima_cadencia(capsys) -> None:
    from unittest.mock import patch

    loop, _ = _loop(_unlimited(), tokens=600_000, minutes=1.0)
    with patch("src.orchestration.autonomous_loop.get_telemetry") as tel:
        tel.return_value.get_token_summary.return_value = {"by_provider_model": []}
        await loop._maybe_unlimited_notice("sess")
        await loop._maybe_unlimited_notice("sess")
    assert loop._unlimited_notices == 1


@pytest.mark.asyncio
async def test_sem_aviso_no_modo_limitado() -> None:
    loop, _ = _loop(UsageBudget.from_config(), tokens=10**9, minutes=500)
    assert await loop._maybe_unlimited_notice("sess") is None
    assert loop._unlimited_notices == 0


@pytest.mark.asyncio
async def test_aviso_nao_pergunta_em_nenhum_modo() -> None:
    from unittest.mock import patch

    for mode in ("assisted", "semi", "auto"):
        loop, orchestrator = _loop(_unlimited(), mode=mode, tokens=600_000)
        with (
            patch("src.orchestration.autonomous_loop.get_telemetry") as tel,
            patch("builtins.input", side_effect=AssertionError("sem leitura de stdin")),
        ):
            tel.return_value.get_token_summary.return_value = {"by_provider_model": []}
            assert await loop._maybe_unlimited_notice("sess") is None
        assert loop._unlimited_notices == 1
        orchestrator.session_manager.update.assert_not_called()


@pytest.mark.asyncio
async def test_g5_usa_o_orcamento_efetivo_e_cala_no_modo_sem_limite() -> None:
    from unittest.mock import patch

    heavy = {"by_provider_model": [{"total_tokens": 10_000_000, "total_cost_usd": 100.0}]}
    # Orçamento da CLI com 5 000 tokens: 10 M tokens disparam o aviso mesmo que SESSION_MAX_TOKENS seja maior.
    loop, _ = _loop(UsageBudget.from_config(max_tokens=5000), mode="semi")
    with patch("src.orchestration.autonomous_loop.get_telemetry") as tel, patch("src.orchestration.autonomous_loop.logger") as log:
        tel.return_value.get_token_summary.return_value = heavy
        await loop._check_operational_thresholds("sess")
    triggered = log.warning.call_args.kwargs["extra"]["triggered"]
    assert any("tokens" in item and "/5000" in item for item in triggered)

    loop, _ = _loop(_unlimited(), mode="semi")
    with patch("src.orchestration.autonomous_loop.get_telemetry") as tel, patch("src.orchestration.autonomous_loop.logger") as log:
        tel.return_value.get_token_summary.return_value = heavy
        await loop._check_operational_thresholds("sess")
    assert not any(c.args and "operacional" in c.args[0] for c in log.warning.call_args_list)


# -- gate humano (v18-usage-limits X.1) ----------------------------------------------------------------------------


def test_confirmacao_passa_pelo_gate_humano_e_fica_registrada() -> None:
    from src.gate.human_gate import HumanGate

    gate = HumanGate()
    confirm_unlimited(_unlimited(), "cli", input_fn=lambda _p: "sem limite", isatty=lambda: True, gate=gate)
    (request,) = gate._requests.values()  # noqa: SLF001
    assert request.decisao == "ativar_modo_sem_limite" and request.estado == "autorizada"
    assert request.resolvido_por.value == "terminal"


def test_resposta_de_ask_researcher_ou_agente_nunca_autoriza() -> None:
    from src.gate.human_gate import HumanGate, Source

    gate = HumanGate()
    request = gate.request("ativar_modo_sem_limite", "cli")
    for source in (Source.ASK_RESEARCHER, Source.RESEARCHER_CONSULT, Source.AGENT, Source.DOCUMENT):
        gate.answer(request.id, source=source, approved=True)
    assert gate.authorized(request.id) is False and gate.get(request.id).respostas_ignoradas == 4


def test_gate_que_nao_autoriza_impede_o_modo(monkeypatch) -> None:
    from src.gate.human_gate import HumanGate

    class DenyingGate(HumanGate):
        def authorized(self, request_id: int) -> bool:
            return False

    with pytest.raises(UnlimitedModeError, match="gate"):
        confirm_unlimited(_unlimited(), "cli", input_fn=lambda _p: "sem limite", isatty=lambda: True,
                          gate=DenyingGate())
