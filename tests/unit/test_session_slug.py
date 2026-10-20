"""O slug de sessão não colide entre sessões do mesmo prompt iniciadas no mesmo segundo."""

import re

import pytest

from src.artifacts.output_manager import generate_session_slug


@pytest.mark.unit
def test_slug_tem_timestamp_sufixo_aleatorio_e_prompt():
    slug = generate_session_slug("Tarefa de Teste!")
    assert re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}_tarefa_de_teste", slug)


@pytest.mark.unit
def test_slugs_do_mesmo_prompt_no_mesmo_segundo_diferem():
    assert len({generate_session_slug("mesma tarefa") for _ in range(50)}) > 1
