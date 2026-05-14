"""Testes unitários para a lógica de invalidação de cache — V12.1.

Cobre os cenários:
  1. Resposta com status de erro não é cacheada (V12.1.2).
  2. Resposta vazia / muito curta não é cacheada (V12.1.2).
  3. Método invalidate() remove a entrada existente do cache (V12.1.3).
  4. Retry com cache-busting gera hash diferente da tentativa original (V12.1.1).
  5. Invalidação de entrada inexistente não lança erro (V12.1.3).
"""

import pytest
import time
from unittest.mock import MagicMock, patch, call

from src.llm_cache import LLMResponseCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(fetchone=None, fetchall=None):
    """Cria context manager mock para get_connection."""
    mock_conn = MagicMock()
    cursor = MagicMock()
    mock_conn.execute.return_value = cursor
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def enable_cache(monkeypatch):
    """Habilita o cache para cada teste."""
    monkeypatch.setenv("LLM_CACHE_ENABLED", "true")
    monkeypatch.setenv("LLM_CACHE_TTL_SECONDS", "3600")
    monkeypatch.setenv("LLM_CACHE_MAX_ENTRIES", "1000")


@pytest.fixture
def cache():
    return LLMResponseCache()


# ---------------------------------------------------------------------------
# V12.1.2 — Nunca cachear respostas vazias ou com erro
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheSetFilterInvalidResponses:
    """set() deve ignorar respostas inválidas, nunca gravá-las no banco."""

    def test_set_ignora_resposta_vazia(self, cache):
        """set() não deve gravar quando response é string vazia."""
        with patch("src.llm_cache.get_connection") as mock_gc:
            cache.set("prompt", "model", "")
        mock_gc.assert_not_called()

    def test_set_ignora_resposta_somente_espacos(self, cache):
        """set() não deve gravar quando response tem apenas espaços."""
        with patch("src.llm_cache.get_connection") as mock_gc:
            cache.set("prompt", "model", "   ")
        mock_gc.assert_not_called()

    def test_set_ignora_resposta_muito_curta(self, cache):
        """set() não deve gravar quando response tem menos de 50 chars."""
        with patch("src.llm_cache.get_connection") as mock_gc:
            cache.set("prompt", "model", "curto")
        mock_gc.assert_not_called()

    def test_set_ignora_resposta_com_exatamente_50_chars(self, cache):
        """Resposta com exatamente 50 chars NÃO deve ser cacheada (limiar é > 50)."""
        response_50 = "A" * 50
        with patch("src.llm_cache.get_connection") as mock_gc:
            cache.set("prompt", "model", response_50)
        mock_gc.assert_not_called()

    def test_set_grava_resposta_valida(self, cache):
        """set() deve gravar quando response é válida (len > 50)."""
        count_row = {"cnt": 0}
        ctx, mock_conn = _make_ctx(fetchone=count_row)
        response_valida = "A" * 51
        with patch("src.llm_cache.get_connection", return_value=ctx):
            cache.set("prompt", "model", response_valida)
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("ON CONFLICT" in s for s in sqls), (
            "Esperava INSERT ... ON CONFLICT para resposta válida"
        )


