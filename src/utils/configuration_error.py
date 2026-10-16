"""Erro de configuração, fora de ``src.config`` para continuar a mesma classe quando ``src.config`` é reimportado."""


class ConfigurationError(RuntimeError):
    """Configuração inválida ou removida: a inicialização falha com a mensagem do que fazer."""
