"""Testes unitários para o parser robusto de JSON de LLMs.

Cobre exemplos reais de saídas problemáticas que LLMs costumam produzir.
"""

import pytest

from src.utils.json_parser import (
    extract_json,
    _strip_markdown_fences,
    _extract_balanced,
    _sanitize,
)


# ---------------------------------------------------------------------------
# extract_json — caminho feliz
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractJsonHappyPath:
    """JSON válido deve ser retornado sem qualquer transformação."""

    def test_plain_dict(self) -> None:
        """Dict JSON limpo deve ser retornado diretamente."""
        result = extract_json('{"status": "approved", "reason": "ok"}')
        assert result == {"status": "approved", "reason": "ok"}

    def test_plain_list(self) -> None:
        """Lista JSON limpa deve ser retornada diretamente."""
        result = extract_json('[{"agent_id": "base", "prompt": "Do X"}]')
        assert result == [{"agent_id": "base", "prompt": "Do X"}]

    def test_nested_dict(self) -> None:
        """Dict aninhado deve ser retornado corretamente."""
        raw = '{"tasks": [{"id": 1}, {"id": 2}], "count": 2}'
        result = extract_json(raw)
        assert isinstance(result, dict)
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# extract_json — bloco markdown
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractJsonMarkdown:
    """JSON envolto em bloco markdown deve ser extraído corretamente."""

    def test_json_fenced_with_json_label(self) -> None:
        """Bloco ```json deve ser desembrulhado."""
        raw = '```json\n{"status": "approved"}\n```'
        result = extract_json(raw)
        assert result == {"status": "approved"}

    def test_json_fenced_without_label(self) -> None:
        """Bloco ``` sem linguagem deve ser desembrulhado."""
        raw = '```\n[{"agent_id": "researcher"}]\n```'
        result = extract_json(raw)
        assert result == [{"agent_id": "researcher"}]

    def test_json_with_text_before_fence(self) -> None:
        """Texto antes do bloco deve ser ignorado."""
        raw = "Claro! Aqui está o plano:\n```json\n[1, 2, 3]\n```"
        result = extract_json(raw)
        assert result == [1, 2, 3]

    def test_json_with_text_after_fence(self) -> None:
        """Texto após o bloco deve ser ignorado."""
        raw = '```json\n{"ok": true}\n```\nEspero que ajude!'
        result = extract_json(raw)
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# extract_json — texto ao redor (sem markdown)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractJsonWithSurroundingText:
    """JSON com texto ao redor (sem markdown) deve ser extraído pelo balanceamento."""

    def test_dict_after_preamble(self) -> None:
        """JSON precedido de texto introdutório deve ser extraído."""
        raw = 'Aqui está meu plano: {"status": "approved", "reason": "tudo ok"}'
        result = extract_json(raw)
        assert result == {"status": "approved", "reason": "tudo ok"}

    def test_list_after_preamble(self) -> None:
        """Lista precedida de texto deve ser extraída."""
        raw = 'Plano de execução:\n[{"agent_id": "base"}]'
        result = extract_json(raw)
        assert result == [{"agent_id": "base"}]

    def test_dict_with_text_after(self) -> None:
        """JSON seguido de texto deve ter o texto ignorado."""
        raw = '{"key": "value"} Este é o resultado final.'
        result = extract_json(raw)
        assert result == {"key": "value"}

    def test_nested_json_correct_closing(self) -> None:
        """Balanceamento correto em JSON aninhado."""
        raw = 'Resultado: {"a": {"b": [1, 2]}} OK'
        result = extract_json(raw)
        assert result == {"a": {"b": [1, 2]}}


