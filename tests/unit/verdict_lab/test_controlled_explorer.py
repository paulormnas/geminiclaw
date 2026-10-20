"""Orquestrador de exploração, orçamento e execução protegida (v18.8-verdict-controlled-sessions, seção 2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.benchmark import archive as bench_archive
from scripts.benchmark import footprint, model_versions
from scripts.verdict_lab.controlled import __main__ as cli
from scripts.verdict_lab.controlled import budget, runner
from scripts.verdict_lab.controlled.explorer import Segmento, Teto, explorar

pytestmark = pytest.mark.unit

BENCH_URL = "postgresql://geminiclaw:s3gredo@db.local:5432/geminiclaw_bench"
DEV_URL = "postgresql://geminiclaw:s3gredo@db.local:5432/geminiclaw"
PLANO = Path("scripts/verdict_lab/controlled/plano_piloto.json")


def seg(sid: str, motivo: str | None, *, custo: float = 1.0, exps: int = 0, minutos: float = 10.0, **kw: Any) -> Segmento:
    return Segmento(session_id=sid, motivo_parada=motivo, minutos=minutos, custo_usd=custo, tokens=1000, chamadas=10,
                    custo_por_provedor={"anthropic": custo}, experimentos_total=exps, **kw)


class Fake:
    """Backend simulado: devolve os segmentos na ordem e registra as retomadas."""

    def __init__(self, *segs: Segmento) -> None:
        self.segs, self.retomadas = list(segs), []

    def iniciar(self) -> Segmento:
        return self.segs.pop(0)

    def retomar(self, session_id: str) -> Segmento:
        self.retomadas.append(session_id)
        return self.segs.pop(0)

    def estado(self) -> dict[str, Any]:
        return {"experimentos": 0}


TETO = Teto(usd=10.0, sessoes=6, minutos=720)


def test_retomada_depois_do_limite_de_custo() -> None:
    b = Fake(seg("s1", "limite_custo", custo=3.0, exps=4), seg("s2", "sem_caminhos_promissores", exps=7))
    r = explorar(b, TETO)
    assert b.retomadas == ["s1"] and r["fim"] == "natural" and r["n_sessoes"] == 2
    assert r["custo_total_usd"] == 4.0 and r["sessoes"][1]["experimentos_novos"] == 3 and r["experimentos"] == 7


@pytest.mark.parametrize("motivo", ["solucao_encontrada", "sem_caminhos_promissores", "saturacao"])
def test_fim_natural_nunca_retoma(motivo: str) -> None:
    b = Fake(seg("s1", motivo, exps=3))
    r = explorar(b, TETO)
    assert r["fim"] == "natural" and r["motivo_final"] == motivo and b.retomadas == [] and not r["censurada"]


def test_teto_de_gasto_censura() -> None:
    r = explorar(Fake(seg("s1", "limite_tempo", custo=4.10, exps=2)), Teto(4.0, 6, 720))
    assert r["fim"] == "interrompida_pelo_orcamento" and r["censurada"] and r["motivo_final"] == "limite_tempo"


def test_teto_de_sessoes_e_de_minutos() -> None:
    assert explorar(Fake(seg("s1", "limite_tokens", exps=1)), Teto(10, 1, 720))["fim"] == "interrompida_pelo_orcamento"
    r = explorar(Fake(seg("s1", "limite_tokens", exps=1, minutos=800)), Teto(10, 6, 720))
    assert r["fim"] == "interrompida_pelo_orcamento"


def test_cota_repetida_sem_progresso() -> None:
    b = Fake(seg("s1", "limite_cota_provedor", exps=0), seg("s2", "limite_cota_provedor", exps=0))
    r = explorar(b, TETO)
    assert r["fim"] == "sem_progresso" and r["n_sessoes"] == 2 and b.retomadas == ["s1"]


def test_progresso_zera_a_contagem() -> None:
    b = Fake(seg("s1", "limite_cota_provedor", exps=0), seg("s2", "limite_tempo", exps=2),
             seg("s3", "limite_cota_provedor", exps=2), seg("s4", "solucao_encontrada", exps=3))
    assert explorar(b, TETO)["fim"] == "natural"


@pytest.mark.parametrize("motivo,esperado", [("planos_rejeitados", "planos_rejeitados"), ("erro", "erro"),
                                             (None, "sem_motivo_parada"), ("interrompida", "interrompida")])
def test_falha(motivo: str | None, esperado: str) -> None:
    r = explorar(Fake(seg("s1", motivo, exps=1)), TETO)
    assert r["fim"] == "falha" and r["motivo_final"] == esperado and r["censurada"]


def test_prazo_do_segmento_e_falha() -> None:
    r = explorar(Fake(seg("s1", "limite_tempo", exps=1, prazo_estourado=True)), TETO)
    assert r["fim"] == "falha" and r["motivo_final"] == "prazo_do_segmento"


def test_exploracao_json_soma_a_cadeia() -> None:
    b = Fake(seg("s1", "limite_custo", custo=2.0, exps=1), seg("s2", "limite_tokens", custo=1.5, exps=3),
             seg("s3", "saturacao", custo=0.5, exps=4))
    r = explorar(b, TETO, identidade={"combinacao": "c", "regime": "P", "repeticao": 2})
    assert [s["session_id"] for s in r["sessoes"]] == ["s1", "s2", "s3"]
    assert r["custo_total_usd"] == 4.0 and r["custo_por_provedor"] == {"anthropic": 4.0}
    assert r["tokens_total"] == 3000 and r["chamadas_total"] == 30 and r["minutos_total"] == 30.0
    assert (r["combinacao"], r["regime"], r["repeticao"]) == ("c", "P", 2) and r["teto"]["usd"] == 10.0


def test_teto_invalido() -> None:
    with pytest.raises(ValueError, match="Teto inválido"):
        Teto(0, 1, 1)


# --- orçamento ---------------------------------------------------------------------------------------------------


def test_orcamento_sem_piloto() -> None:
    o = budget.calcular(budget.carregar_plano(PLANO))
    assert o["total_geral"]["maximo"] == 56.0 and o["total_geral"]["esperado"] is None
    assert all(ln["usd"] is None and ln["gasto_esperado_usd"] is None for ln in o["linhas"])
    assert "sem dados" in budget.markdown(o) and "**máximo US$ 56.00**" in budget.markdown(o)


def test_orcamento_com_piloto() -> None:
    plano = budget.carregar_plano(PLANO)
    plano["repeticoes"] = {"P": 10}
    piloto = [{"combinacao": "sonnet-dev-sol-juiz", "regime": "P", "custo_total_usd": 2.5, "tokens_total": 900,
               "chamadas_total": 40, "sessoes": [{"uso_por_agente": {"developer": {"chamadas": 30}}}]}]
    o = budget.calcular(plano, piloto)
    linha = next(ln for ln in o["linhas"] if ln["combinacao"] == "sonnet-dev-sol-juiz")
    assert linha["gasto_esperado_usd"] == 25.0 and linha["gasto_maximo_usd"] == 100.0
    assert linha["usd"] == {"media": 2.5, "p90": 2.5} and linha["chamadas_por_agente_media"] == {"developer": 30.0}
    haiku = next(ln for ln in o["linhas"] if ln["combinacao"] == "haiku-dev-sol-juiz")
    assert haiku["gasto_esperado_usd"] is None and o["total_geral"]["esperado"] is None


def test_p90_por_posto() -> None:
    plano = budget.carregar_plano(PLANO)
    plano["repeticoes"] = {"P": 1}
    piloto = [{"combinacao": "haiku-dev-sol-juiz", "regime": "P", "custo_total_usd": float(v), "tokens_total": v,
               "chamadas_total": v} for v in range(1, 11)]
    linha = budget.calcular(plano, piloto)["linhas"][0]
    assert linha["usd"]["p90"] == 9.0 and linha["usd"]["media"] == 5.5


@pytest.mark.parametrize("mudar,trecho", [
    (lambda p: p.update(versao=2), "'versao'"),
    (lambda p: p["repeticoes"].update(Z=1), "regime desconhecido"),
    (lambda p: p["repeticoes"].update(P=-1), "inteiro >= 0"),
    (lambda p: p["combinacoes"].append(dict(p["combinacoes"][0])), "repetida"),
    (lambda p: p["combinacoes"][0].pop("teto_usd"), "teto inválido"),
])
def test_plano_invalido(tmp_path: Path, mudar, trecho: str) -> None:
    plano = json.loads(PLANO.read_text(encoding="utf-8"))
    mudar(plano)
    path = tmp_path / "p.json"
    path.write_text(json.dumps(plano), encoding="utf-8")
    with pytest.raises(budget.PlanError, match=trecho):
        budget.carregar_plano(path)


def test_orcamento_nao_chama_llm_nem_banco(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "executar_processo", lambda *a, **k: pytest.fail("processo"))
    assert cli.main(["orcamento", "--plano", str(PLANO), "--saida", str(tmp_path)]) == 0
    assert "máximo US$ 56.00" in capsys.readouterr().out
    saved = json.loads((tmp_path / "orcamento.json").read_text(encoding="utf-8"))
    assert saved["total_geral"]["maximo"] == 56.0


def test_orcamento_reproduzivel(tmp_path: Path) -> None:
    cli.main(["orcamento", "--plano", str(PLANO), "--saida", str(tmp_path / "a")])
    cli.main(["orcamento", "--plano", str(PLANO), "--saida", str(tmp_path / "b")])
    assert (tmp_path / "a" / "orcamento.json").read_bytes() == (tmp_path / "b" / "orcamento.json").read_bytes()


# --- backend de processo -----------------------------------------------------------------------------------------


def make_backend(tmp_path: Path, *, respostas: list[tuple[str, str | None]], exps: list[int]) -> runner.ProcessBackend:
    comandos: list[list[str]] = []
    respostas = list(respostas)
    exps = list(exps)

    def executor(cmd, env, timeout):
        comandos.append(list(cmd))
        return runner.ResultadoProcesso(0, "log")

    estado = {"atual": None}

    def ultima(out, desde):
        sid, motivo = respostas.pop(0)
        estado["atual"] = motivo
        return tmp_path / sid

    b = runner.ProcessBackend(
        task="tarefa", project_id="proj", env={"A": "1"}, output_dir=tmp_path, timeout=60.0, python="py",
        executor=executor,
        uso=lambda sid: {"cost_usd": 1.5, "total_tokens": 100, "calls": 5, "cost_by_provider": {"anthropic": 1.5},
                         "por_agente": {"developer": {"chamadas": 5.0}}},
        contagens=lambda pid: {"experimentos": exps.pop(0) if exps else 0, "resultados": 0, "hipoteses": 0},
        parada=lambda pasta: estado["atual"], ultima_sessao=ultima,
    )
    b.comandos = comandos  # type: ignore[attr-defined]
    return b


def test_backend_comandos_e_cadeia(tmp_path: Path) -> None:
    b = make_backend(tmp_path, respostas=[("s1", "limite_custo"), ("s2", "solucao_encontrada")], exps=[2, 5, 5])
    r = explorar(b, TETO)
    assert b.comandos[0] == ["py", "main.py", "--mode", "auto", "--project", "proj", "tarefa"]  # type: ignore[attr-defined]
    assert b.comandos[1] == ["py", "main.py", "--mode", "auto", "--session", "s1", "resume"]  # type: ignore[attr-defined]
    assert r["fim"] == "natural" and b.sessoes == ["s1", "s2"] and r["custo_total_usd"] == 3.0
    assert r["sessoes"][0]["uso_por_agente"] == {"developer": {"chamadas": 5.0}}


def test_backend_sem_pasta_de_sessao_e_falha(tmp_path: Path) -> None:
    b = make_backend(tmp_path, respostas=[("", None)], exps=[0])
    b.ultima_sessao = lambda out, desde: None
    r = explorar(b, TETO)
    assert r["fim"] == "falha" and r["motivo_final"] == "sem_motivo_parada" and b.sessoes == []


# --- execução de um item (reset, entrada, semeadura, arquivamento) ------------------------------------------------


def combo_item(regime: str = "N") -> runner.Item:
    combo = {"name": "c1", "roles": {"*": "anthropic/claude-haiku-5-5", "VALIDATOR": "openai/gpt-6.1-sol"}}
    return runner.Item(1, regime, combo, Teto(4.0, 3, 60), 99)


class FakeBackend:
    instancias: list["FakeBackend"] = []

    def __init__(self, **kw: Any) -> None:
        self.kw, self.sessoes, self.logs = kw, ["sessao-9"], ["log-a", "log-b"]
        FakeBackend.instancias.append(self)

    def iniciar(self) -> Segmento:
        return seg("sessao-9", "sem_caminhos_promissores", exps=3)

    def retomar(self, session_id: str) -> Segmento:  # pragma: no cover - fim natural
        raise AssertionError

    def estado(self) -> dict[str, Any]:
        return {"experimentos": 3, "resultados": 2, "hipoteses": 1}


def executar(monkeypatch, tmp_path: Path, **over: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    FakeBackend.instancias.clear()
    chamadas: dict[str, Any] = {"reset": [], "semear": []}
    monkeypatch.setattr(runner.rb, "_close_local_pools", lambda: None)
    monkeypatch.setattr(bench_archive, "fetch_events", lambda sid: [{"event_type": "x", "sid": sid}])
    monkeypatch.setattr(footprint, "project_graph_full", lambda pid, store=None: {"nos": [], "arestas": []})
    monkeypatch.setattr(model_versions, "db_allocation_profile", lambda sid: None)
    args = dict(
        saida=tmp_path / "saida", env_base={"PATH": "/bin", "SEGREDO": "x"}, matriz={"env": {"SESSION_MAX_COST_USD": "3"},
        "timeout_seconds": 100}, output_dir=tmp_path / "outputs", target=object(), reset=True, dump=False,
        semear=lambda nome, draft: chamadas["semear"].append((nome, draft)) or "proj-1",
        reiniciar=lambda target, **kw: chamadas["reset"].append(kw),
        backend_factory=FakeBackend,
    )
    args.update(over)
    return runner.executar_item(combo_item(), **args), chamadas


def test_executar_item_prepara_entrada_verdade_e_arquiva(monkeypatch, tmp_path: Path) -> None:
    resultado, chamadas = executar(monkeypatch, tmp_path)
    pasta = tmp_path / "saida" / "c1" / "N" / "r1"
    assert len(chamadas["reset"]) == 1 and chamadas["reset"][0]["archive_dir"] == pasta
    nome, draft = chamadas["semear"][0]
    assert nome == "c1-N-r1" and draft.alvo == 0.55 and draft.ao_atingir_objetivo == "continuar"
    assert (pasta / "input_context" / "dados.csv").is_file() and (pasta / "input_context" / "dados.yaml").is_file()
    assert (pasta / "verdade" / "verdade.json").is_file() and not list((pasta / "input_context").rglob("verdade*"))
    for nome_arq in ("exploracao.json", "grafo_projeto.json", "eventos.json", "run.log"):
        assert (pasta / nome_arq).is_file(), nome_arq
    saved = json.loads((pasta / "exploracao.json").read_text(encoding="utf-8"))
    assert saved["fim"] == "natural" and saved["project_id"] == "proj-1" and saved["regime"] == "N"
    assert saved["semente_dado"] == 99 and saved["estado_grafo"]["experimentos"] == 3
    assert resultado["combinacao"] == "c1"


def test_ambiente_do_subprocesso_nao_leva_a_verdade(monkeypatch, tmp_path: Path) -> None:
    executar(monkeypatch, tmp_path)
    env = FakeBackend.instancias[0].kw["env"]
    pasta = tmp_path / "saida" / "c1" / "N" / "r1"
    assert env["INPUT_CONTEXT_DIR"] == str(pasta / "input_context")
    assert env["VALIDATOR_MODEL"] == "openai/gpt-6.1-sol"
    assert not any("verdade" in str(v) for v in env.values()) and "verdade" not in " ".join(env)


def test_sem_reset_nao_apaga_nada(monkeypatch, tmp_path: Path) -> None:
    _, chamadas = executar(monkeypatch, tmp_path, reset=False)
    assert chamadas["reset"] == []


# --- execução protegida (CLI) ------------------------------------------------------------------------------------


def env_bench(monkeypatch) -> None:
    monkeypatch.setattr(cli, "_dotenv", lambda: {"BENCHMARK_DATABASE_URL": BENCH_URL, "DATABASE_URL": DEV_URL,
                                                  "BENCHMARK_QDRANT_URL": "http://qdrant.local:6333",
                                                  "OPENAI_API_KEY": "k"})


def test_ensaio_por_padrao_nao_cria_nada(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "executar_item", lambda *a, **k: pytest.fail("executou"))
    saida = tmp_path / "saida"
    assert cli.main(["explorar", "--plano", str(PLANO), "--saida", str(saida)]) == 0
    out = capsys.readouterr().out
    assert "ENSAIO" in out and "haiku-dev-sol-juiz/P/r1" in out and "máximo US$ 56.00" in out
    assert not saida.exists()


def test_executar_sem_reset_stores_e_recusado(monkeypatch, capsys, tmp_path: Path) -> None:
    env_bench(monkeypatch)
    monkeypatch.setattr(runner, "executar_item", lambda *a, **k: pytest.fail("executou"))
    saida = tmp_path / "saida"
    assert cli.main(["explorar", "--plano", str(PLANO), "--saida", str(saida), "--executar"]) == 2
    assert "--reset-stores" in capsys.readouterr().err and not saida.exists()


def test_executar_sem_confirm_target_mostra_o_alvo_sem_senha(monkeypatch, capsys, tmp_path: Path) -> None:
    env_bench(monkeypatch)
    monkeypatch.setattr(runner, "executar_item", lambda *a, **k: pytest.fail("executou"))
    saida = tmp_path / "saida"
    argv = ["explorar", "--plano", str(PLANO), "--saida", str(saida), "--executar", "--reset-stores"]
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert "geminiclaw_bench@db.local" in err and "s3gredo" not in err and not saida.exists()


def test_executar_com_alvo_confirmado_roda_e_grava_o_manifesto(monkeypatch, capsys, tmp_path: Path) -> None:
    env_bench(monkeypatch)
    vistos: list[str] = []

    def falso(item, **kw):
        vistos.append(item.nome)
        pasta = runner.diretorio_da(kw["saida"], item)
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "exploracao.json").write_text("{}", encoding="utf-8")
        return {"fim": "natural", "motivo_final": "saturacao", "custo_total_usd": 1.0, "n_sessoes": 1}

    monkeypatch.setattr(runner, "executar_item", falso)
    saida = tmp_path / "saida"
    argv = ["explorar", "--plano", str(PLANO), "--saida", str(saida), "--executar", "--reset-stores",
            "--confirm-target", "geminiclaw_bench@db.local"]
    assert cli.main(argv) == 0
    assert len(vistos) == 8 and vistos[0] == "haiku-dev-sol-juiz/P/r1"
    manifesto = json.loads((saida / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["entradas"]["plano"]["sha256"] and manifesto["sementes_dos_dados"] and "commit" in manifesto
    assert manifesto["verdict"]["VERDICT_MODEL"] == "v2"


def test_saida_ocupada_e_recusada_e_retomar_pula_as_feitas(monkeypatch, capsys, tmp_path: Path) -> None:
    env_bench(monkeypatch)
    saida = tmp_path / "saida"
    saida.mkdir()
    (saida / "manifesto.json").write_text("{}", encoding="utf-8")
    argv = ["explorar", "--plano", str(PLANO), "--saida", str(saida), "--executar", "--reset-stores",
            "--confirm-target", "geminiclaw_bench@db.local"]
    assert cli.main(argv) == 2 and "manifesto.json" in capsys.readouterr().err
    feitas = runner.diretorio_da(saida, runner.Item(1, "P", {"name": "haiku-dev-sol-juiz"}, TETO, 1))
    feitas.mkdir(parents=True)
    (feitas / "exploracao.json").write_text("{}", encoding="utf-8")
    vistos: list[str] = []
    monkeypatch.setattr(runner, "executar_item", lambda item, **kw: vistos.append(item.nome) or {
        "fim": "natural", "motivo_final": "x", "custo_total_usd": 0.0, "n_sessoes": 1})
    assert cli.main([*argv, "--retomar"]) == 0
    assert len(vistos) == 7 and "haiku-dev-sol-juiz/P/r1" not in vistos


def test_gerar_grava_dados_e_verdade_separados(capsys, tmp_path: Path) -> None:
    assert cli.main(["gerar", "--regime", "N", "--semente", "3", "--saida", str(tmp_path)]) == 0
    assert "sha256" in capsys.readouterr().out
    assert (tmp_path / "input_context" / "dados.csv").is_file() and (tmp_path / "verdade" / "verdade.json").is_file()
