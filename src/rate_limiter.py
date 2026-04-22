import asyncio
import time
from typing import Optional

from src.logger import get_logger

logger = get_logger(__name__)

class AdaptiveRateLimiter:
    """Implementa um limitador de taxa adaptativo com backoff exponencial.
    
    Usa uma variação de Token Bucket combinada com janela deslizante e
    adaptação de limite baseada em sucessos/falhas (HTTP 429).
    """

    def __init__(
        self,
        requests_per_minute: int = 15,
        cooldown_seconds: int = 30,
        min_requests_per_minute: int = 2,
    ) -> None:
        """Inicializa o rate limiter.

        Args:
            requests_per_minute: Limite máximo normal de requisições por minuto.
            cooldown_seconds: Tempo base de espera quando ocorre um erro 429.
            min_requests_per_minute: Limite mínimo de requisições por minuto (durante backoff).
        """
        self.base_rpm = requests_per_minute
        self.current_rpm = requests_per_minute
        self.cooldown_seconds = cooldown_seconds
        self.min_rpm = min_requests_per_minute
        
        self.tokens: float = float(self.current_rpm)
        self.last_update = time.monotonic()
        
        # Controle de backoff
        self.in_cooldown_until: float = 0.0
        self.consecutive_429s = 0
        
        self._lock = asyncio.Lock()

    def _update_tokens(self) -> None:
        """Atualiza a quantidade de tokens disponíveis baseado no tempo decorrido."""
        now = time.monotonic()
        time_passed = now - self.last_update
        
        # Tokens gerados por segundo
        rate = self.current_rpm / 60.0
        
        self.tokens += time_passed * rate
        if self.tokens > self.current_rpm:
            self.tokens = float(self.current_rpm)
            
        self.last_update = now

    async def acquire(self) -> None:
        """Aguarda até que um token esteja disponível e possa fazer a requisição."""
        while True:
            now = time.monotonic()
            
            async with self._lock:
                # Verifica se estamos em cooldown
                if now < self.in_cooldown_until:
                    sleep_time = self.in_cooldown_until - now
                    logger.debug("Rate limiter em cooldown", extra={"sleep_time": sleep_time})
                else:
                    self._update_tokens()
                    
                    if self.tokens >= 1.0:
                        self.tokens -= 1.0
                        return
                    else:
                        # Falta token, calcula o tempo de espera até gerar 1 token
                        rate = self.current_rpm / 60.0
                        sleep_time = (1.0 - self.tokens) / rate
            
            # Dorme fora do lock
            await asyncio.sleep(sleep_time)

    async def report_429(self) -> None:
        """Informa ao limitador que ocorreu um erro de rate limit (HTTP 429)."""
        async with self._lock:
            self.consecutive_429s += 1
            
            # Backoff exponencial: 30s, 60s, 120s...
            cooldown = self.cooldown_seconds * (2 ** (self.consecutive_429s - 1))
            self.in_cooldown_until = time.monotonic() + cooldown
            
            # Reduz a taxa pela metade, não menos que min_rpm
            self.current_rpm = max(self.min_rpm, self.current_rpm // 2)
            
            # Reseta tokens para a nova capacidade (ou zero para forçar espera após cooldown)
            self.tokens = 0.0
            self.last_update = time.monotonic()
            
            logger.warning(
                "Rate limit 429 recebido. Aplicando backoff.",
                extra={
                    "cooldown_seconds": cooldown,
                    "new_rpm": self.current_rpm,
                    "consecutive_429s": self.consecutive_429s
                }
            )

    async def report_success(self) -> None:
        """Informa que uma requisição foi bem sucedida, gradualmente restaurando a taxa."""
        async with self._lock:
            if self.consecutive_429s > 0:
                self.consecutive_429s = 0
                
            if self.current_rpm < self.base_rpm:
                # Recuperação gradual: adiciona 1 RPM a cada sucesso até o base_rpm
                self.current_rpm = min(self.base_rpm, self.current_rpm + 1)
                
                logger.debug(
                    "Requisição bem sucedida. Restaurando rate limit.",
                    extra={"new_rpm": self.current_rpm, "base_rpm": self.base_rpm}
                )