# ---------------------------------------------------------------------------
# extract_json — trailing commas e comentários
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractJsonSanitization:
    """Trailing commas e comentários inline devem ser removidos antes do parse."""

    def test_trailing_comma_in_dict(self) -> None:
        """Dict com trailing comma deve ser parseado."""
        raw = '{"key": "val",}'
        result = extract_json(raw)
        assert result == {"key": "val"}

    def test_trailing_comma_in_list(self) -> None:
        """Lista com trailing comma deve ser parseada."""
        raw = "[1, 2, 3,]"
        result = extract_json(raw)
        assert result == [1, 2, 3]

    def test_inline_comment_removed(self) -> None:
        """Comentário inline // deve ser removido."""
        raw = '{"key": 1 // nota do autor\n}'
        result = extract_json(raw)
        assert result == {"key": 1}

    def test_trailing_comma_after_last_field(self) -> None:
        """Trailing comma após último campo de dict aninhado."""
        raw = '{"tasks": [{"id": 1},]}'
        result = extract_json(raw)
        assert result == {"tasks": [{"id": 1}]}


# ---------------------------------------------------------------------------
# extract_json — casos de borda
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractJsonEdgeCases:
    """Casos de borda e entradas inválidas."""

    def test_empty_string_returns_none(self) -> None:
        """String vazia deve retornar None."""
        assert extract_json("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """String com apenas espaços deve retornar None."""
        assert extract_json("   \n\t  ") is None

    def test_plain_text_no_json_returns_none(self) -> None:
        """Texto sem nenhum JSON deve retornar None."""
        assert extract_json("Não entendi a solicitação.") is None

    def test_unclosed_bracket_returns_none(self) -> None:
        """JSON malformado sem fechamento deve retornar None."""
        assert extract_json('{"key": "val"') is None

    def test_real_llm_output_plan(self) -> None:
        """Saída real de LLM com plano JSON em markdown."""
        raw = (
            "Com base na solicitação, aqui está o plano de execução:\n\n"
            "```json\n"
            '[\n  {"agent_id": "researcher", "prompt": "Pesquise X"},\n'
            '  {"agent_id": "base", "prompt": "Resuma os resultados"}\n]\n'
            "```\n\n"
            "Este plano foi otimizado para o Raspberry Pi 5."
        )
        result = extract_json(raw)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["agent_id"] == "researcher"

    def test_real_llm_output_validator(self) -> None:
        """Saída real de LLM com resposta do Validador em markdown."""
        raw = (
            "Analisei o plano e aprovo.\n\n"
            "```json\n"
            '{"status": "approved", "reason": "Plano coerente e eficiente"}\n'
            "```"
        )
        result = extract_json(raw)
        assert isinstance(result, dict)
        assert result["status"] == "approved"


# ---------------------------------------------------------------------------
# Helpers internos — testes isolados
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJsonParserInternals:
    """Testes dos helpers internos do json_parser."""

    def test_strip_markdown_fences_with_json(self) -> None:
        raw = "```json\n{}\n```"
        assert _strip_markdown_fences(raw) == "{}"

    def test_strip_markdown_fences_no_fence(self) -> None:
        raw = '{"key": "val"}'
        assert _strip_markdown_fences(raw) == raw

    def test_extract_balanced_simple_dict(self) -> None:
        text = 'texto {"a": 1} mais texto'
        assert _extract_balanced(text) == '{"a": 1}'

    def test_extract_balanced_simple_list(self) -> None:
        text = "prefixo [1, 2, 3] sufixo"
        assert _extract_balanced(text) == "[1, 2, 3]"

    def test_extract_balanced_nested(self) -> None:
        text = 'x {"a": {"b": 2}} y'
        assert _extract_balanced(text) == '{"a": {"b": 2}}'

    def test_extract_balanced_no_delimiters(self) -> None:
        assert _extract_balanced("sem delimitadores") is None

    def test_sanitize_trailing_comma(self) -> None:
        assert _sanitize('{"a": 1,}') == '{"a": 1}'

    def test_sanitize_inline_comment(self) -> None:
        result = _sanitize('{"a": 1 // comment\n}')
        assert "//" not in result
        assert "comment" not in result

    def test_sanitize_no_changes_needed(self) -> None:
        raw = '{"a": 1}'
        assert _sanitize(raw) == raw
