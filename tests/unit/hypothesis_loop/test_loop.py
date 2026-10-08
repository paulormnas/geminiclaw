"""Ciclo de exploração ativa no laço autônomo (v18-hypothesis-loop §1, §4 e §8; cenários 6.1, 6.2, 6.6, 6.7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.exploration import ExplorationSession
from src.knowledge.hypothesis_cycle import ApprovalDecision, SolutionStatus
from src.knowledge.suggestions import SuggestionError
from tests.support.exploration_world import APPROVED, REJECTED, LoopHarness, hyp, plan, task

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _defaults():
    with patch("src.config.CURATOR_ENABLED", False):
        yield


def _hyp_status(h: LoopHarness, enunciado_part: str) -> str:
    (node,) = [n for n in h.hypotheses() if enunciado_part in n.properties["enunciado"]]
    return node.properties["status"]


@pytest.mark.asyncio
async def test_sem_caminhos_promissores_apos_executar_e_nao_ter_nada_novo(tmp_path):
    """Scenario: Sem caminhos — sem hipótese nova, nem aprovada pendente, nem sugestão: fecha com checkpoint."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first])
    result = await h.run()
    assert h.ran == ["t1"]  # a concluída não é reexecutada no segundo ciclo
    assert h.stop_reason == "sem_caminhos_promissores"
    cp = h.checkpoint()
    assert cp.estado == "fechado" and cp.motivo_parada == "sem_caminhos_promissores"
    assert result.succeeded == result.total == 1
    (sessao,) = h.w.raw.find_nodes("Sessao", {"sessao_id": h.w.sid}, limit=2)
    assert sessao.properties["motivo_parada"] == "sem_caminhos_promissores"
    assert _hyp_status(h, "Hipótese h1") == "em_teste"


@pytest.mark.asyncio
async def test_plano_replanejado_executa_so_o_novo(tmp_path):
    h = LoopHarness(tmp_path, plans=[
        plan([task("t1")], [hyp("h1")]),
        plan([task("t1"), task("t2", "h2", depends_on=["t1"])], [hyp("h2")]),
        plan([task("t1"), task("t2", "h2", depends_on=["t1"])]),
    ])
    await h.run()
    assert h.ran == ["t1", "t2"] and h.stop_reason == "sem_caminhos_promissores"
    assert "MODO: REPLAN" in h.planner_prompts[1] and "EXPLORAÇÃO" in h.planner_prompts[1]


@pytest.mark.asyncio
async def test_modo_autonomo_executa_as_duas_hipoteses_de_maior_prioridade(tmp_path):
    """Scenario: Modo autônomo — 4 propostas e HYPOTHESES_PER_CYCLE=2: só 2 executam no ciclo."""
    hips = [hyp(f"h{i}", custo_estimado=c) for i, c in enumerate(["alto", "baixo", "medio", "baixo"])]
    tasks = [task(f"t{i}", f"h{i}") for i in range(4)]
    h = LoopHarness(tmp_path, plans=[plan(tasks, hips), plan([task("t1", "h1"), task("t3", "h3")])])
    await h.run()
    assert sorted(h.ran) == ["t1", "t3"]  # os de custo baixo; o de custo alto fica de fora do ciclo
    statuses = sorted(n.properties["status"] for n in h.hypotheses())
    assert statuses == ["em_teste", "em_teste", "proposta", "proposta"]


@pytest.mark.asyncio
async def test_modo_assistido_sem_aprovacao_a_hipotese_do_researcher_nao_executa(tmp_path):
    """Scenario: Modo assistido — sem aprovação nada executa e a sessão fica suspensa (retomável)."""
    approver = lambda items: {}  # noqa: E731 - o pesquisador não respondeu
    h = LoopHarness(tmp_path, mode="assisted", plans=[plan([task("t1")], [hyp("h1")])], approver=approver)
    await h.run()
    assert h.ran == []
    assert h.sm.get(h.w.sid).status in ("suspended", "closed") and h.stop_reason == "interrompida"
    assert _hyp_status(h, "Hipótese h1") == "proposta"
    assert h.checkpoint().estado == "interrompido"


