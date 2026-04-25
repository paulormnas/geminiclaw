import pytest
from src.llm.context_compression import compress_messages, estimate_tokens

@pytest.mark.unit
class TestContextCompression:
    """Testes para a lógica de compressão de contexto (V21)."""

    def test_estimate_tokens_basic(self):
        """Testa se a estimativa de tokens segue a regra de 4 caracteres."""
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcdefgh") == 2
        assert estimate_tokens("") == 0

    def test_compress_no_messages(self):
        """Testa comportamento com lista vazia."""
        assert compress_messages([], 4096) == []

    def test_compress_within_budget(self):
        """Testa se mensagens não são alteradas se estiverem dentro do budget."""
        messages = [
            {"role": "user", "content": "Olá"},
            {"role": "assistant", "content": "Oi, como posso ajudar?"}
        ]
        # Budget folgado: system(0) + safety(50) + msg1(~1) + msg2(~5) << 200
        result = compress_messages(messages, max_tokens=200)
        assert result == messages
        assert len(result) == 2

    def test_compress_preserves_system_and_last_user_message(self):
        """Testa se o sistema preserva o system prompt e a última mensagem."""
        # Cada mensagem tem ~100 tokens (400 chars)
        messages = [
            {"role": "user", "content": "A" * 400},
            {"role": "assistant", "content": "B" * 400},
            {"role": "user", "content": "C" * 400},
            {"role": "assistant", "content": "D" * 400},
            {"role": "user", "content": "E" * 400}, # Última: DEVE ser preservada
        ]
        
        system = "Instrução de sistema" # ~5 tokens
        # Budget: 250 tokens total
        # System: 5
        # Safety margin: 250/4 = 62
        # Remaining budget for messages: 250 - 5 - 62 = 183 tokens
        
        result = compress_messages(messages, max_tokens=250, system=system)
        
        # Última mensagem (E) tem 100 tokens. Cabe no budget de 183.
        # Mensagem anterior (D) tem 100 tokens. 100 + 100 = 200 > 183. NÃO cabe.
        
        assert len(result) == 1
        assert result[0]["content"] == "E" * 400

    def test_compress_truncates_last_message_if_exceeds_budget(self):
        """Testa se a última mensagem é truncada se for maior que o budget total."""
        messages = [
            {"role": "user", "content": "Super longa " * 100} # ~300 tokens
        ]
        
        # Budget muito pequeno
        # total 100, safety 25, budget 75 tokens
        result = compress_messages(messages, max_tokens=100)
        
        assert len(result) == 1
        assert "[truncado]" in result[0]["content"]
        assert estimate_tokens(result[0]["content"]) <= 75 + 10 # margem para o texto de truncagem

    def test_compress_drops_old_middle_messages(self):
        """Testa o descarte de mensagens antigas do meio da conversa."""
        messages = [
            {"role": "user", "content": "Primeira"},
            {"role": "assistant", "content": "Resposta 1"},
            {"role": "user", "content": "Segunda"},
            {"role": "assistant", "content": "Resposta 2"},
            {"role": "user", "content": "Terceira"},
        ]
        
        # Força um budget que caiba apenas 2 mensagens (a última e a anterior)
        # 1 token ≈ 4 chars. Mensagens são curtas (~2-3 tokens cada).
        # total 60, safety 15, budget 45 tokens.
        result = compress_messages(messages, max_tokens=60)
        
        # Deve ter pelo menos a última ("Terceira")
        assert result[-1]["content"] == "Terceira"
        # E deve ter removido as mais antigas se o budget for atingido
        # Como as msgs são minúsculas, talvez caibam todas. Vamos testar com msgs maiores.
        
        big_messages = [
            {"role": "user", "content": "X" * 100}, # 25 tokens
            {"role": "assistant", "content": "Y" * 100}, # 25 tokens
            {"role": "user", "content": "Z" * 100}, # 25 tokens
            {"role": "assistant", "content": "W" * 100}, # 25 tokens
            {"role": "user", "content": "K" * 100}, # 25 tokens
        ]
        # Total 125 tokens + msgs extras
        # Budget total 80, safety 20, net budget 60 tokens.
        # Cabe: K (25) + W (25) = 50. Z (25) já estoura (50+25=75 > 60).
        
        result = compress_messages(big_messages, max_tokens=80)
        assert len(result) == 2
        assert result[0]["content"] == "W" * 100
        assert result[1]["content"] == "K" * 100
