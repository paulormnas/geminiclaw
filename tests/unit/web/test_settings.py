"""Configuração da web: loopback, hash, cookie seguro (spec: Servidor só em loopback)."""

import pytest

from src.utils.configuration_error import ConfigurationError
from src.web.settings import load_web_settings

HASH = "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$aGFzaA"

pytestmark = pytest.mark.unit


def env(**kw: str) -> dict[str, str]:
    return {"WEB_PASSWORD_HASH": HASH, **kw}


def test_padroes_validos() -> None:
    s = load_web_settings(env())
    assert (s.host, s.port, s.cookie_name) == ("127.0.0.1", 8765, "gc_session")
    assert s.allowed_origins == ("http://127.0.0.1:8765", "http://localhost:8765")


def test_endereco_externo_recusado() -> None:
    with pytest.raises(ConfigurationError, match="WEB_HOST.*tailscale serve"):
        load_web_settings(env(WEB_HOST="0.0.0.0"))


def test_nome_da_tailnet_sem_cookie_seguro() -> None:
    with pytest.raises(ConfigurationError, match="WEB_COOKIE_SECURE=true"):
        load_web_settings(env(WEB_ALLOWED_HOSTS="127.0.0.1,mac.tailnet.ts.net"))


def test_nome_da_tailnet_com_cookie_seguro() -> None:
    s = load_web_settings(env(WEB_ALLOWED_HOSTS="127.0.0.1,mac.tailnet.ts.net", WEB_COOKIE_SECURE="true"))
    assert s.cookie_name == "__Host-gc_session"
    assert "https://mac.tailnet.ts.net" in s.allowed_origins


def test_sem_hash() -> None:
    with pytest.raises(ConfigurationError, match="src.web.password"):
        load_web_settings({})


def test_hash_que_nao_e_argon2id() -> None:
    with pytest.raises(ConfigurationError, match=r"\$argon2id\$"):
        load_web_settings({"WEB_PASSWORD_HASH": "abc"})


@pytest.mark.parametrize("port", ["80", "70000", "abc"])
def test_porta_invalida(port: str) -> None:
    with pytest.raises(ConfigurationError, match="WEB_PORT"):
        load_web_settings(env(WEB_PORT=port))
