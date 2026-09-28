"""Renderização de templates de instrução dos agentes (Roadmap V16 / ADR 011).

Centraliza a substituição de marcadores nos templates de instrução dos
agentes, para que o nome do produto (`config.APP_NAME`) seja injetado a
partir de uma única fonte de verdade em vez de ser repetido literalmente em
cada módulo de agente (`agents/*/agent.py`).
"""

from src import config


def render_instruction(template: str, **extra: str) -> str:
    """Renderiza um template de instrução substituindo marcadores por valores.

    Usa substituição literal de marcadores (ex.: ``{app_name}``) em vez de
    `str.format()`, porque os templates de instrução dos agentes contêm
    exemplos de plano em JSON com chaves (`{`, `}`) que não podem ser
    tratadas como placeholders de formatação.

    Args:
        template: Texto do template de instrução, contendo marcadores como
            ``{app_name}``.
        **extra: Marcadores adicionais a substituir, no formato
            ``nome_do_marcador=valor``.

    Returns:
        O texto do template com os marcadores substituídos pelos valores
        correspondentes. Marcadores sem valor correspondente permanecem
        inalterados no texto.
    """
    rendered = template.replace("{app_name}", config.APP_NAME)
    for key, value in extra.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered
