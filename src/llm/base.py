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
    # Dados opacos que o próprio provedor precisa receber de volta no histórico (ex.: blocos
    # de pensamento assinados da Anthropic, que devem ser devolvidos intactos no ciclo de
    # ferramentas). Os demais provedores ignoram este campo.
    provider_data: dict | None = None
    # Versão efetivamente servida, como o provedor informa (v18.5-model-catalog-locality);
    # "desconhecida" quando não informa. Nunca derivada do nome pedido.
    versao_efetiva: str = "desconhecida"

    def to_message(self) -> dict:
        """Converte a resposta para o formato de mensagem do histórico."""
        msg = {"role": "assistant"}
        if self.text:
            msg["content"] = self.text
        if self.thought:
            msg["thought"] = self.thought
        if self.provider_data:
            msg["provider_data"] = self.provider_data
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

    async def check_availability(self) -> str | None:
        """Confere se o modelo configurado está utilizável, **sem gerar texto** (ADR 017 §4).

        Returns:
            ``None`` se o modelo está disponível; um código de motivo curto (ex.:
            ``modelo_nao_instalado``) se o backend responde mas o modelo não serve. Falhas de
            comunicação podem levantar exceção: quem chama reduz o erro a classe + código HTTP.
        """
        return None if await self.health_check() else "health_check_falhou"

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nome do modelo em uso (ex: 'qwen3.5:4b', 'gemini-3.8-flash')."""
        ...
