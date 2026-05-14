import asyncio, json, os, time
import httpx
from src.llm.base import LLMProvider, LLMResponse, ToolCall
from src.logger import get_logger

logger = get_logger(__name__)

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model
        # Reutilizar cliente HTTP — evita overhead de conexão no Pi 5
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=None,  # Sem timeout: Pi 5 pode levar minutos por resposta
        )
        # Throttling interno para não sobrecarregar o Pi 5
        self._rpm_limit = int(os.getenv("LLM_REQUESTS_PER_MINUTE", "15"))
        self._request_times: list[float] = []
        self._lock = asyncio.Lock()

    async def _throttle(self):
        """Controla a taxa de requisições para proteger o Pi 5."""
        async with self._lock:
            now = time.monotonic()
            self._request_times = [t for t in self._request_times if now - t < 60]
            if len(self._request_times) >= self._rpm_limit:
                wait = 60 - (now - self._request_times[0])
                if wait > 0:
                    logger.info("Ollama throttling ativo", extra={"wait": wait})
                    await asyncio.sleep(wait)
            self._request_times.append(time.monotonic())

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        await self._throttle()

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                # Limitar contexto para proteger RAM do Pi 5
                "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096")),
            }
        }
        # Desabilitar thinking mode do Qwen3.5.5 para respostas mais rápidas
        # (pode ser habilitado por agente via variável de ambiente)
        if os.getenv("OLLAMA_ENABLE_THINKING", "false").lower() == "false":
            # O Qwen3.5 respeita a instrução no system prompt para desabilitar thinking
            no_think_suffix = "\n/no_think"
            if system:
                system = system + no_think_suffix
            else:
                system = no_think_suffix

        if tools:
            payload["tools"] = tools
        
        # Injetar system prompt se fornecido e não for redundante
        final_messages = list(messages)
        if system:
            # Verifica se a primeira mensagem já é um system prompt idêntico
            first_msg = messages[0] if messages else None
            if not (first_msg and first_msg.get("role") == "system" and first_msg.get("content") == system):
                final_messages = [{"role": "system", "content": system}] + final_messages
        payload["messages"] = final_messages

        try:
            logger.debug("Enviando requisição ao Ollama", extra={"model": self._model, "tools_count": len(tools) if tools else 0})
            # Log payload apenas em modo debug profundo se necessário, mas aqui vamos logar o básico
            response = await self._client.post("/api/chat", json=payload)
            if response.status_code != 200:
                logger.error(
                    f"Ollama retornou erro {response.status_code}", 
                    extra={"response_body": response.text, "payload_keys": list(payload.keys())}
                )
            response.raise_for_status()
            data = response.json()

            message = data.get("message", {})
            tool_calls = []
            for tc in message.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        logger.error("Erro ao decodificar argumentos da ferramenta", extra={"args": args})
                        args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", fn.get("name", f"call_{int(time.time())}")),
                    name=fn.get("name", ""),
                    arguments=args,
                ))

            # V11.2.3 — TTFT: Ollama expõe load_duration + prompt_eval_duration em nanosegundos.
            # load_duration = tempo para carregar o modelo na memória.
            # prompt_eval_duration = tempo para avaliar o prompt.
            # Juntos aproximam o Time to First Token no Pi 5.
            _load_ns = data.get("load_duration", 0) or 0
            _prompt_eval_ns = data.get("prompt_eval_duration", 0) or 0
            _ttft_ms = int((_load_ns + _prompt_eval_ns) / 1_000_000)

            return LLMResponse(
                text=message.get("content"),
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                usage={
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                    "ttft_ms": _ttft_ms,
                },
            )
        except Exception as e:
            logger.error(f"Erro na requisição ao Ollama: {str(e)}")
            raise

    async def generate_stream(self, messages: list[dict], system: str | None = None):
        """Gera resposta em streaming (simplificado para MVP)."""
        # Implementação básica de stream pode ser adicionada depois se necessário
        response = await self.generate(messages, system=system)
        if response.text:
            yield response.text

    async def health_check(self) -> bool:
        try:
            r = await self._client.get("/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self._model
