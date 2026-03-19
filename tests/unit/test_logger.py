import json
import logging
import pytest
import io
from src.logger import get_logger, JsonFormatter

@pytest.fixture
def log_capture_stream():
    """Fixture para capturar a saída de log em um stream io.StringIO."""
    stream = io.StringIO()
    return stream

@pytest.mark.unit
def test_json_formatter_valid_json():
    """Testa se o JsonFormatter produz um JSON válido."""
    formatter = JsonFormatter()
    logger = logging.getLogger("test_json")
    record = logging.LogRecord(
        name="test_json",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Mensagem de teste",
        args=None,
        exc_info=None
    )
    result = formatter.format(record)
    
    # Verifica se é um JSON válido
    data = json.loads(result)
    assert data["message"] == "Mensagem de teste"
    assert data["level"] == "INFO"
    assert "timestamp" in data
    assert "event" in data

@pytest.mark.unit
def test_get_logger_singleton_handlers():
    """Testa se get_logger não duplica handlers."""
    logger_name = "test_singleton"
    logger1 = get_logger(logger_name)
    initial_handler_count = len(logger1.handlers)
    
    logger2 = get_logger(logger_name)
    assert len(logger2.handlers) == initial_handler_count
    assert logger1 is logger2

@pytest.mark.unit
def test_logger_output_contains_required_fields(log_capture_stream):
    """Testa se a saída do log contém os campos obrigatórios."""
    logger = get_logger("test_fields")
    
    # Adiciona stream handler temporário para captura
    handler = logging.StreamHandler(log_capture_stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    
    logger.info("Teste de campos", extra={"event": "custom_event"})
    
    output = log_capture_stream.getvalue()
    data = json.loads(output)
    
    assert data["message"] == "Teste de campos"
    assert data["level"] == "INFO"
    assert data["event"] == "custom_event"
    assert "timestamp" in data
    
    # Limpa handlers após o teste
    logger.removeHandler(handler)

@pytest.mark.unit
def test_logger_extra_fields(log_capture_stream):
    """Testa se campos extras são incluídos no JSON."""
    logger = get_logger("test_extra")
    
    handler = logging.StreamHandler(log_capture_stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    
    # Injected extra fields via dict
    logger.info("Teste extra", extra={"extra": {"uid": "123", "action": "login"}})
    
    output = log_capture_stream.getvalue()
    data = json.loads(output)
    
    assert data["uid"] == "123"
    assert data["action"] == "login"
    
    logger.removeHandler(handler)
