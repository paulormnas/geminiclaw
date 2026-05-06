"""Testes unitários para scripts/github_app_auth.py.

Valida a geração do JWT e a troca pelo Installation Token,
sem realizar chamadas reais à API do GitHub.
"""
import importlib
import pytest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def rsa_keypair(tmp_path):
    """Gera um par de chaves RSA efêmero para os testes.

    Returns:
        tuple[Path, RSAPrivateKey]: Caminho do arquivo .pem e a chave privada.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "test-app.pem"
    key_file.write_bytes(pem_bytes)
    return key_file, private_key


@pytest.fixture()
def env_vars(monkeypatch, rsa_keypair):
    """Injeta as variáveis de ambiente necessárias para o módulo."""
    key_file, private_key = rsa_keypair
    monkeypatch.setenv("GITHUB_APP_ID", "999")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "111222")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setenv("GITHUB_REPO", "paulormnas/geminiclaw")
    return private_key


# ---------------------------------------------------------------------------
# Testes de generate_jwt()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_jwt_contains_correct_issuer(env_vars):
    """JWT deve conter 'iss' igual ao GITHUB_APP_ID configurado."""
    import jwt as pyjwt

    import scripts.github_app_auth as mod
    importlib.reload(mod)

    private_key = env_vars
    token = mod.generate_jwt()
    public_key = private_key.public_key()
    decoded = pyjwt.decode(token, public_key, algorithms=["RS256"])

    assert decoded["iss"] == "999"


@pytest.mark.unit
def test_jwt_expiry_within_11_minutes(env_vars):
    """JWT deve expirar em no máximo 11 minutos (600s + 60s de skew)."""
    import jwt as pyjwt

    import scripts.github_app_auth as mod
    importlib.reload(mod)

    private_key = env_vars
    token = mod.generate_jwt()
    public_key = private_key.public_key()
    decoded = pyjwt.decode(token, public_key, algorithms=["RS256"])

    duration = decoded["exp"] - decoded["iat"]
    assert duration <= 660, f"Duração do JWT ({duration}s) excede 660s"


@pytest.mark.unit
def test_jwt_fails_if_pem_not_found(monkeypatch, tmp_path):
    """generate_jwt() deve encerrar com SystemExit se o .pem não existir."""
    monkeypatch.setenv("GITHUB_APP_ID", "999")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "111")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(tmp_path / "nao_existe.pem"))

    import scripts.github_app_auth as mod
    importlib.reload(mod)

    with pytest.raises(SystemExit):
        mod.generate_jwt()


# ---------------------------------------------------------------------------
# Testes de get_installation_token()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_installation_token_returns_token(env_vars):
    """get_installation_token() deve retornar o valor do campo 'token' da resposta."""
    import scripts.github_app_auth as mod
    importlib.reload(mod)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"token": "ghs_abc123_test_token"}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp):
        result = mod.get_installation_token()

    assert result == "ghs_abc123_test_token"


@pytest.mark.unit
def test_get_installation_token_uses_installation_id_in_url(env_vars):
    """A URL da chamada à API deve conter o GITHUB_APP_INSTALLATION_ID."""
    import scripts.github_app_auth as mod
    importlib.reload(mod)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"token": "ghs_xyz"}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        mod.get_installation_token()

    call_url = mock_post.call_args[0][0]
    assert "111222" in call_url, f"Installation ID não encontrado na URL: {call_url}"


@pytest.mark.unit
def test_get_installation_token_sends_bearer_jwt(env_vars):
    """O header Authorization deve conter 'Bearer <jwt>'."""
    import scripts.github_app_auth as mod
    importlib.reload(mod)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"token": "ghs_xyz"}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        mod.get_installation_token()

    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"].startswith("Bearer "), (
        f"Header Authorization inválido: {headers.get('Authorization')}"
    )


@pytest.mark.unit
def test_get_installation_token_raises_on_http_error(env_vars):
    """get_installation_token() deve propagar HTTPStatusError em caso de erro da API."""
    import httpx

    import scripts.github_app_auth as mod
    importlib.reload(mod)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=mock_resp
    )

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(httpx.HTTPStatusError):
            mod.get_installation_token()


# ---------------------------------------------------------------------------
# Teste de _check_env()
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_env_exits_when_variable_missing(monkeypatch):
    """_check_env() deve encerrar com SystemExit se alguma variável estiver ausente."""
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY_PATH", raising=False)

    import scripts.github_app_auth as mod
    importlib.reload(mod)

    with pytest.raises(SystemExit):
        mod._check_env()