@pytest.mark.asyncio
async def test_modo_assistido_aprovada_executa_e_rejeitada_fica_abandonada(tmp_path):
    items_seen: list = []

    def approver(items):
        items_seen.extend(i.id for i in items)
        by_text = {i.enunciado: i.id for i in items}
        ok = next(v for k, v in by_text.items() if "aprovada" in k)
        no = next(v for k, v in by_text.items() if "rejeitada" in k)
        return {ok: ApprovalDecision("aprovar"), no: ApprovalDecision("rejeitar", motivo="sem relevância")}

    plans = [plan([task("t1", "h1"), task("t2", "h2")],
                  [hyp("h1", "Hipótese aprovada pelo pesquisador"), hyp("h2", "Hipótese rejeitada pelo pesquisador")])]
    h = LoopHarness(tmp_path, mode="assisted", plans=plans + [plans[0]], approver=approver)
    await h.run()
    assert h.ran == ["t1"] and len(items_seen) == 2  # lote único com as duas
    assert _hyp_status(h, "aprovada") == "em_teste" and _hyp_status(h, "rejeitada") == "abandonada"


@pytest.mark.asyncio
async def test_modo_assistido_hipotese_do_pesquisador_executa_sem_aprovacao(tmp_path):
    """Scenario: Modo assistido — hipótese do pesquisador executa sem passar pelo aprovador."""
    h = LoopHarness(tmp_path, mode="assisted", approver=lambda items: pytest.fail("não deve pedir aprovação"))
    mine = h.w.hypothesis("Minha hipótese", origem="pesquisador", status="proposta")
    first = plan([task("t1", mine)], [{"ref": "m", "id": mine}])
    h.plans = [first, first]
    await h.run()
    assert h.ran == ["t1"]


@pytest.mark.asyncio
async def test_plano_no_formato_antigo_continua_funcionando(tmp_path):
    """Scenario: Plano no formato antigo — lista simples executa; o texto de hipótese vira hipótese formal governada."""
    first = task("t1", None, hypothesis="O modelo atinge R2 de 0,85", scientific_rationale="porque sim")
    old = [first, task("t2", None)]
    h = LoopHarness(tmp_path, plans=[old, old])
    await h.run()
    assert h.ran == ["t1", "t2"] and h.stop_reason == "sem_caminhos_promissores"
    (node,) = h.hypotheses()
    assert node.properties["origem"] == "researcher" and node.properties["enunciado"] == "O modelo atinge R2 de 0,85"


@pytest.mark.asyncio
async def test_formato_antigo_no_assistido_tambem_exige_aprovacao_da_hipotese(tmp_path):
    old = [task("t1", None, hypothesis="O modelo atinge R2 de 0,85")]
    h = LoopHarness(tmp_path, mode="assisted", plans=[old], approver=lambda items: {})
    await h.run()
    assert h.ran == [] and h.stop_reason == "interrompida"


@pytest.mark.asyncio
async def test_subtarefa_experimental_sem_hipotese_no_formato_novo_nao_executa(tmp_path):
    """Governança não pode ser contornada por omissão do hypothesis_ref; preparação (eda) segue."""
    p = plan([task("sem_ref", None), task("eda_dados", None, task_type="eda"), task("ok", "h1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[p, p])
    await h.run()
    assert sorted(h.ran) == ["eda_dados", "ok"]


@pytest.mark.asyncio
async def test_dependente_de_subtarefa_retirada_tambem_e_retirada(tmp_path):
    hips = [hyp("h1", "Hipótese um"), hyp("h2", "Hipótese dois"), hyp("h3", "Hipótese três")]
    p = plan([task("a", "h1"), task("b", "h2"), task("c", "h3"), task("d", None, task_type="eda", depends_on=["c"])],
             hips)
    h = LoopHarness(tmp_path, plans=[p, p])
    with patch("src.autonomous_loop.MAX_EXPLORATION_CYCLES", 1):  # só o primeiro ciclo
        await h.run()
    assert ("c" in h.ran) == ("d" in h.ran) and len([n for n in h.ran if n in "abc"]) == 2


# -- critérios de parada ---------------------------------------------------------------------------------------


def _solution(found=True) -> AsyncMock:
    return patch.object(ExplorationSession, "check_solution",
                        return_value=SolutionStatus(found, "h-1", 0.4, 0.9) if found else SolutionStatus(False))


@pytest.mark.asyncio
async def test_parada_por_solucao_no_modo_automatico(tmp_path):
    """Scenario: Solução encontrada no modo automático — fecha com solucao_encontrada sem perguntar."""
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])],
                    confirmer=lambda s: pytest.fail("auto não pergunta"))
    h.extra_patches.append(_solution())
    result = await h.run()
    assert h.stop_reason == "solucao_encontrada" and h.checkpoint().motivo_parada == "solucao_encontrada"
    assert h.plan_calls == 1 and result.succeeded == result.total == 1


