"""Parser tolerante a falhas para extrair JSON de respostas de LLMs.

LLMs frequentemente emitem JSON envolvido em blocos markdown, precedido de
texto introdutório, com trailing commas ou comentários inline. Esta função
normaliza todas essas variantes antes de tentar o parse.
"""

import json
import re
from typing import Union

from src.logger import get_logger

logger = get_logger(__name__)

# Tipo de retorno: dict, list ou None quando o parse falha
JsonValue = Union[dict, list, None]


def extract_json(text: str) -> JsonValue:
    """Extrai o primeiro objeto JSON válido do texto fornecido.

    Estratégias aplicadas em ordem crescente de intervenção:
    1. ``json.loads`` direto — sem transformação alguma.
    2. Remoção de blocos de código markdown (`` ```json ... ``` ``).
    3. Extração pelo primeiro delimitador ``[`` / ``{`` usando contagem
       de balanceamento para encontrar o par fechador correto.
    4. Remoção de trailing commas e comentários inline ``// ...``.

    Emite log de warning sempre que alguma limpeza for necessária.

    Args:
        text: Texto bruto retornado pelo LLM.

    Returns:
        O objeto Python (dict ou list) ou ``None`` quando nenhuma estratégia
        conseguiu produzir JSON válido.
    """
    if not text or not text.strip():
        return None

    # Verificação rápida: se não houver { ou [, não é JSON (silencioso)
    if "{" not in text and "[" not in text:
        return None

    # Estratégia 1 — parse direto (caminho feliz, sem log)
    result = _try_loads(text)
    if result is not None:
        return result

    cleaned = text

    # Estratégia 2 — remover blocos de código markdown
    stripped = _strip_markdown_fences(cleaned)
    if stripped != cleaned:
        logger.warning(
            "JSON extraído de bloco markdown",
            extra={"original_len": len(cleaned), "stripped_len": len(stripped)},
        )
        cleaned = stripped
        result = _try_loads(cleaned)
        if result is not None:
            return result

    # Estratégia 3 — extrair pela contagem de delimitadores balanceados
    balanced = _extract_balanced(cleaned)
    if balanced is not None and balanced != cleaned.strip():
        logger.warning(
            "JSON extraído por contagem de delimitadores balanceados",
            extra={"extracted_len": len(balanced)},
        )
        result = _try_loads(balanced)
        if result is not None:
            return result
            
        # Tenta sanitizar o bloco extraído, pois pode conter trailing commas
        sanitized_balanced = _sanitize(balanced)
        result = _try_loads(sanitized_balanced)
        if result is not None:
            return result
        
        # Se não deu certo, NÃO sobrescreve 'cleaned' com 'balanced', 
        # pois o bloco extraído provavelmente não era o JSON real.
    sanitized = _sanitize(cleaned)
    if sanitized != cleaned:
        logger.warning(
            "JSON sanitizado (trailing commas / comentários removidos)",
            extra={"sanitized_len": len(sanitized)},
        )
        result = _try_loads(sanitized)
        if result is not None:
            return result

    logger.warning(
        "Falha ao extrair JSON após todas as estratégias",
        extra={"text_preview": text[:200]},
    )
    return None


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _try_loads(text: str) -> JsonValue:
    """Tenta ``json.loads`` e retorna None em caso de falha."""
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _strip_markdown_fences(text: str) -> str:
    """Remove blocos de código markdown (```json ... ``` ou ``` ... ```)."""
    # Captura o conteúdo dentro de qualquer bloco de código
    pattern = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return text


def _extract_balanced(text: str) -> str | None:
    """Extrai a substring JSON usando contagem de balanceamento de delimitadores.

    Localiza o primeiro ``[`` ou ``{`` no texto e avança caractere a caractere
    mantendo contagem de abertura/fechamento para encontrar o fechador correto.
    Isso é mais robusto do que o regex greedy `[\\[{].*[\\]}]`.

    Args:
        text: Texto possivelmente rodeado por conteúdo não-JSON.

    Returns:
        Substring correspondente ao JSON balanceado, ou ``None`` se não
        encontrado.
    """
    open_chars = {"{": "}", "[": "]"}
    close_chars = set(open_chars.values())

    start = -1
    open_char: str | None = None

    for i, ch in enumerate(text):
        if ch in open_chars:
            start = i
            open_char = ch
            break

    if start == -1 or open_char is None:
        return None

    close_char = open_chars[open_char]
    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def _sanitize(text: str) -> str:
    """Remove trailing commas e comentários inline que invalidam o JSON.

    Exemplos tratados:
    - ``{"key": "val",}``  → ``{"key": "val"}``
    - ``[1, 2, 3,]``       → ``[1, 2, 3]``
    - ``{"k": 1 // nota}`` → ``{"k": 1 }``
    """
    # Remove comentários inline // até o fim da linha (fora de strings)
    text = re.sub(r"(?<![\"'])//[^\n]*", "", text)

    # Remove trailing comma antes de ] ou }
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text.strip()
