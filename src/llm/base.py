import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    text: str | None
    thought: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length"
    usage: dict = field(default_factory=dict)

    def to_message(self) -> dict:
        """Converte a resposta para o formato de mensagem do histórico."""
        msg = {"role": "assistant"}
        if self.text:
            msg["content"] = self.text
        if self.thought:
            msg["thought"] = self.thought
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments
                    }
                }
                for tc in self.tool_calls
            ]
        return msg

class LLMProvider(ABC):
    """Interface contratual para qualquer backend de inferência."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Gera uma resposta. `tools` no formato OpenAI Tool Calling."""
        ...

    @abstractmethod
    async def generate_stream(self, messages: list[dict], system: str | None = None):
        """Gera resposta em streaming. Yield de chunks de texto."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Retorna True se o backend está acessível e operacional."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nome do modelo em uso (ex: 'qwen3.5:4b', 'gemini-2.0-flash')."""
        ...
