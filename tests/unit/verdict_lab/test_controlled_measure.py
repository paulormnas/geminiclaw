"""Medição das explorações controladas (v18.8-verdict-controlled-sessions, seção 3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.verdict_lab import output
from scripts.verdict_lab.controlled import __main__ as cli
from scripts.verdict_lab.controlled import measure, stats
from scripts.verdict_lab.controlled.measure import ExploracaoMedida, HipoteseMedida
from scripts.verdict_lab.replay import replay_file
from src.knowledge.verdict import Attempt, Criterion, VerdictParams, compute_verdict

pytestmark = pytest.mark.unit

PARAMS = VerdictParams()
CRIT = {"metrica": "acuracia", "alvo": 0.93, "delta_min": 0.01, "metrica_id": "m1", "sentido": "maior_melhor"}


# ---------------------------------------------------------------------------
# Intervalos
# ---------------------------------------------------------------------------


def test_wilson_de_6_em_10() -> None:
    t = stats.taxa(6, 10)
    assert t.metodo == "wilson" and t.valor == 0.6
    assert t.baixo == pytest.approx(0.3127, abs=1e-3) and t.alto == pytest.approx(0.8318, abs=1e-3)
    assert t.rotulo.startswith("6/10 = 0.600")


def test_zero_em_quinze_usa_clopper_pearson() -> None:
    t = stats.taxa(0, 15)
    assert t.metodo == "clopper-pearson" and t.baixo == 0.0 and t.alto == pytest.approx(0.218, abs=1e-3)


def test_n_em_n_e_sem_dados() -> None:
    assert stats.taxa(10, 10).baixo == pytest.approx(0.6915, abs=1e-3) and stats.taxa(10, 10).alto == 1.0
    assert stats.taxa(0, 0).valor is None and stats.taxa(0, 0).rotulo == "0/0"
    with pytest.raises(ValueError):
        stats.taxa(3, 2)


def test_percentis_e_resumo() -> None:
    r = stats.resumo([1.0, 2.0, 3.0, 4.0, 5.0])
    assert (r["mediana"], r["p10"], r["p90"], r["n"]) == (3.0, 1.4, 4.6, 5)
    assert stats.resumo([])["mediana"] is None


# ---------------------------------------------------------------------------
# Medidas sobre explorações simuladas
# ---------------------------------------------------------------------------


def hip(estado: str, *, plantada: bool = False, uteis: int = 3, total: int = 5, ate: int | None = None) -> HipoteseMedida:
    veredito = {"validada": 0.5, "refutada": -0.5, "indecisa": 0.0}[estado]
    return HipoteseMedida(
        id="h", estado=estado, veredito_gravado=veredito, veredito_sistema=veredito, veredito_completa2=veredito,
        veredito_atual=veredito, n_tentativas=6, variacoes=total, variacoes_uteis=uteis, tentativas_ate_limiar=ate,
        plantada=plantada,
    )


def expl(regime: str, estados: list[str], *, censurada: bool = False, custo: float = 1.0, combo: str = "c1",
         fim: str = "natural", rep: int = 1) -> ExploracaoMedida:
    return ExploracaoMedida(
        combinacao=combo, regime=regime, repeticao=rep, pasta=Path("."), fim=fim, censurada=censurada,
        custo_usd=custo, chamadas=10, tokens=100, nao_testadas=0, hipoteses=[hip(e) for e in estados], verdade={},
    )


def test_poder_e_falsa_validacao() -> None:
    p = [expl("P", ["validada"]) for _ in range(6)] + [expl("P", ["indecisa"]) for _ in range(4)]
    n = [expl("N", ["validada"])] + [expl("N", ["indecisa"]) for _ in range(14)]
    mp, mn = measure.medir_grupo(p), measure.medir_grupo(n)
    assert (mp["com_hipotese_validada"].k, mp["com_hipotese_validada"].n) == (6, 10)
    assert mp["com_hipotese_validada"].metodo == "wilson"
    assert (mn["com_hipotese_validada"].k, mn["com_hipotese_validada"].n) == (1, 15)


def test_zero_erros_em_quinze_explorações_t() -> None:
    m = measure.medir_grupo([expl("T", ["indecisa"]) for _ in range(15)])
    t = m["com_hipotese_validada"]
    assert (t.k, t.n, t.metodo) == (0, 15, "clopper-pearson") and t.alto == pytest.approx(0.218, abs=1e-3)


def test_censuradas_ficam_fora_das_taxas_e_sao_contadas() -> None:
    p = [expl("P", ["validada"]) for _ in range(4)] + [expl("P", ["indecisa"]) for _ in range(3)]
    p += [expl("P", [], censurada=True, fim="interrompida_pelo_orcamento") for _ in range(3)]
    m = measure.medir_grupo(p)
    assert m["n_validas"] == 7 and m["n_censuradas"] == 3 and m["com_hipotese_validada"].n == 7
    assert m["censuradas_por_fim"] == {"interrompida_pelo_orcamento": 3}


def test_custo_por_validacao_util() -> None:
    p = [expl("P", ["validada"], custo=5.0) for _ in range(3)] + [expl("P", ["indecisa"], custo=5.0) for _ in range(3)]
    m = measure.medir_grupo(p)
    assert m["custo_usd"] == 30.0 and m["custo_por_validacao_usd"] == 10.0 and m["chamadas_por_validacao"] == 20.0
    assert measure.medir_grupo([expl("P", ["indecisa"])])["custo_por_validacao_usd"] is None


def test_refutacao_discordante_so_sem_validada() -> None:
    p = [expl("P", ["refutada"]), expl("P", ["refutada", "validada"]), expl("P", ["indecisa"])]
    m = measure.medir_grupo(p)
    assert m["refutacao_discordante"].k == 1 and m["indecisao"].k == 1 and m["com_hipotese_validada"].k == 1
    assert m["hipoteses"][measure.REFUTADA] == 2


def test_variacoes_tentativas_ate_limiar_e_abordagem_plantada() -> None:
    e = expl("F", [])
    e.hipoteses = [hip("validada", uteis=2, total=4, ate=5), hip("refutada", plantada=True, uteis=0, total=1)]
    m = measure.medir_grupo([e])
    assert m["variacoes_uteis"]["mediana"] == 1.0 and m["variacoes_total"]["p90"] == pytest.approx(3.7)
    assert m["tentativas_ate_limiar"]["n"] == 1 and m["tentativas_ate_limiar"]["mediana"] == 5.0
    assert m["abordagem_plantada"] == {"hipoteses": 1, "validada": 0, "refutada": 1, "indecisa": 0}


def test_estado_pelo_limiar() -> None:
    assert [measure.estado_do(v) for v in (0.3, 0.299, -0.3, -0.299)] == ["validada", "indecisa", "refutada", "indecisa"]


def test_agrupar_inclui_o_grupo_de_todas_as_combinacoes() -> None:
    g = measure.agrupar([expl("P", [], combo="a"), expl("P", [], combo="b"), expl("N", [], combo="a")])
    assert len(g[("a", "P")]) == 1 and len(g[(measure.TODAS, "P")]) == 2 and ("b", "N") not in g


# ---------------------------------------------------------------------------
# Rodada arquivada de ponta a ponta
# ---------------------------------------------------------------------------

VALORES_VALIDADA = [(0.94, "c1", "n1"), (0.95, "c2", "n1"), (0.96, "c3", "n1"), (0.97, "c4", "n1"),
                    (0.96, "c5", "n1"), (0.97, "c6", "n1"), (0.96, "c3", "n2"), (0.97, "c4", "n2")]
VALORES_INDECISA = [(0.50, "c1", "n1"), (0.51, "c2", "n1")]


def grafo(hipoteses: dict[str, list[tuple[float | str, str, str]]], vereditos: dict[str, float | None]) -> dict[str, Any]:
    nos: list[dict[str, Any]] = [
        {"id": "p", "label": "Problema", "propriedades": {"id": "p", "projeto_id": "pj", "criterio_sucesso": CRIT}},
        {"id": "m1", "label": "Metrica",
         "propriedades": {"id": "m1", "nome": "acuracia", "sentido": "maior_melhor"}},
    ]
    arestas: list[dict[str, Any]] = []
    for hid, tentativas in hipoteses.items():
        nos.append({"id": hid, "label": "Hipotese", "propriedades": {
            "id": hid, "projeto_id": "pj", "enunciado": hid, "veredito": vereditos.get(hid)}})
        arestas.append({"origem": hid, "tipo": "SOBRE", "destino": "p", "propriedades": {}})
        for i, (valor, config, no) in enumerate(tentativas):
            e, r = f"{hid}-e{i}", f"{hid}-r{i}"
            props: dict[str, Any] = {
                "id": e, "status": "sucesso", "criado_em": f"2026-01-01T00:{i:02d}:00+00:00", "seed": i,
                "hash_params": config, "sessao_id": "s", "no_execucao": no, "projeto_id": "pj"}
            if valor == "MemoryError":
                props.update(status="falha", causa_falha="abordagem", assinatura_falha="MemoryError")
            nos.append({"id": e, "label": "Experimento", "propriedades": props})
            arestas.append({"origem": e, "tipo": "TESTA", "destino": hid, "propriedades": {}})
            if valor != "MemoryError":
                nos.append({"id": r, "label": "Resultado", "propriedades": {
                    "id": r, "valor": valor, "nome_original": "acuracia", "status_validacao": "validado",
                    "projeto_id": "pj"}})
                arestas += [{"origem": e, "tipo": "PRODUZIU", "destino": r, "propriedades": {}},
                            {"origem": r, "tipo": "MEDE", "destino": "m1", "propriedades": {}}]
    return {"nos": nos, "arestas": arestas}


def veredito_gravado(pasta: Path, hipoteses: dict[str, list[tuple[float | str, str, str]]]) -> dict[str, float]:
    """O que o sistema gravaria: v2 sobre as tentativas coletadas do grafo (arredondado a seis casas)."""
    (pasta / "grafo_projeto.json").write_text(json.dumps(grafo(hipoteses, {})), encoding="utf-8")
    _, hs = replay_file(pasta / "grafo_projeto.json")
    return {h.hipotese_id: round(compute_verdict(h.attempts, h.criterion, PARAMS).veredito, 6) for h in hs}


def arquivar(raiz: Path, combo: str, regime: str, rep: int, hipoteses: dict[str, list[Any]], *,
             censurada: bool = False, fim: str = "natural", custo: float = 2.0,
             alterar: dict[str, float] | None = None) -> Path:
    pasta = raiz / combo / regime / f"r{rep}"
    (pasta / "verdade").mkdir(parents=True, exist_ok=True)
    vereditos: dict[str, float | None] = {**veredito_gravado(pasta, hipoteses), **(alterar or {})}
    (pasta / "grafo_projeto.json").write_text(json.dumps(grafo(hipoteses, vereditos)), encoding="utf-8")
    teto, alvo = {"P": (0.96, 0.93), "T": (0.90, 0.93), "N": (0.50, 0.55), "F": (0.96, 0.93)}[regime]
    verdade = {"regime": regime, "teto": teto, "alvo": alvo, "abordagem_plantada": (
        {"assinatura_falha": "MemoryError"} if regime == "F" else None)}
    (pasta / "verdade" / "verdade.json").write_text(json.dumps(verdade), encoding="utf-8")
    (pasta / "exploracao.json").write_text(json.dumps({
        "combinacao": combo, "regime": regime, "repeticao": rep, "fim": fim, "censurada": censurada,
        "custo_total_usd": custo, "chamadas_total": 40, "tokens_total": 4000}), encoding="utf-8")
    return pasta


def test_rodada_arquivada_e_medida_com_equivalencia(tmp_path: Path) -> None:
    arquivar(tmp_path, "c1", "P", 1, {"h1": VALORES_VALIDADA, "h2": VALORES_INDECISA})
    arquivar(tmp_path, "c1", "N", 1, {"h1": VALORES_INDECISA})
    arquivar(tmp_path, "c1", "P", 2, {"h1": VALORES_INDECISA}, censurada=True, fim="interrompida_pelo_orcamento")
    expls = measure.carregar_rodada(tmp_path, PARAMS)
    assert [(e.regime, e.repeticao) for e in expls] == [("N", 1), ("P", 1), ("P", 2)]
    p1 = expls[1]
    estados = {h.id: h.estado for h in p1.hipoteses}
    assert estados == {"h1": "validada", "h2": "indecisa"}
    h1 = p1.hipoteses[0]
    assert abs(h1.veredito_sistema - h1.veredito_completa2) <= 1e-12
    assert h1.variacoes == 6 and h1.variacoes_uteis >= 3 and h1.tentativas_ate_limiar is not None
    assert expls[2].censurada and measure.equivalencia(expls)["maior_diferenca_completa2"] <= 1e-12
    m = measure.medir_grupo([e for e in expls if e.regime == "P"])
    assert m["n_validas"] == 1 and m["n_censuradas"] == 1 and m["com_hipotese_validada"].k == 1


def test_divergencia_do_gravado_encerra_com_erro_que_cita_a_hipotese(tmp_path: Path) -> None:
    arquivar(tmp_path, "c1", "P", 1, {"h1": VALORES_VALIDADA}, alterar={"h1": -0.9})
    with pytest.raises(measure.MeasureError, match="h1"):
        measure.carregar_rodada(tmp_path, PARAMS)


def test_verdade_ausente_e_regime_inconsistente(tmp_path: Path) -> None:
    pasta = arquivar(tmp_path, "c1", "P", 1, {"h1": VALORES_VALIDADA})
    (pasta / "verdade" / "verdade.json").write_text(json.dumps({"regime": "N"}), encoding="utf-8")
    with pytest.raises(measure.MeasureError, match="regime"):
        measure.carregar_rodada(tmp_path, PARAMS)
    (pasta / "verdade" / "verdade.json").unlink()
    with pytest.raises(measure.MeasureError, match="verdade.json"):
        measure.carregar_rodada(tmp_path, PARAMS)


def test_diretorio_sem_exploracao_e_inexistente(tmp_path: Path) -> None:
    with pytest.raises(measure.MeasureError, match="nenhum exploracao.json"):
        measure.carregar_rodada(tmp_path, PARAMS)
    with pytest.raises(measure.MeasureError, match="inexistente"):
        measure.carregar_rodada(tmp_path / "nao", PARAMS)


def test_abordagem_plantada_no_regime_f(tmp_path: Path) -> None:
    arquivar(tmp_path, "c1", "F", 1, {"h1": [("MemoryError", "c1", "n1"), ("MemoryError", "c1", "n1")],
                                       "h2": VALORES_VALIDADA})
    (e,) = measure.carregar_rodada(tmp_path, PARAMS)
    assert {h.id: h.plantada for h in e.hipoteses} == {"h1": True, "h2": False}
    m = measure.medir_grupo([e])
    assert m["abordagem_plantada"]["hipoteses"] == 1 and m["com_hipotese_validada"].k == 1


def test_medir_grava_saidas_e_recusa_resultado_anterior(tmp_path: Path) -> None:
    arquivar(tmp_path, "c1", "P", 1, {"h1": VALORES_VALIDADA, "h2": VALORES_INDECISA})
    arquivar(tmp_path, "c1", "N", 1, {"h1": VALORES_INDECISA, "h2": VALORES_VALIDADA})
    r = measure.medir(tmp_path, repeticoes=20, params=PARAMS)
    out = r["saida"]
    assert out == (tmp_path / "medicao").resolve()
    manifesto = json.loads((out / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["comando"] == "medir" and len(manifesto["entradas"]) == 6
    assert {v["nome"] for v in manifesto["variantes"]} == {"completa2", "atual"}
    csv = (out / "resultados.csv").read_text(encoding="utf-8")
    assert csv.splitlines()[0].startswith("nivel,") and csv.count("hipotese,") >= 4
    relatorio = (out / "relatorio.md").read_text(encoding="utf-8")
    for trecho in ("Taxas por regime", "Equivalência com o laboratório", "Observado × previsto", "1/1 = 1.000"):
        assert trecho in relatorio
    with pytest.raises(output.OutputError, match="manifesto.json"):
        measure.medir(tmp_path, repeticoes=20, params=PARAMS)
    measure.medir(tmp_path, repeticoes=20, params=PARAMS, sobrescrever=True)


def test_exploracoes_da_medicao_anterior_nao_entram_na_nova(tmp_path: Path) -> None:
    arquivar(tmp_path, "c1", "P", 1, {"h1": VALORES_VALIDADA})
    measure.medir(tmp_path, repeticoes=10, params=PARAMS)
    assert len(measure.carregar_rodada(tmp_path, PARAMS)) == 1


# ---------------------------------------------------------------------------
# Previsão e comparação
# ---------------------------------------------------------------------------


def tentativas(valores: list[tuple[float, str, str]], falhas: int = 0) -> list[Attempt]:
    out = [
        Attempt(attempt_id=f"t{i}", timestamp=f"2026-01-01T00:{i:02d}:00+00:00", node_id=no, session_id="s",
                seed=i, dataset_ids=(), config_hash=cfg, outcome_kind="resultado", value=v, validation="validado",
                contract_complete=True)
        for i, (v, cfg, no) in enumerate(valores)
    ]
    out += [
        Attempt(attempt_id=f"f{i}", timestamp=f"2026-01-02T00:{i:02d}:00+00:00", node_id="n1", session_id="s",
                seed=None, dataset_ids=(), config_hash="sem_config", outcome_kind="falha", failure_cause="ambigua")
        for i in range(falhas)
    ]
    return out


def com_tentativas(ts: list[Attempt]) -> HipoteseMedida:
    h = hip("indecisa")
    h.tentativas, h.n_tentativas = ts, len(ts)
    h.criterion = Criterion("maior_melhor", 0.01, 0.93)
    return h


AMOSTRA = [(0.90, "a", "n1"), (0.92, "a", "n1"), (0.91, "b", "n1"), (0.93, "b", "n1"), (0.92, "c", "n2"),
           (0.94, "c", "n2")]


def test_estimativa_dos_parametros_da_simulacao() -> None:
    est = measure.estimar_parametros([com_tentativas(tentativas(AMOSTRA, falhas=2))])
    assert est["sigma"] == pytest.approx(0.01414, abs=1e-4)  # desvio entre repetições da mesma configuração
    assert est["tau"] >= 0 and est["nos"] == 2 and est["tentativas_por_hipotese"] == 8
    assert est["p_variacao"] == pytest.approx(2 / 5) and est["p_falha"] == pytest.approx(2 / 8)


def test_parametros_nao_estimaveis_dizem_o_motivo() -> None:
    assert "sem hipóteses" in measure.estimar_parametros([])["motivo"]
    sem_repeticao = com_tentativas(tentativas([(0.9, "a", "n1"), (0.91, "b", "n1")]))
    assert "sigma" in measure.estimar_parametros([sem_repeticao])["motivo"]
    um_resultado = com_tentativas(tentativas([(0.9, "a", "n1"), (0.91, "a", "n1")]))
    assert "tau" in measure.estimar_parametros([um_resultado])["motivo"]


def exploracoes_com_amostra(regime: str, n: int, validadas: int) -> list[ExploracaoMedida]:
    out = []
    for i in range(n):
        e = expl(regime, ["validada" if i < validadas else "indecisa"], rep=i + 1)
        e.hipoteses[0] = com_tentativas(tentativas(AMOSTRA))
        e.hipoteses[0].estado = "validada" if i < validadas else "indecisa"
        e.verdade = {"teto": {"P": 0.96, "T": 0.90, "N": 0.50}[regime], "alvo": 0.93}
        out.append(e)
    return out


def test_previsao_e_deterministica_e_tem_intervalo() -> None:
    obs = exploracoes_com_amostra("P", 5, 3)
    est = measure.estimar_parametros([h for e in obs for h in e.hipoteses])
    a = measure.prever("c1", "P", est, obs, semente=7, repeticoes=60)
    b = measure.prever("c1", "P", est, obs, semente=7, repeticoes=60)
    assert a["prevista"] == b["prevista"] and a["baixo"] <= a["prevista"] <= a["alto"]
    assert measure.prever("c1", "P", {"motivo": "x"}, obs, semente=7, repeticoes=10) == {"motivo": "x"}


def test_regime_incompativel_e_registrado_sem_alterar_parametros(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.config as config

    antes = (config.VERDICT_PRIOR, config.VERDICT_Q_DIVERGENT)
    grupos = measure.agrupar(exploracoes_com_amostra("N", 15, 4))
    monkeypatch.setattr(measure, "estimar_parametros", lambda hs: {"ok": True})
    monkeypatch.setattr(measure, "prever", lambda *a, **k: {
        "prevista": 0.02, "baixo": 0.0, "alto": 0.06, "hipoteses_por_exploracao": 1})
    (linha,) = measure.comparar(grupos, semente=1, repeticoes=10)
    assert linha["classificacao"] == "incompativel" and linha["medida"] == "falsa_validacao"
    assert linha["observada"].k == 4 and linha["observada"].n == 15
    assert (config.VERDICT_PRIOR, config.VERDICT_Q_DIVERGENT) == antes


def test_regime_compativel_quando_a_observada_cai_no_intervalo(monkeypatch: pytest.MonkeyPatch) -> None:
    grupos = measure.agrupar(exploracoes_com_amostra("N", 15, 1))
    monkeypatch.setattr(measure, "estimar_parametros", lambda hs: {"ok": True})
    monkeypatch.setattr(measure, "prever", lambda *a, **k: {
        "prevista": 0.05, "baixo": 0.0, "alto": 0.12, "hipoteses_por_exploracao": 1})
    assert measure.comparar(grupos, semente=1, repeticoes=10)[0]["classificacao"] == "compativel"


def test_sem_previsao_registra_o_motivo() -> None:
    (linha,) = measure.comparar(measure.agrupar([expl("N", ["indecisa"])]), semente=1, repeticoes=10)
    assert linha["classificacao"] == "sem_previsao" and "sigma" in linha["motivo"]


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------


def test_cli_medir(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(VerdictParams, "from_config", classmethod(lambda cls: PARAMS))
    assert cli.main(["medir", "--rodada", str(tmp_path / "nao")]) == cli.EXIT_EXCEPTION
    assert "inexistente" in capsys.readouterr().err
    arquivar(tmp_path, "c1", "P", 1, {"h1": VALORES_VALIDADA})
    args = ["medir", "--rodada", str(tmp_path), "--repeticoes-simulacao", "10"]
    assert cli.main(args) == 0 and "1 explorações medidas" in capsys.readouterr().out
    assert cli.main(args) == cli.EXIT_REFUSED and "manifesto.json" in capsys.readouterr().err
    assert cli.main([*args, "--sobrescrever"]) == 0
