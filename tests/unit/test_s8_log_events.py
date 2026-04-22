"""Testes unitários para os log events da Etapa S8 do roadmap_v2.

Valida que os eventos estruturados exigidos pelo roadmap_v2 S8 são emitidos
corretamente pelas skills sem dependência de Docker ou API Gemini.
"""

import pytest
import logging
import tempfile
import os

from src.skills.base import BaseSkill, SkillResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSkill(BaseSkill):
    """Skill mínima de teste — não faz I/O real."""

    name = "fake_skill"
    description = "Skill de teste para validação de log events."

    def __init__(self, should_succeed: bool = True):
        self._should_succeed = should_succeed

    async def run(self, **kwargs) -> SkillResult:  # noqa: D102
        if self._should_succeed:
            return SkillResult(success=True, output="ok")
        return SkillResult(success=False, output="", error="falha simulada")


def _get_events(caplog_records: list) -> list[str]:
    """Extrai o campo 'event' dos LogRecords capturados pelo caplog.

    O logger GeminiClaw usa extra={...} com campos planos adicionados ao
    record.__dict__ — o acesso correto é getattr(record, 'event').
    """
    return [getattr(r, "event", None) for r in caplog_records if getattr(r, "event", None)]


# ---------------------------------------------------------------------------
# Testes de skill_invoked / skill_completed / skill_failed via BaseSkill
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_with_logging_emits_skill_invoked(caplog):
    """run_with_logging deve emitir o evento skill_invoked antes da execução."""
    skill = _FakeSkill(should_succeed=True)

    with caplog.at_level(logging.INFO, logger="src.skills.base"):
        await skill.run_with_logging(query="test")

    events = _get_events(caplog.records)
    assert "skill_invoked" in events, f"skill_invoked não encontrado nos logs: {events}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_with_logging_emits_skill_completed_on_success(caplog):
    """run_with_logging deve emitir skill_completed quando run() retorna success=True."""
    skill = _FakeSkill(should_succeed=True)

    with caplog.at_level(logging.INFO, logger="src.skills.base"):
        await skill.run_with_logging()

    events = _get_events(caplog.records)
    assert "skill_completed" in events, f"skill_completed não encontrado nos logs: {events}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_with_logging_emits_skill_failed_on_error(caplog):
    """run_with_logging deve emitir skill_failed quando run() retorna success=False."""
    skill = _FakeSkill(should_succeed=False)

    with caplog.at_level(logging.WARNING, logger="src.skills.base"):
        await skill.run_with_logging()

    events = _get_events(caplog.records)
    assert "skill_failed" in events, f"skill_failed não encontrado nos logs: {events}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_with_logging_skill_name_in_log(caplog):
    """Os log events devem incluir o nome da skill no campo 'skill'."""
    skill = _FakeSkill(should_succeed=True)

    with caplog.at_level(logging.INFO, logger="src.skills.base"):
        await skill.run_with_logging()

    skill_names = [
        getattr(r, "skill", None)
        for r in caplog.records
        if getattr(r, "event", None) in ("skill_invoked", "skill_completed")
    ]
    assert all(name == "fake_skill" for name in skill_names), (
        f"Nome da skill incorreto nos logs: {skill_names}"
    )


# ---------------------------------------------------------------------------
# Testes de memory_written via MemorySkill
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_skill_emits_memory_written_on_remember(caplog):
    """MemorySkill com action='remember' deve emitir memory_written (short_term)."""
    from src.skills.memory.skill import MemorySkill

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "memory.db")
        skill = MemorySkill(db_path=db_path)

        with caplog.at_level(logging.INFO, logger="src.skills.memory.skill"):
            result = await skill.run(
                action="remember",
                session_id="sess_test",
                key="iris_eda",
                value="150 amostras, 4 features",
            )

    assert result.success, f"Esperava success=True, obteve: {result.error}"

    events = _get_events(caplog.records)
    assert "memory_written" in events, f"memory_written não encontrado: {events}"

    stores = [
        getattr(r, "store", None)
        for r in caplog.records
        if getattr(r, "event", None) == "memory_written"
    ]
    assert "short_term" in stores, f"store='short_term' não encontrado: {stores}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_skill_emits_memory_written_on_memorize(caplog):
    """MemorySkill com action='memorize' deve emitir memory_written (long_term)."""
    from src.skills.memory.skill import MemorySkill

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "memory.db")
        skill = MemorySkill(db_path=db_path)

        with caplog.at_level(logging.INFO, logger="src.skills.memory.skill"):
            result = await skill.run(
                action="memorize",
                key="modelo_recomendado",
                value="Random Forest — melhor F1 no dataset Iris",
                importance=0.8,
            )

    assert result.success, f"Esperava success=True, obteve: {result.error}"

    events = _get_events(caplog.records)
    assert "memory_written" in events, f"memory_written não encontrado: {events}"

    stores = [
        getattr(r, "store", None)
        for r in caplog.records
        if getattr(r, "event", None) == "memory_written"
    ]
    assert "long_term" in stores, f"store='long_term' não encontrado: {stores}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_skill_emits_memory_promoted_on_remember_forever(caplog):
    """MemorySkill com action='remember_forever' deve emitir memory_promoted."""
    from src.skills.memory.skill import MemorySkill

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "memory.db")
        skill = MemorySkill(db_path=db_path)

        # Primeiro grava na memória de curto prazo
        await skill.run(
            action="remember",
            session_id="sess_test",
            key="achado_importante",
            value="Random Forest superou Logistic Regression no Iris",
        )

        # Agora promove para longo prazo
        with caplog.at_level(logging.INFO, logger="src.skills.memory.skill"):
            result = await skill.run(
                action="remember_forever",
                session_id="sess_test",
                key="achado_importante",
                importance=0.9,
            )

    assert result.success, f"Esperava success=True, obteve: {result.error}"

    events = _get_events(caplog.records)
    assert "memory_promoted" in events, f"memory_promoted não encontrado: {events}"


# ---------------------------------------------------------------------------
# Teste de consistência: nenhum evento errado em caso de falha
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_with_logging_no_completed_on_failure(caplog):
    """Quando a skill falha, skill_completed NÃO deve ser emitido."""
    skill = _FakeSkill(should_succeed=False)

    with caplog.at_level(logging.DEBUG, logger="src.skills.base"):
        await skill.run_with_logging()

    events = _get_events(caplog.records)
    assert "skill_completed" not in events, (
        f"skill_completed não deveria estar presente em falha: {events}"
    )
