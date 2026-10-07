"""Arquivos de registro do orquestrador em ``outputs/<sessão>/`` que nenhuma ferramenta de agente pode escrever.

O orquestrador e o Curator leem estes arquivos como registros próprios (sugestões e respostas; sinalizações). Se o
código gerado pelo LLM pudesse gravá-los, forjaria sugestões aprovadas ou sinalizações. A camada de escrita dos agentes
(o sandbox de código) recusa estes nomes, sem distinguir caixa (sistemas de arquivos insensíveis a caixa os unificam).
"""

from __future__ import annotations

RESERVED_SESSION_FILES: frozenset[str] = frozenset({"curator_suggestions.jsonl", "curator_flags.jsonl"})


def is_reserved_name(name: str) -> bool:
    """``True`` se ``name`` (qualquer caixa) é um arquivo de registro reservado do orquestrador."""
    return name.casefold() in RESERVED_SESSION_FILES
