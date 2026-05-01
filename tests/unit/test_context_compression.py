import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.llm.context_compression import compress_messages, estimate_tokens

@pytest.mark.unit
class TestContextCompression:
    """Testes para a lógica de compressão de contexto (V6.5)."""

    def test_estimate_tokens_basic(self):
        """Testa se a estimativa de tokens segue a regra de 4 caracteres."""
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcdefgh") == 2
        assert estimate_tokens("") == 0

    @pytest.mark.asyncio
    async def test_compress_no_messages(self):
        """Testa comportamento com lista vazia."""
        assert await compress_messages([], 4096) == []

    @pytest.mark.asyncio
    async def test_compress_within_budget(self):
        """Testa se mensagens não são alteradas se estiverem dentro do budget."""
        messages = [
            {"role": "user", "content": "Olá"},
            {"role": "assistant", "content": "Oi, como posso ajudar?"}
        ]
        result = await compress_messages(messages, max_tokens=200)
        assert result == messages
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_compress_preserves_last_message(self):
        """Testa se o sistema preserva a última mensagem."""
        # Cada mensagem tem ~110 tokens (incluindo overhead dict)
        messages = [
            {"role": "user", "content": "A" * 400},
            {"role": "assistant", "content": "B" * 400},
            {"role": "user", "content": "C" * 400},
            {"role": "assistant", "content": "D" * 400},
            {"role": "user", "content": "E" * 400}, 
        ]
        
        system = "Instrução de sistema"
        # Budget total 300, safety 60, system 5 -> budget msgs 235.
        # Cabe E (~110) + D (~110) = 220. C (~110) estoura.
        result = await compress_messages(messages, max_tokens=300, system=system)
        
        # O resultado deve ter 2 mensagens
        assert len(result) == 2
        assert result[-1]["content"] == "E" * 400
        assert result[0]["content"] == "D" * 400

    @pytest.mark.asyncio
    async def test_compress_priority_retention(self):
        """Testa se mensagens de alta prioridade são mantidas em detrimento de baixas."""
        messages = [
            {"role": "user", "content": "U1" * 50},      # ~35 tokens (Prio 90)
            {"role": "tool", "content": "T1" * 50},      # ~35 tokens (Prio 30)
            {"role": "assistant", "content": "A1" * 50}, # ~35 tokens (Prio 70)
            {"role": "user", "content": "U2" * 50},      # ~35 tokens (Prio 90)
        ]
        
        # max_tokens 100 -> safety 20 -> budget 80 tokens.
        # U2 (~35) -> budget left 45.
        # A1 (~35) -> budget left 10.
        # T1 (~35) -> PULA.
        # U1 (~35) -> PULA.
        
        result = await compress_messages(messages, max_tokens=100)
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_compress_with_summary(self):
        """Testa a compressão com sumarização."""
        # Mensagens grandes para forçar estouro de budget > 100
        messages = [
            {"role": "user", "content": "Pergunta 1" * 100},   # ~250 tokens
            {"role": "assistant", "content": "Resposta 1" * 100}, # ~250 tokens
            {"role": "user", "content": "Pergunta 2" * 100},   # ~250 tokens
            {"role": "assistant", "content": "Resposta 2" * 100}, # ~250 tokens
        ]
        
        mock_provider = MagicMock()
        mock_provider.generate = AsyncMock(return_value=MagicMock(text="Resumo das msgs 1"))
        
        # Budget 400 total
        # max_tokens 500 -> safety 100 -> budget 400.
        # Total messages ~1000 tokens.
        
        with patch("src.config.CONTEXT_COMPRESSION_MODE", "summarize"):
            result = await compress_messages(messages, max_tokens=500, provider=mock_provider)
                
        assert any("[RESUMO DO HISTÓRICO ANTERIOR]" in m["content"] for m in result if m["role"] == "system")
        assert mock_provider.generate.called
