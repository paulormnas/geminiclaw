"""Gera o hash argon2id da senha da web: ``uv run python -m src.web.password`` (a senha não aparece nem é gravada)."""

from __future__ import annotations

import getpass
import sys

from argon2 import PasswordHasher

MIN_LENGTH = 12


def main() -> int:
    first = getpass.getpass("Senha da interface web: ")
    if len(first) < MIN_LENGTH:
        print(f"A senha deve ter ao menos {MIN_LENGTH} caracteres.", file=sys.stderr)
        return 1
    if first != getpass.getpass("Repita a senha: "):
        print("As senhas não conferem.", file=sys.stderr)
        return 1
    print("Acrescente ao .env (entre aspas simples, o hash tem '$'):")
    print(f"WEB_PASSWORD_HASH='{PasswordHasher().hash(first)}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
