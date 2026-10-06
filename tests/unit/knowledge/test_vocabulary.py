"""Testes de ``src.knowledge.vocabulary`` (``openspec/changes/v17-controlled-vocabulary``).

Usa ``InMemoryGraphStore`` e um CSV claramente fictício (``tests/fixtures/cnpq_areas_fixture.csv``);
a tabela oficial do CNPq não é usada nem reproduzida aqui.
"""

import shutil
from pathlib import Path

import pytest

from src.knowledge import vocabulary
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.normalization import normalize_domain_term, normalize_metric_name
from src.knowledge.provenance import Actor
from src.knowledge.vocabulary import (
    VocabularyError,
    VocabularySourceMissingError,
    approve_term,
    list_pending,
    map_term,
    reject_term,
    resolve_domain,
    resolve_metric,
    seed_vocabulary,
)

FIXTURE_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "cnpq_areas_fixture.csv"
REAL_METRICS = vocabulary.DEFAULT_VOCABULARY_DIR / vocabulary.METRICS_FILENAME
ORQ = Actor(kind="orquestrador")
CURATOR = Actor(kind="agente", role="curator", model="qwen3:8b")


@pytest.fixture
def vocab_dir(tmp_path):
    shutil.copy(FIXTURE_CSV, tmp_path / vocabulary.CNPQ_FILENAME)
    shutil.copy(REAL_METRICS, tmp_path / vocabulary.METRICS_FILENAME)
    return tmp_path


@pytest.fixture
def store(vocab_dir):
    s = InMemoryGraphStore()
    seed_vocabulary(s, vocabulary_dir=vocab_dir)
    return s


def _count(store, label):
    return len(store.find_nodes(label, {}, limit=10_000))


def _by(store, label, key, value):
    (node,) = store.find_nodes(label, {key: value})
    return node


# --- Carga -----------------------------------------------------------------


@pytest.mark.unit
def test_carga_idempotente(vocab_dir):
    """Scenario: Carga idempotente — duas execuções geram um único Dominio por codigo_cnpq."""
    s = InMemoryGraphStore()
    seed_vocabulary(s, vocabulary_dir=vocab_dir)
    n_dom, n_met = _count(s, "Dominio"), _count(s, "Metrica")
    n_edges = len(s._edges)
    second = seed_vocabulary(s, vocabulary_dir=vocab_dir)
    assert (_count(s, "Dominio"), _count(s, "Metrica"), len(s._edges)) == (n_dom, n_met, n_edges)
    assert second == {"dominios_criados": 0, "metricas_criadas": 0, "arestas_criadas": 0}
    assert n_dom == 4
    assert all(len(s.find_nodes("Dominio", {"codigo_cnpq": c})) == 1 for c in ("9.00.00.00-0", "9.01.01.00-2"))


@pytest.mark.unit
def test_carga_amplia_sinonimos_sem_duplicar(vocab_dir):
    """Reexecução com sinônimos novos no catálogo só amplia ``sinonimos`` do nó existente."""
    s = InMemoryGraphStore()
    seed_vocabulary(s, vocabulary_dir=vocab_dir)
    yaml_path = vocab_dir / vocabulary.METRICS_FILENAME
    yaml_path.write_text(
        "metricas:\n  - {nome: f1, sinonimos: [f1_score, dice], sentido: maior_melhor, familia: classificacao}\n",
        encoding="utf-8",
    )
    seed_vocabulary(s, vocabulary_dir=vocab_dir)
    assert len(s.find_nodes("Metrica", {"nome": "f1"})) == 1
    assert "dice" in _by(s, "Metrica", "nome", "f1").properties["sinonimos"]