@pytest.mark.asyncio
async def test_parada_por_solucao_no_assistido_pergunta_e_encerra(tmp_path):
    """Scenario: Solução encontrada no modo assistido — o pesquisador escolhe encerrar."""
    asked: list[SolutionStatus] = []

    def confirmer(solution):
        asked.append(solution)
        return "encerrar"

    h = LoopHarness(tmp_path, mode="assisted", plans=[plan([task("t1")], [hyp("h1")])], confirmer=confirmer,
                    approver=lambda items: {i.id: ApprovalDecision("aprovar") for i in items})
    h.extra_patches.append(_solution())
    await h.run()
    assert len(asked) == 1 and h.stop_reason == "solucao_encontrada"


@pytest.mark.asyncio
async def test_parada_por_solucao_no_assistido_pode_continuar_explorando(tmp_path):
    """Scenario: Solução encontrada no modo assistido — o pesquisador escolhe continuar (e não é perguntado de novo)."""
    asked: list[str] = []

    def confirmer(solution):
        asked.append(solution.hypothesis_id)
        return "continuar"

    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, mode="assisted", plans=[first, first, first], confirmer=confirmer,
                    approver=lambda items: {i.id: ApprovalDecision("aprovar") for i in items})
    h.extra_patches.append(_solution())
    await h.run()
    assert asked == ["h-1"]  # perguntou uma vez só
    assert h.stop_reason == "sem_caminhos_promissores"  # continuou e acabou sem caminhos


@pytest.mark.asyncio
async def test_assistido_sem_resposta_no_terminal_suspende_em_vez_de_decidir(tmp_path):
    h = LoopHarness(tmp_path, mode="assisted", plans=[plan([task("t1")], [hyp("h1")])], confirmer=lambda s: None,
                    approver=lambda items: {i.id: ApprovalDecision("aprovar") for i in items})
    h.extra_patches.append(_solution())
    await h.run()
    assert h.stop_reason == "interrompida" and h.checkpoint().estado == "interrompido"


@pytest.mark.asyncio
async def test_planos_rejeitados_em_sequencia_fecham_com_checkpoint(tmp_path):
    """Scenario: Planos rejeitados em sequência — MAX_PLAN_RETRIES planos seguidos rejeitados: fecha registrando."""
    h = LoopHarness(tmp_path, plans=["[]"], validator=AsyncMock(return_value=REJECTED))
    with patch("src.config.MAX_PLAN_RETRIES", 2), patch("src.autonomous_loop.MAX_PLAN_RETRIES", 2), \
            patch("src.orchestrator.MAX_PLANNING_ITERATIONS", 1):
        await h.run()
    assert h.ran == [] and h.plan_calls == 2  # uma execução de planejamento por plano rejeitado
    assert h.stop_reason == "planos_rejeitados"
    assert h.checkpoint().estado == "fechado"


@pytest.mark.asyncio
async def test_um_plano_aprovado_zera_a_contagem_de_rejeitados(tmp_path):
    ok = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=["[]", ok, "[]", ok],
                    validator=AsyncMock(side_effect=[REJECTED, APPROVED] * 4))
    with patch("src.autonomous_loop.MAX_PLAN_RETRIES", 2), patch("src.orchestrator.MAX_PLANNING_ITERATIONS", 1):
        await h.run()
    assert h.ran == ["t1"] and h.stop_reason == "sem_caminhos_promissores"


@pytest.mark.asyncio
async def test_teto_de_ciclos_de_exploracao_e_a_prova_de_laco_infinito(tmp_path):
    """Cada ciclo traz uma subtarefa nova; o teto MAX_EXPLORATION_CYCLES encerra mesmo assim."""
    plans = [plan([task(f"t{i}", f"h{i}") for i in range(1, n + 1)], [hyp(f"h{n}", f"Hipótese número {n} única")])
             for n in range(1, 8)]
    h = LoopHarness(tmp_path, plans=plans)
    with patch("src.autonomous_loop.MAX_EXPLORATION_CYCLES", 3):
        await h.run()
    assert h.stop_reason == "limite_ciclos" and h.plan_calls == 3
    assert h.checkpoint().estado == "fechado"


