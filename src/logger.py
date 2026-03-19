import logging
import json
import datetime
from typing import Any

class JsonFormatter(logging.Formatter):
    """Formatador de logs em JSON estruturado."""

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro de log como uma string JSON.

        Args:
            record: O registro de log a ser formatado.

        Returns:
            Uma string JSON contendo os campos do log.
        """
        log_data = {
            "timestamp": datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "event": getattr(record, "event", "log_message"),
        }

        # Adiciona campos extras se presentes
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        return json.dumps(log_data)

def get_logger(name: str) -> logging.Logger:
    """Retorna um logger configurado com o formatador JSON.

    Args:
        name: O nome do logger.

    Returns:
        Um objeto logging.Logger configurado.
    """
    logger = logging.getLogger(name)
    
    # Define o nível de log para INFO por padrão
    logger.setLevel(logging.INFO)

    # Evita duplicar handlers se get_logger for chamado múltiplas vezes para o mesmo nome
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    return logger
