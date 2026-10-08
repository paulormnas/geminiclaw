"""Testes unitários do Session Profile (Roadmap V15.6 / Spec G10).

Cobre a flag --mode, o help completo e o banner de inicialização de sessão.
"""

import pytest

from src.cli import (
    FULL_HELP_TEXT,
    build_parser,
    print_full_help,
    print_session_banner,
)
from src.config import SESSION_DEFAULT_MODE, SessionMode


@pytest.mark.unit
class TestModeFlag:
    """Testes da flag --mode do parser."""

    def test_mode_padrao_e_none(self) -> None:
        """Sem --mode, args.mode é None (resolvido depois para SESSION_DEFAULT_MODE)."""
        parser = build_parser()
        args = parser.parse_args(["tarefa"])
        assert args.mode is None

    def test_mode_assisted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--mode", "assisted", "tarefa"])
        assert args.mode == "assisted"

    def test_mode_semi(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--mode", "semi", "tarefa"])
        assert args.mode == "semi"

    def test_mode_auto(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--mode", "auto", "tarefa"])
        assert args.mode == "auto"

    def test_mode_invalido_rejeitado(self) -> None:
        """Valor fora do enum SessionMode é rejeitado pelo argparse."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--mode", "invalido", "tarefa"])

    def test_choices_correspondem_ao_enum(self) -> None:
        parser = build_parser()
        mode_action = next(a for a in parser._actions if a.dest == "mode")
        assert set(mode_action.choices) == {m.value for m in SessionMode}


@pytest.mark.unit
class TestSessionDefaultMode:
    """Testes do valor padrão de SessionMode."""

    def test_default_mode_e_assisted_sem_env(self) -> None:
        assert SESSION_DEFAULT_MODE in {m.value for m in SessionMode}

    def test_session_mode_enum_valores(self) -> None:
        assert SessionMode.ASSISTED.value == "assisted"
        assert SessionMode.SEMI.value == "semi"
        assert SessionMode.AUTO.value == "auto"


@pytest.mark.unit
class TestFullHelp:
    """Testes do texto de ajuda completo (Tarefa 2 de G10)."""

    def test_help_contem_modos(self) -> None:
        assert "assisted" in FULL_HELP_TEXT
        assert "semi" in FULL_HELP_TEXT
        assert "auto" in FULL_HELP_TEXT

    def test_help_contem_exemplos(self) -> None:
        assert "EXEMPLOS" in FULL_HELP_TEXT
        assert "geminiclaw" in FULL_HELP_TEXT

    def test_print_full_help_nao_lanca_excecao(self, capsys: pytest.CaptureFixture) -> None:
        print_full_help()
        captured = capsys.readouterr()
        assert "GeminiClaw" in captured.out


@pytest.mark.unit
class TestSessionBanner:
    """Testes do banner de inicialização de sessão (Tarefa 3 de G10)."""

    def test_banner_exibe_modo_assistido(self, capsys: pytest.CaptureFixture, tmp_path) -> None:
        print_session_banner(SessionMode.ASSISTED.value, context_dir=str(tmp_path / "no_such_dir"))
        out = capsys.readouterr().out
        assert "assistido" in out

    def test_banner_alerta_sem_contexto(self, capsys: pytest.CaptureFixture, tmp_path) -> None:
        empty_dir = tmp_path / "input_context"
        empty_dir.mkdir()
        print_session_banner(SessionMode.ASSISTED.value, context_dir=str(empty_dir))
        out = capsys.readouterr().out
        assert "Nenhum contexto detectado" in out

    def test_banner_lista_ate_3_arquivos(self, capsys: pytest.CaptureFixture, tmp_path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "artigo.pdf").write_text("x")
        (context_dir / "dados.csv").write_text("x")
        print_session_banner(SessionMode.ASSISTED.value, context_dir=str(context_dir))
        out = capsys.readouterr().out
        assert "artigo.pdf" in out
        assert "dados.csv" in out

    def test_banner_resume_quando_mais_de_3_arquivos(self, capsys: pytest.CaptureFixture, tmp_path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        for i in range(5):
            (context_dir / f"arquivo_{i}.txt").write_text("x")
        print_session_banner(SessionMode.ASSISTED.value, context_dir=str(context_dir))
        out = capsys.readouterr().out
        assert "5 arquivos" in out

    def test_banner_alerta_modo_auto(self, capsys: pytest.CaptureFixture, tmp_path) -> None:
        print_session_banner(SessionMode.AUTO.value, context_dir=str(tmp_path / "no_such_dir"))
        out = capsys.readouterr().out
        assert "Modo autônomo ativo" in out

    def test_banner_nao_alerta_fora_do_modo_auto(self, capsys: pytest.CaptureFixture, tmp_path) -> None:
        print_session_banner(SessionMode.SEMI.value, context_dir=str(tmp_path / "no_such_dir"))
        out = capsys.readouterr().out
        assert "Modo autônomo ativo" not in out