@pytest.mark.unit
def test_hierarquia(store):
    """Scenario: Hierarquia — cada termo de nível inferior tem SUBAREA_DE para o pai."""
    sub = _by(store, "Dominio", "codigo_cnpq", "9.01.01.00-2")
    area = _by(store, "Dominio", "codigo_cnpq", "9.01.00.00-1")
    esp = _by(store, "Dominio", "codigo_cnpq", "9.01.01.01-3")
    sub_edges = store.neighbors(sub.id, ["SUBAREA_DE"], "out").edges
    assert any(e.dst_id == area.id and e.rel_type == "SUBAREA_DE" for e in sub_edges)
    assert any(e.dst_id == sub.id for e in store.neighbors(esp.id, ["SUBAREA_DE"], "out").edges)
    assert sub.properties["status"] == "aprovado"
    assert sub.properties["criado_por"] == "orquestrador"
    assert sub.properties["projeto_id"] == "__global__"


@pytest.mark.unit
def test_metricas_da_mesma_familia_relacionadas(store):
    """Métricas da mesma família são ligadas por RELACIONADA_A."""
    f1 = _by(store, "Metrica", "nome", "f1")
    acc = _by(store, "Metrica", "nome", "acuracia")
    edges = store.neighbors(f1.id, ["RELACIONADA_A"], "both").edges
    assert any({e.src_id, e.dst_id} == {f1.id, acc.id} for e in edges)


@pytest.mark.unit
def test_catalogo_inicial_completo():
    """O catálogo do design tem as 13 métricas com sentido e família."""
    metrics = vocabulary.load_metrics_catalog()
    assert len(metrics) == 13
    by_name = {m["nome"]: m for m in metrics}
    assert by_name["log_loss"]["sentido"] == "menor_melhor"
    assert by_name["r2"]["familia"] == "ajuste_regressao"


@pytest.mark.unit
def test_carga_falha_explicita_sem_tabela_cnpq(tmp_path):
    """Sem a tabela oficial do CNPq a carga falha (fail-fast) e não escreve nada."""
    shutil.copy(REAL_METRICS, tmp_path / vocabulary.METRICS_FILENAME)
    s = InMemoryGraphStore()
    with pytest.raises(VocabularySourceMissingError, match="fonte oficial do CNPq"):
        seed_vocabulary(s, vocabulary_dir=tmp_path)
    assert _count(s, "Metrica") == 0


@pytest.mark.unit
def test_tabela_cnpq_malformada_e_rejeitada(tmp_path):
    """CSV com cabeçalho errado, nível inválido ou pai inexistente falha com mensagem acionável."""
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(VocabularyError, match="Cabeçalho"):
        vocabulary.load_cnpq_table(path)
    path.write_text("codigo_cnpq,termo,nivel,codigo_pai\n1,T,invalido,\n", encoding="utf-8")
    with pytest.raises(VocabularyError, match="nivel"):
        vocabulary.load_cnpq_table(path)
    path.write_text("codigo_cnpq,termo,nivel,codigo_pai\n1,T,area,99\n", encoding="utf-8")
    with pytest.raises(VocabularyError, match="codigo_pai"):
        vocabulary.load_cnpq_table(path)


# --- Normalização e resolução ---------------------------------------------


@pytest.mark.unit
def test_normalizacao_compartilhada_com_validator():
    """O Validator usa a mesma função de normalização de métricas do vocabulário."""
    from src.agents import validator_agent

    assert validator_agent._normalize_metric_name("F1-Score") == normalize_metric_name("F1-Score") == "f1score"
    assert normalize_domain_term("Química  Orgânica") == "quimica_organica"


@pytest.mark.unit
def test_f1_variacoes_resolvem_para_f1(store):
    """Normalização: "F1-Score", "f1_score" e "F1" resolvem para `f1`."""
    f1 = _by(store, "Metrica", "nome", "f1")
    for name in ("F1-Score", "f1_score", "F1"):
        r = resolve_metric(store, name, actor=ORQ, sessao_id="s1")
        assert r.node_id == f1.id, name
    assert _count(store, "Metrica") == 13


