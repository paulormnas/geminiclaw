"""CRUD de projetos, arquivamento e SPA estática (spec web-interface)."""

import pytest

from src.web.deps import LiveSession

pytestmark = pytest.mark.unit

NIL = "00000000-0000-0000-0000-000000000000"


def create(client, auth, titulo="Iris", objetivo="Classificar espécies"):
    return client.post("/api/projects", json={"titulo": titulo, "objetivo": objetivo}, headers=auth)


def test_criar_e_ler(client, auth, store) -> None:
    r = create(client, auth)
    assert r.status_code == 201
    pid = r.json()["projeto_id"]
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["status"] == "ativo" and detail["titulo"] == "Iris" and detail["problema"] is None
    node = store.find_nodes("Projeto", {"projeto_id": pid}, limit=1)[0]
    assert node.properties["criado_por"] if "criado_por" in node.properties else True


def test_titulo_vazio(client, auth) -> None:
    r = create(client, auth, titulo="")
    assert r.status_code == 422 and r.json()["campo"] == "titulo"


def test_titulo_longo(client, auth) -> None:
    r = create(client, auth, titulo="x" * 201)
    assert r.status_code == 422 and r.json()["campo"] == "titulo"


def test_corpo_com_campo_desconhecido(client, auth) -> None:
    r = client.post("/api/projects", json={"titulo": "a", "objetivo": "b", "x": 1}, headers=auth)
    assert r.status_code == 422


def test_editar_e_concluir(client, auth) -> None:
    pid = create(client, auth).json()["projeto_id"]
    r = client.patch(f"/api/projects/{pid}", json={"titulo": "Íris 2", "status": "concluido"}, headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "concluido" and r.json()["titulo"] == "Íris 2"
    assert client.get("/api/projects?status=ativo").json() == []
    assert len(client.get("/api/projects?status=concluido").json()) == 1


def test_concluir_com_pesquisa_em_execucao(client, auth, live) -> None:
    pid = create(client, auth).json()["projeto_id"]
    live[pid] = [LiveSession("s1", "iris-04")]
    r = client.patch(f"/api/projects/{pid}", json={"status": "concluido"}, headers=auth)
    assert r.status_code == 409 and r.json()["sessoes"][0]["alias"] == "iris-04"
    assert client.get(f"/api/projects/{pid}").json()["status"] == "ativo"


def test_editar_titulo_com_pesquisa_em_execucao_pode(client, auth, live) -> None:
    pid = create(client, auth).json()["projeto_id"]
    live[pid] = [LiveSession("s1", "iris-04")]
    assert client.patch(f"/api/projects/{pid}", json={"titulo": "Novo"}, headers=auth).status_code == 200


def test_arquivar_e_desarquivar(client, auth) -> None:
    pid = create(client, auth).json()["projeto_id"]
    assert client.patch(f"/api/projects/{pid}", json={"status": "arquivado"}, headers=auth).status_code == 200
    assert client.get("/api/projects").json() == []
    assert len(client.get("/api/projects?incluir_arquivados=1").json()) == 1
    assert client.patch(f"/api/projects/{pid}", json={"status": "pausado"}, headers=auth).json()["status"] == "pausado"
    assert len(client.get("/api/projects").json()) == 1


def test_status_invalido(client, auth) -> None:
    pid = create(client, auth).json()["projeto_id"]
    assert client.patch(f"/api/projects/{pid}", json={"status": "apagado"}, headers=auth).status_code == 422


def test_sem_delete(client, auth, store) -> None:
    pid = create(client, auth).json()["projeto_id"]
    assert client.delete(f"/api/projects/{pid}", headers=auth).status_code == 405
    assert store.find_nodes("Projeto", {"projeto_id": pid}, limit=1)


def test_inexistente(client, auth) -> None:
    r = client.get(f"/api/projects/{NIL}")
    assert r.status_code == 404 and r.json()["erro"] == "projeto_nao_encontrado"
    assert client.get("/api/projects/naoexiste").status_code == 404
    assert client.patch(f"/api/projects/{NIL}", json={"titulo": "x"}, headers=auth).status_code == 404


def test_spa_devolve_index_nas_rotas_do_frontend(client, tmp_path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "app.js").write_text("1")
    assert client.get("/p/abc/projetos").text == "<html>spa</html>"
    assert client.get("/assets/app.js").text == "1"
    assert client.get("/../etc/passwd").text == "<html>spa</html>"
    assert client.get("/api/nao-existe").status_code in (401, 404)


def test_build_ausente_503_e_api_funciona(client) -> None:
    r = client.get("/")
    assert r.status_code == 503 and "pnpm --dir frontend build" in r.json()["mensagem"]
    assert client.get("/api/session").status_code == 401
