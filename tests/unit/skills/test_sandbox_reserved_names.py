"""Nomes reservados do orquestrador: o sandbox não pode forjar ``curator_*.jsonl`` da sessão (revisão de segurança M4).

``outputs/<sessão>/curator_suggestions.jsonl`` e ``curator_flags.jsonl`` são lidos pelo orquestrador/Curator como
registros próprios. Com ``task_name="."`` o bind mount do sandbox seria a pasta da sessão inteira (e com
``session_id="."`` a raiz de todas as sessões), dando ao código gerado escrita nesses arquivos.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.skills.code.sandbox import PythonSandbox


@pytest.fixture
def sandbox(tmp_path: Path):
    with patch("src.skills.code.sandbox.docker.from_env") as mock_env:
        mock_env.return_value = MagicMock()
        yield PythonSandbox(work_dir=str(tmp_path / "work"))


def _run(sandbox: PythonSandbox, tmp_path: Path, session: str, task: str):
    return sandbox.run(code="pass", session_id=session, task_name=task, output_dir=str(tmp_path / "out"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "session,task",
    [
        ("s", "."),
        (".", "t"),
        (".", "."),
        ("s", "curator_flags.jsonl"),
        ("Curator_Suggestions.JSONL", "t"),
    ],
)
def test_nomes_que_alcancam_a_pasta_da_sessao_ou_reservados_sao_recusados(sandbox, tmp_path, session, task):
    (tmp_path / "out" / "s").mkdir(parents=True)
    result = _run(sandbox, tmp_path, session, task)
    assert result.exit_code == -1 and "Nome inválido" in result.stderr
    sandbox.client.containers.run.assert_not_called()


@pytest.mark.unit
def test_pasta_da_tarefa_que_e_symlink_para_a_sessao_e_recusada(sandbox, tmp_path):
    session = tmp_path / "out" / "s"
    session.mkdir(parents=True)
    (session / "t").symlink_to(session)
    result = _run(sandbox, tmp_path, "s", "t")
    assert result.exit_code == -1 and "Nome inválido" in result.stderr
    sandbox.client.containers.run.assert_not_called()


@pytest.mark.unit
def test_arquivo_reservado_criado_no_container_e_removido_com_erro_explicito(sandbox, tmp_path):
    task_dir = tmp_path / "out" / "s" / "t"
    container = MagicMock()

    def run_container(**kwargs):
        (task_dir / "Curator_Suggestions.jsonl").write_text('{"evento": "sugestao"}')
        (task_dir / "sub").mkdir()
        (task_dir / "sub" / "CURATOR_FLAGS.JSONL").write_text("{}")
        (task_dir / "legitimo.txt").write_text("ok")
        return container

    sandbox.client.containers.run.side_effect = run_container
    container.exec_run.return_value = MagicMock(output=(b"", b""), exit_code=0)

    result = _run(sandbox, tmp_path, "s", "t")

    assert not (task_dir / "Curator_Suggestions.jsonl").exists()
    assert not (task_dir / "sub" / "CURATOR_FLAGS.JSONL").exists()
    assert (task_dir / "legitimo.txt").read_text() == "ok"
    assert result.exit_code != 0 and "reservado" in result.stderr


@pytest.mark.unit
def test_nomes_reservados_coincidem_com_os_arquivos_do_curator():
    from src.knowledge.curator_flags import FLAGS_FILENAME
    from src.knowledge.suggestions import FILENAME
    from src.reserved_files import RESERVED_SESSION_FILES

    assert RESERVED_SESSION_FILES == {FILENAME, FLAGS_FILENAME}