@pytest.mark.unit
def test_sinonimo_resolvido(store):
    """Scenario: Sinônimo resolvido — "accuracy" resolve para `acuracia` (maior_melhor)."""
    r = resolve_metric(store, "accuracy", actor=ORQ, sessao_id="s1")
    node = store.get_node(r.node_id)
    assert r.status == "sinonimo"
    assert node.properties["nome"] == "acuracia"
    assert node.properties["sentido"] == "maior_melhor"
    assert resolve_metric(store, "acuracia", actor=ORQ, sessao_id="s1").status == "exato"
    assert resolve_metric(store, "r²", actor=ORQ, sessao_id="s1").node_id == _by(store, "Metrica", "nome", "r2").id


@pytest.mark.unit
def test_variacao_ortografica(store):
    """Scenario: Variação ortográfica — "Química Orgânica" e "quimica organica" retornam o mesmo nó."""
    a = resolve_domain(store, "Química Orgânica", actor=ORQ, sessao_id="s1")
    b = resolve_domain(store, "quimica organica", actor=ORQ, sessao_id="s1")
    assert a.node_id == b.node_id
    assert a.status == "exato"
    assert store.get_node(a.node_id).properties["codigo_cnpq"] == "9.01.01.00-2"


@pytest.mark.unit
def test_metrica_nova_cria_candidato_listado(store):
    """Scenario: Métrica nova — "indice_de_cristalinidade" cria Metrica candidata listada em `vocab pending`."""
    r = resolve_metric(store, "indice_de_cristalinidade", actor=ORQ, sessao_id="s1", sentido="maior_melhor")
    assert r.status == "candidato_criado"
    node = store.get_node(r.node_id)
    assert node.properties["status"] == "candidato"
    assert any(i["id"] == r.node_id and i["tipo"] == "termo" for i in list_pending(store))
    # Segunda resolução reaproveita o candidato (utilizável imediatamente, sem duplicar).
    again = resolve_metric(store, "Indice de Cristalinidade", actor=ORQ, sessao_id="s2")
    assert again.node_id == r.node_id and again.status == "exato"


@pytest.mark.unit
def test_metrica_candidata_sem_sentido_falha(store):
    """Candidato de métrica exige sentido: falha explícita e nada é criado."""
    before = _count(store, "Metrica")
    with pytest.raises(VocabularyError, match="sentido"):
        resolve_metric(store, "metrica_desconhecida", actor=ORQ, sessao_id="s1")
    assert _count(store, "Metrica") == before


