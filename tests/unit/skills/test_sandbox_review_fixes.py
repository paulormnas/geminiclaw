# ruff: noqa: F811 — a fixture make_sandbox é reexportada e usada como argumento
"""Achados da revisão de segurança do PR #111 (v18.5-sandbox-phases): um grupo de testes por achado."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_sandbox_phases import _FetchDaemon
from test_sandbox_slim import FakeDaemon, _run, make_sandbox  # noqa: F401 — fixture reexportada


# --- A1: a rede exige autorização explícita do classificador ---------------------------------------

@pytest.mark.unit
def test_a1_sem_insumos_e_classificador_padrao_nao_libera_rede(make_sandbox, tmp_path):
    """Sem insumos, ``all([])`` não pode liberar a rede: o classificador padrão não autoriza nada."""
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, needs_network=True)

    assert daemon.run_kwargs["network_disabled"] is True
    assert result.rede_na_execucao is False
    assert "classificador" in result.nota_rede


@pytest.mark.unit
def test_a1_classificador_sem_autorizacao_explicita_nega_antes_de_outras_regras(make_sandbox, tmp_path):
    """Um classificador que só implementa ``is_shareable`` (sem ``network_allowed``) é fail-closed."""

    class SoShareable:
        def is_shareable(self, path):
            return True

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=SoShareable()), tmp_path, needs_network=True)

    assert result.rede_na_execucao is False and "classificador" in result.nota_rede


@pytest.mark.unit
def test_a1_classificador_que_autoriza_sem_insumos_libera_a_rede(make_sandbox, tmp_path):
    class Autoriza:
        def network_allowed(self):
            return True

        def is_shareable(self, path):
            return True

    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, input_classifier=Autoriza()), tmp_path, needs_network=True)

    assert result.rede_na_execucao is True


# --- A2: put_archive só em pontos de montagem (raiz somente leitura) ----------------------------------

@pytest.mark.unit
def test_a2_copy_usa_mount_tmpfs_com_tamanho_e_modo(make_sandbox, tmp_path, monkeypatch):
    """/inputs em modo copy é um ``Mount`` tmpfs (aceita put_archive com a raiz ro), não HostConfig.Tmpfs."""
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    monkeypatch.setenv("SANDBOX_COPY_MAX_BYTES", "1048576")
    snap = tmp_path / "out" / "s" / "input_snapshot"
    snap.mkdir(parents=True)
    (snap / "dados.csv").write_text("a,b\n")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon, memory_limit="1g"), tmp_path)

    mount = next(m for m in daemon.run_kwargs["mounts"] if m["Target"] == "/inputs")
    assert mount["Type"] == "tmpfs"
    assert mount["TmpfsOptions"] == {"SizeBytes": 1048576, "Mode": 0o555}
    assert "/inputs" not in daemon.run_kwargs["tmpfs"]
    assert any(path == "/inputs" for path, _data in daemon.put_archives)


@pytest.mark.unit
def test_a2_fetch_usa_diretorio_de_controle_ro_e_nao_put_archive(make_sandbox, tmp_path):
    """Script e spec do fetch vão no diretório /control (ro), escrito no host antes de criar o container."""
    daemon = _FetchDaemon()
    _run(make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache")), tmp_path,
         assets=[{"url": "https://e.org/p", "destino": "p.bin"}])

    control = [v for v in daemon.prep_kwargs["volumes"].values() if v["bind"] == "/control"]
    assert control == [{"bind": "/control", "mode": "ro"}]
    assert set(daemon.control_files) == {"fetch_assets.py", "fetch_spec.json"}
    assert "https://e.org/p" in daemon.control_files["fetch_spec.json"]
    assert [path for path, _data in daemon.put_archives] == ["/outputs"]  # só o script, em ponto de montagem
    fetch_cmd = next(c for c, _kw in daemon.exec_calls if c[0] == "python" and "fetch" in c[1])
    assert fetch_cmd == ["python", "/control/fetch_assets.py", "/control/fetch_spec.json"]


# --- M1: limites de ativos e de disco ----------------------------------------------------------------

MIB = 1024 * 1024


@pytest.mark.unit
def test_m1_padroes_de_limite_de_ativos(make_sandbox, monkeypatch):
    for name in ("SANDBOX_ASSET_MAX_BYTES", "SANDBOX_ASSET_TOTAL_MAX_BYTES", "SANDBOX_MIN_FREE_BYTES"):
        monkeypatch.delenv(name, raising=False)
    sandbox = make_sandbox(FakeDaemon())

    assert sandbox.asset_max_bytes == 512 * MIB
    assert sandbox.asset_total_max_bytes == 2048 * MIB
    assert sandbox.min_free_bytes > 0


@pytest.mark.unit
def test_m1_spec_do_fetch_leva_o_teto_somado(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_ASSET_TOTAL_MAX_BYTES", "12345")
    daemon = _FetchDaemon()
    _run(make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache")), tmp_path,
         assets=[{"url": "https://e.org/p", "destino": "p.bin"}])

    assert json.loads(daemon.control_files["fetch_spec.json"])["total_max_bytes"] == 12345


@pytest.mark.unit
def test_m1_fetch_recusa_ao_estourar_o_teto_somado(tmp_path, monkeypatch):
    from src.skills.code import fetch_assets

    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(fetch_assets, "STAGING_DIR", str(staging))

    def fake_download(url, destination, max_bytes, allow=()):
        if 6 > max_bytes:
            raise fetch_assets.AssetError(f"o ativo excede o limite de {max_bytes} bytes")
        Path(destination).write_bytes(b"x" * 6)
        return 6

    monkeypatch.setattr(fetch_assets, "download", fake_download)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "assets": [{"url": "https://e.org/a", "destino": "a"}, {"url": "https://e.org/b", "destino": "b"}],
        "max_bytes": 100, "total_max_bytes": 10,
    }))

    assert fetch_assets.main(["x", str(spec)]) == 1  # o segundo ativo ultrapassa 10 bytes somados


@pytest.mark.unit
def test_m1_disco_livre_insuficiente_recusa_antes_dos_containers(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_MIN_FREE_BYTES", str(10 * MIB))
    monkeypatch.setattr("src.skills.code.sandbox.shutil.disk_usage",
                        lambda path: SimpleNamespace(total=100 * MIB, used=95 * MIB, free=5 * MIB))
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, packages=["tabulate"])

    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra" and result.infra_error == "sandbox_disk_low"
    assert "SANDBOX_MIN_FREE_BYTES" in result.stderr


@pytest.mark.unit
def test_m1_disco_livre_suficiente_executa(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_MIN_FREE_BYTES", str(10 * MIB))
    monkeypatch.setattr("src.skills.code.sandbox.shutil.disk_usage",
                        lambda path: SimpleNamespace(total=100 * MIB, used=50 * MIB, free=50 * MIB))
    result = _run(make_sandbox(FakeDaemon()), tmp_path)

    assert result.exit_code == 0 and result.infra_error is None


# --- M2: o tmpfs de /inputs e o /tmp contam na memória do container ---------------------------------

def _snapshot_com_dado(tmp_path):
    snap = tmp_path / "out" / "s" / "input_snapshot"
    snap.mkdir(parents=True)
    (snap / "dados.csv").write_text("a,b\n")


@pytest.mark.unit
def test_m2_padrao_do_modo_copy_ate_64_mib(make_sandbox, monkeypatch):
    monkeypatch.delenv("SANDBOX_COPY_MAX_BYTES", raising=False)
    assert make_sandbox(FakeDaemon()).copy_max_bytes <= 64 * MIB


@pytest.mark.unit
def test_m2_copy_mais_tmpfs_nao_cabe_na_memoria(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    monkeypatch.setenv("SANDBOX_COPY_MAX_BYTES", str(64 * MIB))
    monkeypatch.setenv("SANDBOX_TMPFS_SIZE", "256m")
    _snapshot_com_dado(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, memory_limit="256m"), tmp_path)

    daemon.client.containers.run.assert_not_called()
    assert result.fase_falha == "infra"
    assert "SANDBOX_COPY_MAX_BYTES" in result.stderr and "memória" in result.stderr


@pytest.mark.unit
def test_m2_copy_que_cabe_na_memoria_executa(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "copy")
    monkeypatch.setenv("SANDBOX_COPY_MAX_BYTES", str(64 * MIB))
    monkeypatch.setenv("SANDBOX_TMPFS_SIZE", "64m")
    _snapshot_com_dado(tmp_path)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon, memory_limit="256m"), tmp_path)

    assert result.exit_code == 0 and result.infra_error is None


@pytest.mark.unit
def test_m2_modo_mount_nao_e_afetado(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_INPUT_DELIVERY", "mount")
    monkeypatch.setenv("SANDBOX_TMPFS_SIZE", "256m")
    _snapshot_com_dado(tmp_path)
    result = _run(make_sandbox(FakeDaemon(), memory_limit="256m"), tmp_path)

    assert result.exit_code == 0


# --- M3: a saída do script é limitada antes de chegar ao orquestrador ---------------------------------

@pytest.mark.unit
def test_m3_script_roda_pelo_lancador_com_limite(make_sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_OUTPUT_MAX_BYTES", "4096")
    daemon = FakeDaemon()
    _run(make_sandbox(daemon), tmp_path)

    cmd = next(c for c, _kw in daemon.exec_calls if "/outputs/script.py" in c)
    assert cmd[:3] == ["python", "-I", "-c"] and cmd[-2:] == ["4096", "/outputs/script.py"]


def _run_launcher(tmp_path, script_source: str, cap: int):
    import subprocess
    import sys

    from src.skills.code.sandbox import _RUNNER_CODE

    script = tmp_path / "script_alvo.py"
    script.write_text(script_source)
    return subprocess.run(
        [sys.executable, "-I", "-c", _RUNNER_CODE.replace("['python',", f"[{sys.executable!r},"), str(cap), str(script)],
        capture_output=True, timeout=60,
    )


@pytest.mark.unit
def test_m3_lancador_trunca_saida_gigante_e_preserva_o_fim(tmp_path):
    proc = _run_launcher(
        tmp_path,
        "import sys\n"
        "sys.stdout.write('A' * 3_000_000)\n"
        "sys.stderr.write('B' * 2_000_000 + 'Traceback FINAL')\n"
        "sys.exit(3)\n",
        cap=1024,
    )

    assert proc.returncode == 3
    assert len(proc.stdout) < 1024 + 100 and len(proc.stderr) < 1024 + 100
    assert b"omitidos" in proc.stdout and proc.stdout.startswith(b"A")
    assert proc.stderr.endswith(b"Traceback FINAL")


@pytest.mark.unit
def test_m3_lancador_nao_altera_saida_pequena_e_propaga_sinal(tmp_path):
    proc = _run_launcher(tmp_path, "print('ola')\n", cap=1024)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"ola\n", b"")

    killed = _run_launcher(tmp_path, "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n", cap=1024)
    assert killed.returncode == 137  # OOM continua reconhecível


# --- M4: kill + varredura também nos caminhos de erro; decodificação tolerante -----------------------------

class _CrashAfterPlanting(FakeDaemon):
    """O script planta um symlink para fora e uma FIFO em /outputs e então o exec falha no meio."""

    def __init__(self, task_dir, **kwargs):
        super().__init__(**kwargs)
        self.task_dir = task_dir

    def _exec_run(self, cmd, *args, **kwargs):
        if "/outputs/script.py" in cmd:
            import os

            os.symlink("/etc/passwd", self.task_dir / "escape")
            os.mkfifo(self.task_dir / "fila")
            raise RuntimeError("conexão com o daemon perdida")
        return super()._exec_run(cmd, *args, **kwargs)


@pytest.mark.unit
def test_m4_erro_no_meio_do_exec_ainda_mata_e_varre(make_sandbox, tmp_path):
    task = tmp_path / "out" / "s" / "t"
    task.mkdir(parents=True)
    daemon = _CrashAfterPlanting(task)
    result = _run(make_sandbox(daemon), tmp_path)

    assert result.fase_falha == "infra"
    assert "kill" in daemon.calls and daemon.calls.index("kill") < daemon.calls.index("remove")
    assert not (task / "escape").is_symlink() and not (task / "fila").exists()


class _InvalidUtf8(FakeDaemon):
    def _exec_run(self, cmd, *args, **kwargs):
        if "/outputs/script.py" in cmd:
            return SimpleNamespace(exit_code=0, output=(b"ok \xff\xfe", b"aviso \xc3"))
        return super()._exec_run(cmd, *args, **kwargs)


@pytest.mark.unit
def test_m4_saida_com_bytes_invalidos_nao_derruba_a_execucao(make_sandbox, tmp_path):
    result = _run(make_sandbox(_InvalidUtf8()), tmp_path)

    assert result.infra_error is None and result.exit_code == 0
    assert result.stdout.startswith("ok ") and "\ufffd" in result.stdout and "\ufffd" in result.stderr


# --- M5: /prior é exatamente <saída>/<sessão>, diferente da sessão atual e sem repetição -------------------

def _out(tmp_path):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return out


@pytest.mark.unit
def test_m5_prior_igual_a_raiz_de_saida_e_recusado(make_sandbox, tmp_path):
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, prior_dirs=[_out(tmp_path)])

    daemon.client.containers.run.assert_not_called()
    assert result.infra_error == "sandbox_mount_refused" and "<saída>/<sessão>" in result.stderr


@pytest.mark.unit
def test_m5_prior_igual_a_sessao_atual_e_recusado(make_sandbox, tmp_path):
    atual = _out(tmp_path) / "s"  # a sessão de _run é "s"
    atual.mkdir()
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, prior_dirs=[atual])

    daemon.client.containers.run.assert_not_called()
    assert result.infra_error == "sandbox_mount_refused" and "sessão atual" in result.stderr


@pytest.mark.unit
def test_m5_prior_em_profundidade_maior_e_recusado(make_sandbox, tmp_path):
    funda = _out(tmp_path) / "antiga" / "tarefa"
    funda.mkdir(parents=True)
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, prior_dirs=[funda])

    daemon.client.containers.run.assert_not_called()
    assert result.infra_error == "sandbox_mount_refused"


@pytest.mark.unit
def test_m5_prior_repetido_e_recusado(make_sandbox, tmp_path):
    antiga = _out(tmp_path) / "antiga"
    antiga.mkdir()
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, prior_dirs=[antiga, antiga])

    daemon.client.containers.run.assert_not_called()
    assert "repetida" in result.stderr


# --- M6: verificação dos ativos com o container encerrado e sem seguir symlink -------------------------------

@pytest.mark.unit
def test_m6_prep_e_encerrado_antes_da_verificacao_do_hash(make_sandbox, tmp_path, monkeypatch):
    from src.skills.code import sandbox as sandbox_module

    daemon = _FetchDaemon()
    real = sandbox_module.verify_and_cache

    def spy(*args, **kwargs):
        daemon.calls.append("verify")
        return real(*args, **kwargs)

    monkeypatch.setattr(sandbox_module, "verify_and_cache", spy)
    _run(make_sandbox(daemon, asset_cache_dir=str(tmp_path / "cache")), tmp_path,
         packages=["tabulate"], assets=[{"url": "https://e.org/p", "destino": "p.bin"}])

    calls = daemon.calls
    assert calls.index("fetch") < calls.index("kill") < calls.index("remove") < calls.index("verify")
    assert calls.index("verify") < calls.index("install")  # a instalação roda em outro container, depois


@pytest.mark.unit
def test_m6_hash_nao_segue_symlink(tmp_path):
    from src.skills.code.assets import sha256_file

    (tmp_path / "alvo").write_bytes(b"x")
    (tmp_path / "link").symlink_to(tmp_path / "alvo")
    with pytest.raises(OSError):
        sha256_file(tmp_path / "link")


@pytest.mark.unit
def test_m6_hash_e_calculado_sobre_o_arquivo_ja_movido(tmp_path, monkeypatch):
    from src.skills.code import assets

    staging, cache = tmp_path / "staging", tmp_path / "cache"
    staging.mkdir()
    (staging / "p.bin").write_bytes(b"abc")
    seen = []
    real = assets.sha256_file

    def spy(path):
        seen.append((path.parent == cache, (staging / "p.bin").exists()))
        return real(path)

    monkeypatch.setattr(assets, "sha256_file", spy)
    records, error = assets.verify_and_cache([assets.AssetSpec("https://e.org/p", "p.bin")], staging, cache)

    assert error is None and seen == [(True, False)]  # hasheado no cache, já fora de staging


@pytest.mark.unit
def test_m6_exdev_copia_e_renomeia(tmp_path, monkeypatch):
    import errno
    import hashlib
    import os

    from src.skills.code import assets

    staging, cache = tmp_path / "staging", tmp_path / "cache"
    staging.mkdir()
    (staging / "p.bin").write_bytes(b"conteudo")
    real_replace = os.replace

    def replace(src, dst):
        if os.fspath(src).startswith(str(staging)):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    records, error = assets.verify_and_cache([assets.AssetSpec("https://e.org/p", "p.bin")], staging, cache)

    digest = hashlib.sha256(b"conteudo").hexdigest()
    assert error is None and records[0].sha256 == digest
    assert (cache / digest).read_bytes() == b"conteudo"
    assert not (staging / "p.bin").exists()
    assert sorted(f.name for f in cache.iterdir()) == [digest]  # sem sobras (.part, .incoming)


# --- M7: sem sha256 declarado só https; redirect https -> http é sempre recusado -----------------------------

@pytest.mark.unit
def test_m7_http_sem_sha256_e_recusado_e_com_sha256_e_aceito():
    from src.skills.code.assets import parse_assets

    specs, errors = parse_assets([{"url": "http://exemplo.org/a", "destino": "a"}])
    assert specs == [] and "https" in errors[0]

    specs, errors = parse_assets([{"url": "https://exemplo.org/a", "destino": "a"}])
    assert errors == [] and len(specs) == 1

    specs, errors = parse_assets([{"url": "http://exemplo.org/a", "destino": "a", "sha256": "a" * 64}])
    assert errors == [] and len(specs) == 1


@pytest.mark.unit
def test_m7_http_sem_sha256_nao_cria_containers(make_sandbox, tmp_path):
    daemon = FakeDaemon()
    result = _run(make_sandbox(daemon), tmp_path, assets=[{"url": "http://exemplo.org/a", "destino": "a"}])

    daemon.client.containers.run.assert_not_called()
    assert result.exit_code == -1 and "https" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("sha_declarado", [False, True])
def test_m7_redirect_de_https_para_http_e_recusado(tmp_path, monkeypatch, sha_declarado):
    from src.skills.code import fetch_assets

    class Resp:
        status = 302

        def getheader(self, name):
            return "http://exemplo.org/destino" if name == "Location" else None

    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Resp()

        def close(self):
            pass

    monkeypatch.setattr(fetch_assets, "_resolve", lambda *a, **k: "93.184.216.34")
    monkeypatch.setattr(fetch_assets, "_PinnedHTTPSConnection", Conn)
    monkeypatch.setattr(fetch_assets, "_PinnedHTTPConnection", Conn)
    with pytest.raises(fetch_assets.AssetError, match="https para http"):
        fetch_assets.download("https://exemplo.org/a", str(tmp_path / "a"), 100)
