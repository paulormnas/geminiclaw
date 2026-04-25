import pytest
import respx
import httpx
import json
from src.llm.providers.ollama import OllamaProvider
from src.llm.base import ToolCall

@pytest.mark.asyncio
async def test_ollama_generate_success():
    """Valida geração bem-sucedida no OllamaProvider."""
    base_url = "http://localhost:11434"
    model = "qwen3.5:4b"
    provider = OllamaProvider(base_url, model)

    payload = {
        "model": model,
        "message": {
            "role": "assistant",
            "content": "Olá! Como posso ajudar?",
        },
        "done": True,
        "eval_count": 10
    }

    async with respx.mock:
        respx.post(f"{base_url}/api/chat").mock(return_value=httpx.Response(200, json=payload))
        
        response = await provider.generate(messages=[{"role": "user", "content": "Oi"}])
        
        assert response.text == "Olá! Como posso ajudar?"
        assert response.finish_reason == "stop"
        assert response.usage["completion_tokens"] == 10

@pytest.mark.asyncio
async def test_ollama_generate_with_tool_calls():
    """Valida conversão de tool calls no OllamaProvider."""
    base_url = "http://localhost:11434"
    model = "qwen3.5:4b"
    provider = OllamaProvider(base_url, model)

    payload = {
        "model": model,
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "function": {
                        "name": "get_weather",
                        "arguments": {"location": "São Paulo"}
                    }
                }
            ]
        },
        "done": True
    }

    async with respx.mock:
        respx.post(f"{base_url}/api/chat").mock(return_value=httpx.Response(200, json=payload))
        
        response = await provider.generate(messages=[{"role": "user", "content": "Tempo em SP"}])
        
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"location": "São Paulo"}
        assert response.finish_reason == "tool_calls"