@pytest.mark.unit
def test_area_emergente(store):
    """Scenario: Área emergente — Dominio candidato sem codigo_cnpq, utilizável imediatamente."""
    term = "computação quântica aplicada à química"
    r = resolve_domain(store, term, actor=CURATOR, sessao_id="s1")
    node = store.get_node(r.node_id)
    assert r.status == "candidato_criado"
    assert node.properties["status"] == "candidato"
    assert "codigo_cnpq" not in node.properties
    assert node.properties["criado_por"] == "curator/qwen3:8b"
    # utilizável: aresta NO_DOMINIO a partir de um Problema
    prob = store.create_node(
        "Problema", {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p1", "sessao_id": "s1"},
        actor=ORQ,
    )
    store.create_edge(prob, "NO_DOMINIO", r.node_id, {}, actor=ORQ)


@pytest.mark.unit
def test_semantico_acima_do_limiar_registra_sinonimo_candidato(store):
    """Passo semântico: similaridade >= VOCAB_MATCH_THRESHOLD usa o termo existente e registra sinônimo candidato."""
    target = _by(store, "Metrica", "nome", "rmse")
    r = resolve_metric(
        store, "raiz do erro quadratico medio", actor=ORQ, sessao_id="s1",
        semantic_search=lambda label, term: [(target.id, 0.95)],
    )
    assert r.status == "semantico" and r.node_id == target.id
    assert _by(store, "Metrica", "nome", "rmse").properties["sinonimos_candidatos"] == ["raiz do erro quadratico medio"]
    assert any(i["tipo"] == "sinonimo" and i["id"] == target.id for i in list_pending(store))


@pytest.mark.unit
def test_semantico_abaixo_do_limiar_cria_candidato_com_alternativas(store):
    """Similaridade abaixo do limiar não resolve: cria candidato e devolve alternativas para revisão."""
    target = _by(store, "Metrica", "nome", "rmse")
    r = resolve_metric(
        store, "outra coisa", actor=ORQ, sessao_id="s1", sentido="menor_melhor",
        semantic_search=lambda label, term: [(target.id, 0.5)],
    )
    assert r.status == "candidato_criado"
    assert r.alternativas == [(target.id, 0.5)]


@pytest.mark.unit
def test_sem_indice_semantico_passo_e_pulado(store):
    """Sem índice semântico a resolução segue correta, apenas sem o passo 3."""
    r = resolve_domain(store, "termo inexistente", actor=ORQ, sessao_id="s1")
    assert r.status == "candidato_criado" and r.alternativas == []


@pytest.mark.unit
def test_termo_vazio_falha(store):
    """Termo vazio é erro explícito."""
    with pytest.raises(VocabularyError):
        resolve_domain(store, "   ", actor=ORQ, sessao_id="s1")


# --- Decisão do pesquisador ------------------------------------------------


def _candidate(store, term="Termo Novo"):
    return resolve_domain(store, term, actor=CURATOR, sessao_id="s1").node_id


@pytest.mark.unit
def test_aprovar(store):
    """Scenario: Aprovar — candidato vira aprovado e a mudança é auditada com autor pesquisador."""
    cid = _candidate(store)
    approve_term(store, cid)
    assert store.get_node(cid).properties["status"] == "aprovado"
    assert store.audit_log[-1]["actor"] == "pesquisador"
    assert store.audit_log[-1]["node_id"] == cid
    with pytest.raises(VocabularyError):
        approve_term(store, cid)


@pytest.mark.unit
def test_rejeitar_nao_apaga(store):
    """`reject` marca rejeitado com motivo sem apagar o nó; rejeitado deixa de resolver."""
    cid = _candidate(store)
    n = _count(store, "Dominio")
    reject_term(store, cid, "fora de escopo")
    node = store.get_node(cid)
    assert node.properties["status"] == "rejeitado" and node.properties["motivo_decisao"] == "fora de escopo"
    assert _count(store, "Dominio") == n
    assert resolve_domain(store, "Termo Novo", actor=ORQ, sessao_id="s1").node_id != cid
    assert not [i for i in list_pending(store) if i["id"] == cid]


@pytest.mark.unit
def test_aprovar_e_rejeitar_sinonimos_candidatos(store):
    """`approve` promove sinônimos candidatos; `reject` os descarta."""
    t = _by(store, "Metrica", "nome", "rmse")
    sem = lambda label, term: [(t.id, 0.99)]  # noqa: E731
    resolve_metric(store, "raiz erro medio", actor=ORQ, sessao_id="s", semantic_search=sem)
    approve_term(store, t.id)
    props = store.get_node(t.id).properties
    assert "raiz erro medio" in props["sinonimos"] and props["sinonimos_candidatos"] == []
    assert resolve_metric(store, "raiz erro medio", actor=ORQ, sessao_id="s").status == "sinonimo"
    resolve_metric(store, "outro nome", actor=ORQ, sessao_id="s", semantic_search=sem)
    reject_term(store, t.id)
    assert store.get_node(t.id).properties["sinonimos_candidatos"] == []


@pytest.mark.unit
def test_mapear_para_termo_existente(store):
    """Scenario: Mapear — arestas passam ao canônico, termo vira sinônimo, candidato rejeitado com motivo."""
    canon = _by(store, "Dominio", "codigo_cnpq", "9.01.01.00-2").id
    cid = resolve_domain(store, "Quim. Organica Sintetica", actor=CURATOR, sessao_id="s1").node_id
    prob = store.create_node(
        "Problema", {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p1", "sessao_id": "s1"},
        actor=ORQ,
    )
    store.create_edge(prob, "NO_DOMINIO", cid, {}, actor=ORQ)
    n_nodes = _count(store, "Dominio")

    map_term(store, cid, canon)

    assert any(e.dst_id == canon for e in store.neighbors(prob, ["NO_DOMINIO"], "out").edges)
    assert "Quim. Organica Sintetica" in store.get_node(canon).properties["sinonimos"]
    cand = store.get_node(cid)
    assert cand.properties["status"] == "rejeitado"
    assert cand.properties["motivo_decisao"] == f"mapeado para {canon}"
    assert _count(store, "Dominio") == n_nodes
    assert resolve_domain(store, "Quim. Organica Sintetica", actor=ORQ, sessao_id="s").node_id == canon
    assert store.audit_log[-1]["actor"] == "pesquisador"


@pytest.mark.unit
def test_map_valida_entradas(store):
    """`map` recusa rótulos diferentes, não-candidato e mapeamento para si mesmo."""
    cid = _candidate(store)
    metric = _by(store, "Metrica", "nome", "f1").id
    area = _by(store, "Dominio", "codigo_cnpq", "9.01.00.00-1").id
    with pytest.raises(VocabularyError, match="Rótulos"):
        map_term(store, cid, metric)
    with pytest.raises(VocabularyError, match="não é candidato"):
        map_term(store, area, _by(store, "Dominio", "codigo_cnpq", "9.00.00.00-0").id)
    with pytest.raises(VocabularyError, match="si mesmo"):
        map_term(store, cid, cid)
    with pytest.raises(VocabularyError, match="não encontrado"):
        approve_term(store, "inexistente")


# --- CLI -------------------------------------------------------------------


@pytest.mark.unit
def test_cli_vocab_pending_approve_reject_map(store, capsys):
    """CLI `vocab pending|approve|reject|map` opera sobre o store com autor pesquisador."""
    from src.cli import _handle_vocab_command

    a = _candidate(store, "Candidato A")
    b = _candidate(store, "Candidato B")
    c = _candidate(store, "Candidato C")
    canon = _by(store, "Dominio", "codigo_cnpq", "9.01.01.00-2").id

    assert _handle_vocab_command(["pending"], store) == 0
    out = capsys.readouterr().out
    assert a in out and b in out and "Candidato C" in out

    assert _handle_vocab_command(["approve", a], store) == 0
    assert _handle_vocab_command(["reject", b, "--motivo", "duplicado"], store) == 0
    assert _handle_vocab_command(["map", c, "--para", canon], store) == 0
    assert store.get_node(a).properties["status"] == "aprovado"
    assert store.get_node(b).properties["motivo_decisao"] == "duplicado"
    assert store.get_node(c).properties["status"] == "rejeitado"

    assert _handle_vocab_command(["approve", a], store) == 1  # já aprovado: erro acionável
    capsys.readouterr()
    assert _handle_vocab_command(["pending"], store) == 0
    assert "Nenhum candidato" in capsys.readouterr().out


@pytest.mark.unit
def test_cli_vocab_argumentos_invalidos(store):
    """Subcomando ausente ou `map` sem --para sai com código diferente de zero."""
    from src.cli import _handle_vocab_command

    assert _handle_vocab_command([], store) != 0
    assert _handle_vocab_command(["map", "x"], store) != 0


@pytest.mark.unit
def test_config_vocab_match_threshold_default():
    """VOCAB_MATCH_THRESHOLD existe em config com default 0,90 e está em .env.example."""
    from src import config

    assert config.VOCAB_MATCH_THRESHOLD == 0.90
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    assert "VOCAB_MATCH_THRESHOLD=" in env_example.read_text(encoding="utf-8")
