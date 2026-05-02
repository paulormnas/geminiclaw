import os
import logging
import json
import datetime
from pathlib import Path
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
        # O logging padrão coloca o conteúdo de 'extra={...}' diretamente no record.__dict__
        # Mas alguns testes passam 'extra={"extra": {...}}', então vamos achatar se necessário.
        standard_fields = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "timestamp", "level", "event"
        }
        
        for key, value in record.__dict__.items():
            if key not in standard_fields:
                if key == "extra" and isinstance(value, dict):
                    log_data.update(value)
                else:
                    log_data[key] = value

        return json.dumps(log_data)

def get_logger(name: str) -> logging.Logger:
    """Retorna um logger configurado com o formatador JSON.

    Args:
        name: O nome do logger.

    Returns:
        Um objeto logging.Logger configurado.
    """
    logger = logging.getLogger(name)
    
    # Define o nível de log baseado na variável de ambiente LOG_LEVEL
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logger.setLevel(log_level)

    # Evita duplicar handlers de stream
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    return logger

def setup_file_logging(log_path: str) -> None:
    """Configura o logger raiz para escrever em um arquivo JSON.

    Args:
        log_path: Caminho para o arquivo de log.
    """
    root_logger = logging.getLogger()
    
    # Verifica se já não tem um FileHandler para este path
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and h.baseFilename == str(Path(log_path).absolute())
        for h in root_logger.handlers
    )
    
    if not has_file_handler:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(JsonFormatter())
            root_logger.addHandler(file_handler)
            # Garante que o nível do root logger permita INFO
            if root_logger.level > logging.INFO:
                root_logger.setLevel(logging.INFO)
            root_logger.info(f"Log em arquivo ativado: {log_path}")
        except Exception as e:
            # Se falhar ao criar arquivo de log, usamos o logger padrão para avisar
            get_logger(__name__).error(f"Não foi possível criar arquivo de log: {e}")
