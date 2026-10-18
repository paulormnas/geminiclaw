"""Comandos do pesquisador: codificação, aplicação na sessão e efeitos no laço (session-continuity 3.3 e 3.4)."""

import json

import pytest

import src.session.commands as cmd
from src.cli.session_process import apply_command
from src.orchestration import usage
from tests.support.exploration_world import LoopHarness, hyp, plan, task

pytestmark = [pytest.mark.unit, pytest.mark.timeout(60)]


def test_codifica_e_decodifica_ida_e_volta():
    assert json.loads(cmd.codifica("pausar")) == {"comando": "pausar"}
    assert cmd.decodifica(cmd.codifica("cancelar", "testar_svm")) == cmd.Comando("cancelar", "testar_svm")
    assert cmd.decodifica(cmd.codifica("replanejar")) == cmd.Comando("replanejar")


@pytest.mark.parametrize("bruto", [
    "não é json", "[]", '{"comando": "apagar_tudo"}', '{"comando": "cancelar"}', '{"comando": "cancelar", "subtarefa": ""}',
    '{"comando": "cancelar", "subtarefa": 3}', "", None,
])
def test_comando_invalido_ou_desconhecido_vira_none(bruto):
    assert cmd.decodifica(bruto) is None


def test_codifica_recusa_o_que_nao_e_comando():
    with pytest.raises(ValueError):
        cmd.codifica("apagar")
    with pytest.raises(ValueError):
        cmd.codifica("cancelar")


@pytest.fixture
def eventos(monkeypatch):
    registrados = []
    monkeypatch.setattr(
        "src.session.events.emit_event", lambda sid, tipo, campos=None, **kw: registrados.append((sid, tipo, campos))
    )
    return registrados


def test_pausar_parar_e_replanejar_acionam_os_sinalizadores(eventos):
    apply_command("s1", cmd.codifica("pausar"))
    apply_command("s1", cmd.codifica("replanejar"))
    assert usage.pause_requested() and usage.consume_replan() and not usage.consume_replan()
    assert not usage.interrupt_requested()
    apply_command("s1", cmd.codifica("parar"))
    assert usage.interrupt_requested()
    assert [(t, c["comando"], c["aceito"]) for _, t, c in eventos] == [
        ("comando_recebido", "pausar", True), ("comando_recebido", "replanejar", True),
        ("comando_recebido", "parar", True),
    ]


def test_cancelar_aceita_a_pendente_e_recusa_a_iniciada(eventos):
    usage.mark_task_started("treinar_rf")
    apply_command("s1", cmd.codifica("cancelar", "testar_svm"))
    apply_command("s1", cmd.codifica("cancelar", "treinar_rf"))
    assert usage.is_cancelled("testar_svm") and not usage.is_cancelled("treinar_rf")
    assert [(c["subtarefa"], c["aceito"]) for _, _, c in eventos] == [("testar_svm", True), ("treinar_rf", False)]


def test_comando_desconhecido_e_consumido_e_registrado_como_ignorado(eventos):
    apply_command("s1", '{"comando": "formatar_disco"}')
    apply_command("s1", "lixo")
    assert [(t, c) for _, t, c in eventos] == [
        ("comando_recebido", {"comando": "ignorado", "aceito": False}),
        ("comando_recebido", {"comando": "ignorado", "aceito": False}),
    ]
    assert not (usage.pause_requested() or usage.interrupt_requested() or usage.consume_replan())


def test_pausada_pesquisador_esta_nas_tabelas_de_motivos():
    from src.knowledge import schema
    from src.report.operation_metrics import describe_stop_reason
    from src.session.continuity import MOTIVOS_RETOMAVEIS
    from src.session.exit_codes import EXIT_AWAITING_RESEARCHER, exit_code_for

    assert "pausada_pesquisador" in schema.NODE_SCHEMAS["Sessao"].properties["motivo_parada"].enum
    assert "pausada_pesquisador" in MOTIVOS_RETOMAVEIS
    assert exit_code_for("pausada_pesquisador") == EXIT_AWAITING_RESEARCHER
    assert "pausada" in describe_stop_reason("pausada_pesquisador")
    assert usage.StopReason.PAUSED.value == "pausada_pesquisador"


# --- efeito no laço ----------------------------------------------------------------------------------------------


def _two_tasks():
    return plan([task("t1", "h1"), task("t2", "h1", depends_on=["t1"])], [hyp("h1")])


@pytest.mark.asyncio
async def test_pausar_termina_a_subtarefa_em_curso_e_fecha_como_suspended(tmp_path):
    """Scenario: Pausar — nenhuma outra começa, status suspended, motivo pausada_pesquisador."""
    h = LoopHarness(tmp_path, plans=[_two_tasks()])
    original = h.runtime.run

    async def run(task_, ctx):
        if task_.task_name == "t1":
            apply_command(h.w.sid, cmd.codifica("pausar"))
        return await original(task_, ctx)

    h.runtime.run = run
    await h.run()
    assert h.ran == ["t1"]
    assert h.stop_reason == "pausada_pesquisador"
    assert h.sm.get(h.w.sid).status == "suspended"
    assert "t1" in h.checkpoint().concluidas()


@pytest.mark.asyncio
async def test_cancelar_pendente_nao_executa_e_aparece_no_checkpoint(tmp_path):
    """Scenario: Cancelar subtarefa pendente; e recusa para a que já começou."""
    # O 2º plano só repete o que já foi concluído: a pesquisa fecha por falta de caminhos (senão o laço de exploração
    # replanejaria sem fim, porque a subtarefa cancelada continua no plano).
    h = LoopHarness(tmp_path, plans=[_two_tasks(), plan([task("t1", "h1")], [hyp("h1")])])
    original = h.runtime.run
    respostas = {}

    async def run(task_, ctx):
        if task_.task_name == "t1":
            respostas["pendente"] = usage.request_cancel("t2")
            respostas["em_curso"] = usage.request_cancel("t1")
        return await original(task_, ctx)

    h.runtime.run = run
    await h.run()
    assert respostas == {"pendente": True, "em_curso": False}
    assert "t2" not in h.ran and "t1" in h.ran
    estado = h.checkpoint().find("t2")
    assert estado is not None and estado.status == "abandonada" and estado.causa_falha == "cancelada_pesquisador"


@pytest.mark.asyncio
async def test_replanejar_pede_novo_replanejamento_ao_researcher(tmp_path):
    """Scenario: Replanejar — depois das subtarefas em curso o Researcher recebe o pedido."""
    h = LoopHarness(tmp_path, plans=[plan([task("t1", "h1")], [hyp("h1")]), plan([task("t1", "h1")], [hyp("h1")])])
    original = h.runtime.run

    async def run(task_, ctx):
        if task_.task_name == "t1":
            apply_command(h.w.sid, cmd.codifica("replanejar"))
        return await original(task_, ctx)

    h.runtime.run = run
    await h.run()
    assert any("pediu um replanejamento" in prompt for prompt in h.planner_prompts[1:])


def test_sessao_pausada_retoma_sem_pedir_confirmacao():
    """Scenario: ``retomar`` depois de ``pausar`` cria a sessão que a continua, sem perguntar."""
    from types import SimpleNamespace

    from src.session.continuity import RESUME_OK, evaluate_resumability

    checkpoint = SimpleNamespace(motivo_parada="pausada_pesquisador")
    assert evaluate_resumability("suspended", checkpoint, "pausada_pesquisador").decision == RESUME_OK
    assert evaluate_resumability("closed", checkpoint, "pausada_pesquisador").decision == RESUME_OK
