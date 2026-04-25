import os
from google import genai
from google.genai import types as genai_types
from src.llm.base import LLMProvider, LLMResponse, ToolCall
from src.logger import get_logger
from src.config import GEMINI_API_KEY, DEFAULT_MODEL

logger = get_logger(__name__)

class GoogleProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or GEMINI_API_KEY
        self._model = model or DEFAULT_MODEL
        self._client = genai.Client(api_key=self._api_key)

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        # Converter mensagens para formato Google GenAI
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(genai_types.Content(role=role, parts=[genai_types.Part(text=msg["content"])]))

        # Configuração de geração
        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system,
        )

        # Adicionar ferramentas se fornecidas
        if tools:
            # Converter formato OpenAI Tool Calling para formato Google GenAI
            # (Simplificado para o MVP: assume-se que as skills serão passadas no formato ADK ou convertidas)
            # Na verdade, o roadmap diz que a abstração usa formato OpenAI como padrão.
            google_tools = []
            functions = []
            for t in tools:
                if t.get("type") == "function":
                    f = t["function"]
                    functions.append(genai_types.FunctionDeclaration(
                        name=f["name"],
                        description=f["description"],
                        parameters=f["parameters"]
                    ))
            if functions:
                google_tools.append(genai_types.Tool(function_declarations=functions))
            config.tools = google_tools

        try:
            # Chamada síncrona embrulhada em executor para ser async-friendly 
            # ou usar o cliente async se disponível (genai.Client tem async_?)
            # O google-genai 1.3.0+ tem suporte async
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

            # Processar resposta
            text = response.text
            tool_calls = []
            
            # Se houver chamadas de função
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        fc = part.function_call
                        tool_calls.append(ToolCall(
                            id=fc.name, # Google não tem um ID único por call como OpenAI, usamos nome
                            name=fc.name,
                            arguments=fc.args
                        ))

            finish_reason = "stop"
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.finish_reason == "MAX_TOKENS":
                    finish_reason = "length"
                elif tool_calls:
                    finish_reason = "tool_calls"

            return LLMResponse(
                text=text,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage={
                    "prompt_tokens": response.usage_metadata.prompt_token_count if response.usage_metadata else 0,
                    "completion_tokens": response.usage_metadata.candidates_token_count if response.usage_metadata else 0,
                    "total_tokens": response.usage_metadata.total_token_count if response.usage_metadata else 0,
                }
            )
        except Exception as e:
            logger.error(f"Erro na requisição ao Google GenAI: {str(e)}")
            raise

    async def generate_stream(self, messages: list[dict], system: str | None = None):
        # Implementação básica de stream
        # (Omitido para brevidade no MVP, similar ao generate mas iterando chunks)
        response = await self.generate(messages, system=system)
        if response.text:
            yield response.text

    async def health_check(self) -> bool:
        try:
            # Tenta uma chamada mínima
            self._client.models.generate_content(
                model=self._model,
                contents="ping",
                config=genai_types.GenerateContentConfig(max_output_tokens=1)
            )
            return True
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self._model
