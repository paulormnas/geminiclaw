from src.llm.base import LLMProvider


def get_provider() -> LLMProvider:
    """Provedor do papel ``researcher``, obtido pelo roteador (ADR 017 §10).

    Mantido por compatibilidade com chamadores sem papel (laço de agente sem provedor
    explícito, triagem). Não há mais singleton nem leitura de ``LLM_PROVIDER``/``LLM_MODEL``.
    """
    from src.model_router import ModelRouter

    return ModelRouter.get_provider()
