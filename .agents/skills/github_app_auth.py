"""Gera Installation Token para o GitHub App do GeminiClaw.

Este script autentica o agente da IDE como colaborador do repositório
`geminiclaw` via GitHub App, gerando um token temporário (válido por 1h)
que pode ser usado pelo `gh` CLI e pelo `git push`.

Uso:
    # Exportar token e autenticar o gh CLI
    export GH_TOKEN=$(uv run python scripts/github_app_auth.py)

    # Configurar remote com token (para git push)
    REPO=$(grep GITHUB_REPO .env | cut -d= -f2)
    git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"

Variáveis de ambiente necessárias (.env):
    GITHUB_APP_ID               -- ID numérico do GitHub App
    GITHUB_APP_INSTALLATION_ID  -- ID da instalação no repositório
    GITHUB_APP_PRIVATE_KEY_PATH -- Caminho absoluto para o arquivo .pem
"""
import os
import sys
import time
from pathlib import Path

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()

_REQUIRED_ENVS = [
    "GITHUB_APP_ID",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_APP_PRIVATE_KEY_PATH",
]


def _check_env() -> None:
    """Verifica se todas as variáveis obrigatórias estão definidas.

    Raises:
        SystemExit: Se alguma variável estiver ausente.
    """
    missing = [k for k in _REQUIRED_ENVS if not os.environ.get(k)]
    if missing:
        print(
            f"[github_app_auth] Variáveis ausentes: {', '.join(missing)}\n"
            "Configure-as no arquivo .env antes de continuar.",
            file=sys.stderr,
        )
        sys.exit(1)


def generate_jwt() -> str:
    """Gera um JWT assinado com a private key do GitHub App.

    O JWT é válido por 10 minutos e é usado para obter o Installation Token.

    Returns:
        str: JWT codificado em Base64URL.

    Raises:
        FileNotFoundError: Se o arquivo .pem não existir no caminho configurado.
        jwt.exceptions.PyJWTError: Se a chave privada for inválida.
    """
    app_id = os.environ["GITHUB_APP_ID"]
    key_path = Path(os.environ["GITHUB_APP_PRIVATE_KEY_PATH"])

    if not key_path.exists():
        print(
            f"[github_app_auth] Chave privada não encontrada em: {key_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    now = int(time.time())
    payload = {
        "iat": now - 60,   # emitido há 60s para tolerar skew de relógio
        "exp": now + 600,  # expira em 10 minutos
        "iss": app_id,
    }
    return jwt.encode(payload, key_path.read_text(), algorithm="RS256")


def get_installation_token() -> str:
    """Troca o JWT por um Installation Token via API do GitHub.

    O token resultante (prefixo `ghs_`) é válido por 1 hora e pode ser
    usado diretamente pelo `gh` CLI (via GH_TOKEN) e pelo `git push`.

    Returns:
        str: Installation Token com prefixo `ghs_`.

    Raises:
        httpx.HTTPStatusError: Se a API do GitHub retornar erro HTTP.
        KeyError: Se a resposta não contiver o campo `token`.
    """
    installation_id = os.environ["GITHUB_APP_INSTALLATION_ID"]
    app_jwt = generate_jwt()

    resp = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["token"]


if __name__ == "__main__":
    _check_env()
    try:
        token = get_installation_token()
        # Imprimir apenas o token — sem newline extra — para uso em subshell
        print(token, end="")
    except httpx.HTTPStatusError as exc:
        print(
            f"[github_app_auth] Erro da API GitHub: {exc.response.status_code} — {exc.response.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"[github_app_auth] Erro inesperado: {exc}", file=sys.stderr)
        sys.exit(1)
