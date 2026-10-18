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


# v18.7-agent-system-prompts (ADR 022 §4.2): todo prompt de papel tem as mesmas seções, nesta ordem.
SECOES_DO_PROMPT = (
    "Papel",
    "O que você recebe",
    "O que você produz",
    "Ferramentas",
    "Como você é avaliado",
    "Regras do papel",
)


def montar_prompt(*, papel: str, recebe: str, produz: str, ferramentas: str, avaliado: str, regras: str) -> str:
    """Monta o prompt de um papel com as seis seções padrão, cada uma com o título em linha própria.

    O que é comum a todos os papéis fica no regimento e não se repete aqui (ADR 022 §4.1).
    """
    corpos = (papel, recebe, produz, ferramentas, avaliado, regras)
    blocos = (f"{titulo}\n{corpo.strip()}" for titulo, corpo in zip(SECOES_DO_PROMPT, corpos, strict=True))
    return "\n\n".join(blocos) + "\n"


def regras_de_seguranca(destino: str) -> str:
    """Texto, em lista, das regras de segurança do regimento cujo destino inclui ``destino`` (um papel).

    O texto renderizado de cada regra é o marcador que o teste de regras de segurança procura no prompt do papel.
    """
    from src.agents.regimento import carregar_regimento, regras_seguranca

    regras = regras_seguranca(carregar_regimento().estrutura, destino)
    return "\n".join(f"- {r['texto']}" for r in regras)
