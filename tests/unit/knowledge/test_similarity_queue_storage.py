"""Testes da fila de similaridade: implementação PostgreSQL (conexão falsa), calibração e CLI."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.knowledge.calibration import suggest_adjustments
from src.knowledge.semantic_runtime import SemanticRuntime, format_stats, run_knowledge_command
from src.knowledge.similarity_queue import (
    BandRate,
    Candidate,
    InMemorySimilarityQueue,
    PostgresSimilarityQueue,
    QueueItemError,
    classify_band,
)


def _cand(**kw) -> Candidate:
    base = dict(
        node_a="a", node_b="b", label_a="Problema", label_b="Problema", tipo="relacionado", score=0.8,
        entre_dominios=False, entre_projetos=False, prioridade=0.4, text_hash_a="ha", text_hash_b="hb",
        embedding_model="m", embedding_version="1",
    )
    base.update(kw)
    return Candidate(**base)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, results):
        self.calls: list[tuple[str, tuple]] = []
        self._results = list(results)

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))
        return _FakeCursor(self._results.pop(0) if self._results else [])


def _queue(results):
    conn = _FakeConn(results)

    @contextmanager
    def factory():
        yield conn

    return PostgresSimilarityQueue(factory), conn


@pytest.mark.unit
class TestPostgresQueue:
    def test_enqueue_insere_com_on_conflict_e_parametros(self):
        queue, conn = _queue([[{"inserido": True}]])
        assert queue.enqueue(_cand()) is True
        sql, params = conn.calls[0]
        assert "INSERT INTO similarity_queue" in sql
        assert "ON CONFLICT (node_a, node_b, embedding_model, embedding_version, text_hash_a, text_hash_b)" in sql
        assert params[:2] == ("a", "b")
        assert "relacionado" not in sql  # valores só por parâmetro

    def test_enqueue_par_ja_registrado_devolve_false(self):
        queue, _ = _queue([[]])  # DO UPDATE ... WHERE não casou: nada retornado
        assert queue.enqueue(_cand()) is False

    def test_enqueue_de_pendente_atualizado_nao_conta_como_novo(self):
        queue, _ = _queue([[{"inserido": False}]])
        assert queue.enqueue(_cand()) is False

    def test_next_batch_ordena_por_prioridade(self):
        row = {
            "id": 7, "node_a": "a", "node_b": "b", "label_a": "Problema", "label_b": "Problema",
            "tipo": "relacionado", "score": 0.8, "entre_dominios": True, "entre_projetos": False,
            "prioridade": 0.6, "text_hash_a": "ha", "text_hash_b": "hb", "embedding_model": "m",
            "embedding_version": "1", "status": "pendente", "criado_em": None, "revisado_em": None,
            "revisado_por": None, "motivo": None,
        }
        queue, conn = _queue([[row]])
        (item,) = queue.next_batch(5)
        assert item.id == 7 and item.candidate.entre_dominios is True
        sql, params = conn.calls[0]
        assert "ORDER BY prioridade DESC" in sql and "status = 'pendente'" in sql
        assert params == (5,)

    def test_mark_confirmed_so_atualiza_pendentes(self):
        queue, conn = _queue([[{"id": 1}], []])
        queue.mark_confirmed(1, "curator", "ok")
        assert "WHERE id = %s AND status = 'pendente'" in conn.calls[0][0]
        assert conn.calls[0][1] == ("confirmado", "curator", "ok", 1)
        with pytest.raises(QueueItemError):
            queue.mark_discarded(99, "curator")

    def test_confirmation_rate_agrega_por_tipo_e_faixa(self):
        queue, conn = _queue(
            [[{"tipo": "relacionado", "faixa": "baixa", "confirmados": 1, "descartados": 19}]]
        )
        (rate,) = queue.confirmation_rate(30)
        assert rate.faixa == "baixa" and rate.taxa == pytest.approx(0.05)
        assert conn.calls[0][1][1] == 30


@pytest.mark.unit
class TestInMemoryQueueRegras:
    def test_ordem_por_prioridade_e_dedupe(self):
        queue = InMemorySimilarityQueue()
        assert queue.enqueue(_cand(node_a="a", node_b="b", prioridade=0.3))
        assert queue.enqueue(_cand(node_a="c", node_b="d", prioridade=0.9))
        assert not queue.enqueue(_cand(node_a="a", node_b="b", prioridade=0.3))
        assert [i.candidate.node_a for i in queue.next_batch(10)] == ["c", "a"]

    def test_pendente_e_atualizado_quando_dominio_e_descoberto(self):
        queue = InMemorySimilarityQueue()
        queue.enqueue(_cand(entre_dominios=False, prioridade=0.4))
        assert not queue.enqueue(_cand(entre_dominios=True, prioridade=0.6))
        (item,) = queue.next_batch(1)
        assert item.candidate.entre_dominios is True and item.candidate.prioridade == 0.6

    @pytest.mark.parametrize(
        ("tipo", "score", "faixa"),
        [("duplicata", 0.95, "duplicata"), ("relacionado", 0.65, "baixa"), ("relacionado", 0.75, "relacionado")],
    )
    def test_classify_band(self, tipo, score, faixa):
        assert classify_band(tipo, score) == faixa

    def test_taxa_ignora_revisoes_fora_da_janela(self):
        agora = [datetime.now(timezone.utc)]
        queue = InMemorySimilarityQueue(clock=lambda: agora[0])
        queue.enqueue(_cand(node_a="a", node_b="b", score=0.65))
        queue.enqueue(_cand(node_a="c", node_b="d", score=0.65))
        (i1, i2) = queue.next_batch(2)
        queue.mark_confirmed(i1.id, "x")
        agora[0] += timedelta(days=40)
        queue.mark_discarded(i2.id, "x")
        (rate,) = queue.confirmation_rate(30)
        assert (rate.confirmados, rate.descartados) == (0, 1)


@pytest.mark.unit
class TestCalibracao:
    def test_taxa_baixa(self, env):
        """Scenario: Taxa baixa"""
        for i in range(20):
            env.queue.enqueue(_cand(node_a=f"a{i}", node_b=f"b{i}", score=0.65))
        itens = env.queue.next_batch(20)
        env.queue.mark_confirmed(itens[0].id, "pesquisador")  # 1/20 = 5%
        for item in itens[1:]:
            env.queue.mark_discarded(item.id, "pesquisador")
        from src import config

        antes = (config.SIM_RELATED_MIN_CROSS, config.SIM_RELATED_MIN_SAME_DOMAIN, config.SIM_DUPLICATE_MIN)

        texto = format_stats(env.queue, 30)

        assert "5%" in texto
        assert "subir o limite inferior (SIM_RELATED_MIN_CROSS)" in texto
        assert antes == (config.SIM_RELATED_MIN_CROSS, config.SIM_RELATED_MIN_SAME_DOMAIN, config.SIM_DUPLICATE_MIN)

    def test_taxa_alta_sugere_descer(self):
        (msg,) = suggest_adjustments([BandRate("relacionado", "relacionado", 7, 3)])
        assert "descer o limite inferior (SIM_RELATED_MIN_SAME_DOMAIN)" in msg

    def test_taxa_saudavel_ou_sem_dados_nao_sugere(self):
        rates = [BandRate("relacionado", "baixa", 3, 7), BandRate("duplicata", "duplicata", 0, 0)]
        assert suggest_adjustments(rates) == []


@pytest.mark.unit
class TestCliKnowledge:
    def test_stats_nao_altera_configuracao_e_retorna_zero(self, env, capsys):
        runtime = SemanticRuntime(store=env.store, raw_store=env.raw, index=env.index, queue=env.queue)
        assert run_knowledge_command(["stats"], runtime) == 0
        assert "Fila de similaridade: 0 par(es) pendente(s)." in capsys.readouterr().out

    def test_reindex_reconcilia_o_indice(self, env, capsys):
        runtime = SemanticRuntime(store=env.store, raw_store=env.raw, index=env.index, queue=env.queue)
        assert run_knowledge_command(["reindex", "--yes"], runtime) == 0
        assert "Índice semântico" in capsys.readouterr().out

    def test_acao_invalida_retorna_codigo_de_erro(self, env):
        assert run_knowledge_command(["inexistente"]) != 0