# ---------------------------------------------------------------------------
# V12.1.3 — Método invalidate()
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheInvalidate:
    """invalidate() deve deletar a entrada do banco baseado no hash do prompt+model."""

    def test_invalidate_chama_delete(self, cache):
        """invalidate() deve executar um DELETE com a chave correta."""
        ctx, mock_conn = _make_ctx()
        with patch("src.llm_cache.get_connection", return_value=ctx):
            cache.invalidate("meu prompt", "gemini")
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("DELETE" in s for s in sqls), (
            "Esperava DELETE no banco ao invalidar uma entrada"
        )

    def test_invalidate_usa_hash_correto(self, cache):
        """invalidate() deve usar o mesmo hash que seria gerado para get/set."""
        ctx, mock_conn = _make_ctx()
        prompt = "tarefa de análise de dados"
        model = "qwen3:4b"
        expected_hash = cache._generate_hash(prompt, model)

        with patch("src.llm_cache.get_connection", return_value=ctx):
            cache.invalidate(prompt, model)

        # Verificar que o hash foi passado como argumento ao execute
        all_args = [c[0][1] for c in mock_conn.execute.call_args_list if c[0][1]]
        hashes_passados = [
            a[0] for a in all_args
            if isinstance(a, tuple) and a
        ]
        assert expected_hash in hashes_passados, (
            f"Hash esperado {expected_hash[:8]}... não foi passado ao DELETE"
        )

    def test_invalidate_nao_lanca_excecao_quando_entrada_inexistente(self, cache):
        """invalidate() de entrada inexistente não deve lançar exceção."""
        ctx, _ = _make_ctx()
        with patch("src.llm_cache.get_connection", return_value=ctx):
            # Não deve lançar nada
            cache.invalidate("prompt que nao existe", "qualquer-modelo")

    def test_invalidate_nao_faz_nada_quando_cache_desabilitado(self, monkeypatch):
        """invalidate() não deve tocar no banco quando cache está desabilitado."""
        monkeypatch.setenv("LLM_CACHE_ENABLED", "false")
        cache_off = LLMResponseCache()
        with patch("src.llm_cache.get_connection") as mock_gc:
            cache_off.invalidate("prompt", "model")
        mock_gc.assert_not_called()


# ---------------------------------------------------------------------------
# V12.1.1 — Cache-busting por injeção de contexto de erro
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCacheBustingByPromptInjection:
    """Verifica que o prompt enriquecido com erro gera hash diferente do original.

    Nota: este teste opera na camada de hash do cache, validando que a injeção
    do bloco de erro no prompt resulta em um hash diferente — ou seja, o cache
    fará MISS na nova tentativa.
    """

    def test_hash_muda_apos_injecao_de_erro(self, cache):
        """Prompt original e prompt com bloco de erro devem ter hashes diferentes."""
        prompt_original = "Classifique o dataset iris usando pandas e sklearn."
        erro = "FileNotFoundError: /datasets/iris.csv not found"
        attempt = 1
        max_retries = 3

        bloco_erro = (
            f"\n\n[TENTATIVA ANTERIOR FALHOU]\n"
            f"Tentativa: {attempt + 1}/{max_retries}\n"
            f"Erro: {erro}\n"
            f"Instrução: Tente uma abordagem diferente para resolver o problema.\n"
        )
        prompt_com_busting = prompt_original + bloco_erro

        hash_original = cache._generate_hash(prompt_original, "qwen3:4b")
        hash_com_busting = cache._generate_hash(prompt_com_busting, "qwen3:4b")

        assert hash_original != hash_com_busting, (
            "Prompt com bloco de erro deve gerar hash diferente (garantir cache MISS)"
        )

    def test_hash_diferente_por_numero_de_tentativa(self, cache):
        """Cada tentativa deve gerar um hash único, pois o número da tentativa muda."""
        prompt = "Gerar gráfico com matplotlib."
        model = "qwen3:4b"
        erro = "ImportError: No module named 'matplotlib'"

        hashes = set()
        for attempt in range(3):
            bloco = (
                f"\n\n[TENTATIVA ANTERIOR FALHOU]\n"
                f"Tentativa: {attempt + 1}/3\n"
                f"Erro: {erro}\n"
                f"Instrução: Tente uma abordagem diferente para resolver o problema.\n"
            )
            h = cache._generate_hash(prompt + bloco, model)
            hashes.add(h)

        assert len(hashes) == 3, (
            "Cada número de tentativa deve produzir um hash único"
        )

    def test_hash_diferente_por_tipo_de_erro(self, cache):
        """Erros distintos geram prompts distintos e portanto hashes distintos."""
        prompt = "Processar CSV com pandas."
        model = "gemini-2.0-flash"
        erros = [
            "FileNotFoundError: iris.csv",
            "MemoryError: out of memory",
            "ValueError: invalid literal",
        ]

        hashes = [
            cache._generate_hash(
                prompt + f"\n\n[TENTATIVA ANTERIOR FALHOU]\nTentativa: 2/3\nErro: {e}\nInstrução: Tente uma abordagem diferente para resolver o problema.\n",
                model,
            )
            for e in erros
        ]

        assert len(set(hashes)) == 3, (
            "Erros distintos devem resultar em hashes distintos"
        )