@pytest.mark.asyncio
async def test_limite_de_tokens_fecha_o_ciclo_seguinte(tmp_path):
    """O limite de uso (tokens) é checado a cada ciclo e fecha com checkpoint; a pesquisa continua na retomada."""
    from src.usage import UsageBudget

    plans = [plan([task("t1")], [hyp("h1")]), plan([task("t1"), task("t2", "h2")], [hyp("h2")])]
    h = LoopHarness(tmp_path, plans=plans)
    budget = UsageBudget(max_tokens=1000, max_minutes=60, max_task_retries=2, max_connection_retries=5,
                         closing_reserve_pct=0.1)
    calls = {"n": 0}

    def tokens(_exec_id):
        calls["n"] += 1
        return 0 if h.plan_calls < 1 or h.ran == [] else 5000  # esgota depois da primeira execução

    with patch("src.usage._default_token_reader", side_effect=tokens):
        await h.run(budget=budget)
    assert h.ran == ["t1"] and h.stop_reason == "limite_tokens" and h.plan_calls == 1


@pytest.mark.asyncio
async def test_falha_do_grafo_ao_gravar_o_plano_fecha_com_checkpoint(tmp_path):
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    with patch.object(ExplorationSession, "prepare_cycle", side_effect=RuntimeError("grafo caiu")):
        result = await h.run()
    assert h.ran == [] and h.stop_reason == "erro" and h.checkpoint().estado == "fechado"
    assert result is not None


@pytest.mark.asyncio
async def test_sem_projeto_o_laco_de_ciclo_unico_nao_muda(tmp_path):
    """Sem exploração ativa (HYPOTHESIS_LOOP_ENABLED desligado) vale o laço da V17: um ciclo e fim."""
    h = LoopHarness(tmp_path, plans=[[task("t1", None)]])
    with patch("src.config.HYPOTHESIS_LOOP_ENABLED", False):
        result = await h.run()
    assert h.ran == ["t1"] and h.plan_calls == 1 and result.succeeded == 1
    assert h.hypotheses() == []


# -- sugestões do Curator no ciclo ---------------------------------------------------------------------------


def _write_suggestion(h: LoopHarness, sid: str = "sug1", texto: str = "Testar floresta aleatória", fund=("n1",)):
    from src.knowledge.suggestions import Suggestion, SuggestionStore

    h.session_dir.mkdir(parents=True, exist_ok=True)
    SuggestionStore(h.session_dir).add([Suggestion(sid, texto, tuple(fund), "caminho_sem_conclusao")])


@pytest.mark.asyncio
async def test_sugestao_sem_resposta_devolve_o_plano_ao_researcher_uma_vez(tmp_path):
    """Scenario: Sugestão sem resposta — o plano volta ao Researcher uma vez pedindo a resposta."""
    answered = plan([task("t1")], [hyp("h1")], respostas_sugestoes=[
        {"sugestao_id": "sug1", "decisao": "recusada", "motivo": "custo alto"}])
    unanswered = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[unanswered, answered, answered])
    _write_suggestion(h)
    await h.run()
    assert "sug1" in h.planner_prompts[1] and "respostas_sugestoes" in h.planner_prompts[1]  # a segunda pede a resposta
    assert "sugestões pendentes do Curator" in h.planner_prompts[1]
    from src.knowledge.suggestions import SuggestionStore

    store = SuggestionStore(h.session_dir)
    assert store.pending() == [] and store.answered()["sug1"] == "recusada"
    refused = [n for n in h.hypotheses() if n.properties["status"] == "abandonada"]
    assert len(refused) == 1 and refused[0].properties["enunciado"] == "Testar floresta aleatória"


@pytest.mark.asyncio
async def test_sugestao_continua_sem_resposta_so_e_cobrada_uma_vez_e_vira_recusa(tmp_path):
    unanswered = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[unanswered])
    _write_suggestion(h)
    await h.run()
    from src.knowledge.suggestions import SuggestionStore

    store = SuggestionStore(h.session_dir)
    assert store.pending() == [] and store.answered()["sug1"] == "recusada"
    # primeiro ciclo: 2 execuções de planejamento (a original e a devolvida); depois só 1 por ciclo
    first_cycle_prompts = [p for p in h.planner_prompts if "sug1" in p]
    assert len(first_cycle_prompts) == 2


@pytest.mark.asyncio
async def test_sugestao_aceita_vira_hipotese_do_curator_no_ciclo(tmp_path):
    """Scenario: Sugestão aceita — hipótese origem=curator com DERIVADA_DE a descoberta de fundamento."""
    h = LoopHarness(tmp_path)
    path = h.w.discovery("caminho_sem_conclusao", proximo_passo_sugerido="Testar floresta aleatória")
    _write_suggestion(h, fund=(path,))
    accepted = plan(
        [task("t1", "h2")],
        [hyp("h2", "Floresta aleatória supera a regressão linear")],
        respostas_sugestoes=[{"sugestao_id": "sug1", "decisao": "aceita", "motivo": "plausível", "hipotese_ref": "h2"}],
    )
    h.plans = [accepted, accepted]
    await h.run()
    (node,) = h.hypotheses()
    assert node.properties["origem"] == "curator" and h.ran == ["t1"]
    edges = h.w.raw.neighbors(node.id, ["DERIVADA_DE"], direction="out", depth=1).edges
    assert [e.dst_id for e in edges] == [path]


