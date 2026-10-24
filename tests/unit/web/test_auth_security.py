"""Login, sessões, bloqueio, CSRF, origem, host e cabeçalhos (spec web-interface)."""

import pytest

from src.utils.configuration_error import ConfigurationError
from src.web.auth import PasswordVerifier
from tests.unit.web.conftest import ORIGIN, PASSWORD

pytestmark = pytest.mark.unit


def login(client, senha=PASSWORD, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.post("/api/session/login", json={"senha": senha}, headers=headers)


def test_senha_correta_emite_cookie_httponly_strict(client) -> None:
    r = login(client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "gc_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert r.json()["csrf_token"] not in r.headers["set-cookie"]


def test_cookie_seguro_usa_prefixo_host(make_client) -> None:
    c = make_client(cookie_secure=True)
    r = c.post("/api/session/login", json={"senha": PASSWORD}, headers={"Origin": ORIGIN})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-gc_session=") and "Secure" in cookie


def test_senha_errada(client) -> None:
    r = login(client, "errada")
    assert r.status_code == 401 and r.json()["erro"] == "credenciais_invalidas"
    assert "set-cookie" not in r.headers


def test_rota_protegida_sem_sessao(client) -> None:
    assert client.get("/api/projects").status_code == 401


def test_expira_por_inatividade(client, clock, auth) -> None:
    assert client.get("/api/session").status_code == 200
    clock.advance(61 * 60)
    assert client.get("/api/session").status_code == 401


def test_expira_por_idade_mesmo_com_uso(client, clock, auth) -> None:
    for _ in range(13):
        clock.advance(59 * 60)
        client.get("/api/session")
    assert client.get("/api/session").status_code == 401


def test_logout(client, auth) -> None:
    assert client.post("/api/session/logout", headers=auth).status_code == 204
    assert client.get("/api/session").status_code == 401


def test_quinta_falha_bloqueia_ate_com_senha_certa(client, clock) -> None:
    for _ in range(5):
        assert login(client, "errada").status_code in (401, 429)
    blocked = login(client)
    assert blocked.status_code == 429 and blocked.json()["tentar_em_segundos"] > 0
    clock.advance(301)
    assert login(client).status_code == 200


def test_sessoes_esgotadas_nao_derruba_a_existente(make_client) -> None:
    c = make_client(max_sessions=1)
    assert login(c).status_code == 200
    r = login(c)
    assert r.status_code == 429 and r.json()["erro"] == "sessoes_esgotadas"
    assert c.get("/api/session").status_code == 200


def test_post_sem_csrf(client, auth) -> None:
    r = client.post("/api/projects", json={"titulo": "x", "objetivo": "y"}, headers={"Origin": ORIGIN})
    assert r.status_code == 403


def test_origem_estranha(client, auth) -> None:
    r = client.post("/api/projects", json={"titulo": "x", "objetivo": "y"},
                    headers={**auth, "Origin": "https://exemplo.invalid"})
    assert r.status_code == 403


def test_login_sem_origin(client) -> None:
    r = login(client, origin=None)
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_host_fora_da_lista(client) -> None:
    assert client.get("/api/session", headers={"Host": "atacante.invalid"}).status_code == 400


def test_cabecalhos_de_seguranca(client, tmp_path) -> None:
    for path in ("/", "/api/session"):
        r = client.get(path)
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
    assert client.get("/api/session").headers["cache-control"] == "no-store"


def test_get_nunca_escreve(client, auth, store) -> None:
    writes: list[str] = []
    for name in ("create_node", "update_node", "create_edge"):
        original = getattr(store, name)
        setattr(store, name, lambda *a, _n=name, _o=original, **k: (writes.append(_n), _o(*a, **k))[1])
    routes = [r for r in client.app.routes if "GET" in getattr(r, "methods", ())]
    for route in routes:
        path = route.path.replace("{projeto_id}", "00000000-0000-0000-0000-000000000000").replace("{path:path}", "x")
        client.get(path)
    assert writes == []


def test_excecao_interna_sem_vazar(make_client, caplog) -> None:
    def broken():
        raise RuntimeError("/Users/x/segredo")

    c = make_client()
    c.app.state.web.store._factory = broken
    r = c.post("/api/session/login", json={"senha": PASSWORD}, headers={"Origin": ORIGIN})
    headers = {"Origin": ORIGIN, "X-CSRF-Token": r.json()["csrf_token"]}
    resp = c.get("/api/projects")
    assert resp.status_code == 500 and resp.json() == {"erro": "interno", "mensagem": "Erro interno."}
    assert "segredo" not in resp.text
    assert "segredo" not in caplog.text and "gc_session" not in caplog.text
    assert headers


def test_hash_malformado_impede_inicializacao() -> None:
    with pytest.raises(ConfigurationError, match="malformado"):
        PasswordVerifier("$argon2id$lixo")