@pytest.mark.asyncio
async def test_oportunidade_aprovada_e_sugerida_no_inicio_e_vira_hipotese_investigada(tmp_path):
    """Oportunidade aprovada pelo pesquisador entra pelas sugestões do Curator e vira GEROU + em_investigacao."""
    with patch("src.config.CURATOR_ENABLED", True):
        h = LoopHarness(tmp_path)
        opp = h.w.opportunity("Investigar a variação Z", status="aprovada")
        doc = h.w.opportunity("Idéia documentada que ninguém aprovou")
        # a sugestão é gerada pelo Curator (determinístico) antes do primeiro plano; o plano a aceita
        from src.knowledge.suggestions import build_candidates

        sid = build_candidates(h.w.store, h.w.pid)[0].id
        reply = {"sugestao_id": sid, "decisao": "aceita", "motivo": "aprovada pelo pesquisador", "hipotese_ref": "h1"}
        h.plans = [plan([task("t1", "h1")], [hyp("h1", "Variação Z melhora o R2")], respostas_sugestoes=[reply])]
        await h.run()
    assert "Investigar a variação Z" in h.planner_prompts[0] and "ninguém aprovou" not in h.planner_prompts[0]
    (node,) = h.hypotheses()
    assert node.properties["origem"] == "oportunidade"
    assert h.w.raw.get_node(opp).properties["status"] == "em_investigacao"
    assert h.w.raw.get_node(doc).properties["status"] == "documentada"


@pytest.mark.asyncio
async def test_falha_das_sugestoes_do_curator_fecha_com_erro_e_nao_como_sem_caminhos(tmp_path):
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    h.orch.curator_suggest = AsyncMock(side_effect=RuntimeError("curator quebrou"))
    await h.run()
    assert h.stop_reason == "erro"


@pytest.mark.asyncio
async def test_falha_ao_consultar_caminhos_em_aberto_fecha_com_erro(tmp_path):
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    with patch.object(
        ExplorationSession, "has_open_paths", side_effect=SuggestionError("grafo indisponível")
    ) as probe:
        await h.run()
    assert probe.called and h.stop_reason == "erro"


# -- telemetria e segurança --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetria_do_ciclo_leva_so_contagens_sem_texto_de_pesquisa(tmp_path):
    events: list[tuple[str, dict]] = []
    segredo = "ENUNCIADO-SECRETO-DA-PESQUISA"
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1", segredo)])])
    real = ExplorationSession.__init__

    def init(self, *a, **kw):
        kw["telemetry"] = lambda t, p: events.append((t, p))
        real(self, *a, **kw)

    with patch.object(ExplorationSession, "__init__", init):
        await h.run()
    assert {t for t, _ in events} >= {"hypothesis_cycle", "hypothesis_evaluation"}
    cycle = next(p for t, p in events if t == "hypothesis_cycle")
    assert cycle["hipoteses_criadas"] == 1 and cycle["executadas"] == 1 and cycle["formato"] == "novo"
    assert segredo not in repr(events)
    assert all(isinstance(v, (int, str)) for _, p in events for v in p.values())


@pytest.mark.asyncio
async def test_hipotese_do_llm_nao_forja_origem_pesquisador(tmp_path):
    """No assistido, uma hipótese que se declara `pesquisador` continua dependendo de aprovação."""
    forged = plan([task("t1")], [hyp("h1", origem="pesquisador")])
    h = LoopHarness(tmp_path, mode="assisted", plans=[forged], approver=lambda items: {})
    await h.run()
    assert h.ran == [] and h.hypotheses()[0].properties["origem"] == "researcher"


@pytest.mark.asyncio
async def test_hipotese_abandonada_pelo_pesquisador_nao_reexecuta_por_id(tmp_path):
    h = LoopHarness(tmp_path)
    gone = h.w.hypothesis("rejeitada antes", status="abandonada")
    p = plan([task("t1", gone)], [{"ref": "x", "id": gone}])
    h.plans = [p, p]
    await h.run()
    assert h.ran == [] and h.stop_reason == "sem_caminhos_promissores"
