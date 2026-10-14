"""Reset isolado dos bancos de benchmark (``openspec/specs/benchmark``).

Recria do zero o banco PostgreSQL **de benchmark** e apaga as coleções do sistema no Qdrant, para que cada execução
comece sem o que a anterior gravou. É uma operação destrutiva: só age com as quatro guardas satisfeitas
(:func:`check_guards`) e grava antes um arquivo de segurança (``pg_dump`` e snapshots do Qdrant).

Sequência de bootstrap de uma instalação nova (levantada do código e do ``docker-compose.yml``; a ordem importa):

1. ``scripts/init_db.sql``: no Postgres do projeto é montado em ``docker-entrypoint-initdb.d`` e só roda na criação do
   volume; um banco criado depois (como o de benchmark) não o recebe sozinho, por isso o reset o aplica.
2. ``scripts/migrate_v17_knowledge.py``: extensão Apache AGE, grafo, ``knowledge_audit``, rótulos e papel
   ``knowledge_reader``.
3. ``scripts/migrations/v18_5_*.sql`` pela ordem do nome (``egress_log``, ``execution_records`` com gatilhos, versão do
   modelo). São idempotentes e complementam o ``init_db.sql``. O pool de ``src/db.py`` não aplica migração alguma (só
   carrega o AGE em cada conexão), então nenhum passo fica oculto ali.
4. ``scripts/seed_vocabulary.py``: domínios CNPq e métricas aprovadas (a ``Metrica`` ``acuracia``).

Os passos 2 e 4 rodam em subprocessos com ``DATABASE_URL``, ``KNOWLEDGE_READER_DATABASE_URL`` e ``QDRANT_URL`` do alvo
(:func:`target_env`), porque esses scripts leem a configuração do processo. Nada é impresso com senha.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
INIT_SQL = ROOT / "scripts" / "init_db.sql"
MIGRATIONS_DIR = ROOT / "scripts" / "migrations"
POSTGRES_CONTAINER = "geminiclaw-postgres"
DEFAULT_MARKER = "bench"
# Coleções do sistema no Qdrant (design §2.1): REINDEXABLE_COLLECTIONS mais KNOWLEDGE_COLLECTION.
SYSTEM_COLLECTIONS_STATIC = ("geminiclaw_documents", "geminiclaw_knowledge")
# Tabelas que a conferência exige vazias após o reset (``knowledge_audit`` recebe a carga do vocabulário).
EMPTY_TABLES = (
    "agent_sessions", "agent_events", "token_usage", "subtask_metrics", "hardware_snapshots", "egress_log",
    "execution_records", "long_term_memory", "similarity_queue", "document_chunks",
)
EXPECTED_TABLES = (*EMPTY_TABLES, "knowledge_audit")
EXIT_RESET_FAILED = 4


class ResetRefused(RuntimeError):
    """Uma guarda do reset não foi satisfeita; nada foi escrito."""


class ResetError(RuntimeError):
    """O reset falhou depois das guardas (dump, recriação, bootstrap ou conferência)."""


@dataclass(frozen=True)
class BenchmarkTarget:
    """Alvo do reset: o banco PostgreSQL e o Qdrant de benchmark."""

    database_url: str
    qdrant_url: str
    marker: str = DEFAULT_MARKER
    dev_database_url: str | None = None
    graph_name: str = "knowledge"
    knowledge_collection: str = "knowledge_nodes"
    # Substitui a lista de coleções do sistema (testes de integração usam nomes descartáveis).
    collections: tuple[str, ...] | None = None

    @property
    def database(self) -> str:
        return urlsplit(self.database_url).path.lstrip("/")

    @property
    def host(self) -> str:
        return urlsplit(self.database_url).hostname or ""

    @property
    def label(self) -> str:
        """``banco@host``: o valor que ``--confirm-target`` deve repetir."""
        return f"{self.database}@{self.host}"

    @property
    def safe_url(self) -> str:
        return redact_url(self.database_url)

    @property
    def system_collections(self) -> tuple[str, ...]:
        if self.collections is not None:
            return self.collections
        return tuple(dict.fromkeys((self.knowledge_collection, *SYSTEM_COLLECTIONS_STATIC)))

    @classmethod
    def from_env(cls, env: dict[str, str]) -> BenchmarkTarget:
        """Monta o alvo de ``BENCHMARK_*`` (e ``DATABASE_URL``, só para a guarda 4).

        Raises:
            ResetRefused: ``BENCHMARK_DATABASE_URL`` ausente.
        """
        url = (env.get("BENCHMARK_DATABASE_URL") or "").strip()
        if not url:
            raise ResetRefused("BENCHMARK_DATABASE_URL não definida: o reset só age sobre o banco de benchmark.")
        return cls(
            database_url=url,
            qdrant_url=(env.get("BENCHMARK_QDRANT_URL") or env.get("QDRANT_URL") or "http://localhost:6333").strip(),
            marker=(env.get("BENCHMARK_DB_MARKER") or DEFAULT_MARKER).strip() or DEFAULT_MARKER,
            dev_database_url=(env.get("DATABASE_URL") or "").strip() or None,
            graph_name=env.get("KNOWLEDGE_GRAPH_NAME") or "knowledge",
            knowledge_collection=env.get("KNOWLEDGE_COLLECTION") or "knowledge_nodes",
        )


@dataclass
class ResetReport:
    """O que o reset fez; vai para ``reset`` no resultado da repetição."""

    database: str
    host: str
    dump_path: str | None = None
    qdrant_snapshots: list[str] = field(default_factory=list)
    dropped_collections: list[str] = field(default_factory=list)
    migrations_applied: list[str] = field(default_factory=list)
    vocabulary: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def redact_url(url: str) -> str:
    """A URL sem a senha (``user:***@host``), para mensagens e logs."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = parts.username or ""
    return urlunsplit(parts._replace(netloc=f"{user}:***@{host}"))


def check_guards(target: BenchmarkTarget, *, reset_requested: bool, confirm_target: str | None) -> None:
    """As quatro guardas do reset (design §2.1); falta qualquer uma, recusa antes de escrever.

    Raises:
        ResetRefused: Guarda não satisfeita, com a causa e o alvo (sem senha).
    """
    if not reset_requested:
        raise ResetRefused("O reset exige --reset-stores na linha de comando.")
    if confirm_target != target.label:
        raise ResetRefused(
            f"--confirm-target {confirm_target!r} não coincide com o alvo; repita exatamente "
            f"'--confirm-target {target.label}' (URL: {target.safe_url})."
        )
    if target.marker not in target.database:
        raise ResetRefused(
            f"O banco '{target.database}' não contém a marca de benchmark '{target.marker}' "
            f"(BENCHMARK_DB_MARKER); o reset recusa bancos que não são de benchmark."
        )
    if target.dev_database_url and urlsplit(target.dev_database_url).path.lstrip("/") == target.database:
        raise ResetRefused(
            f"O banco de benchmark '{target.database}' é o mesmo de DATABASE_URL (desenvolvimento); use outro banco."
        )


def target_env(target: BenchmarkTarget, base: dict[str, str]) -> dict[str, str]:
    """Ambiente com os bancos de benchmark no lugar dos de desenvolvimento (subprocessos e o próprio runner)."""
    env = dict(base)
    env["DATABASE_URL"] = target.database_url
    env["QDRANT_URL"] = target.qdrant_url
    reader = env.get("KNOWLEDGE_READER_DATABASE_URL")
    if reader:  # mesmo servidor, outro banco: o leitor precisa enxergar o grafo de benchmark
        parts = urlsplit(reader)
        env["KNOWLEDGE_READER_DATABASE_URL"] = urlunsplit(parts._replace(path=f"/{target.database}"))
    return env


# --------------------------------------------------------------------------------------------
# Passos (funções pequenas, substituíveis nos testes)
# --------------------------------------------------------------------------------------------


def _admin_url(target: BenchmarkTarget) -> str:
    parts = urlsplit(target.database_url)
    return urlunsplit(parts._replace(path="/postgres"))


def _database_exists(target: BenchmarkTarget) -> bool:
    import psycopg

    with psycopg.connect(_admin_url(target), autocommit=True) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target.database,)).fetchone() is not None


def _dump_postgres(target: BenchmarkTarget, dest: Path) -> Path:
    """``pg_dump -Fc`` do banco de benchmark: no host se houver ``pg_dump``, senão pelo container ``postgres``.

    A senha viaja só em ``PGPASSWORD`` (nunca em argumento).

    Raises:
        ResetError: Nenhuma ferramenta disponível ou o dump falhou.
    """
    parts = urlsplit(target.database_url)
    dest.mkdir(parents=True, exist_ok=True)
    dump_file = dest / f"{target.database}.dump"
    env = {**os.environ, "PGPASSWORD": parts.password or ""}
    user = parts.username or "postgres"
    if shutil.which("pg_dump"):
        cmd = ["pg_dump", "-Fc", "-h", parts.hostname or "localhost", "-p", str(parts.port or 5432), "-U", user,
               "-f", str(dump_file), target.database]
        run_kwargs: dict = {}
    elif shutil.which("docker"):
        cmd = ["docker", "exec", "-e", "PGPASSWORD", POSTGRES_CONTAINER, "pg_dump", "-Fc", "-h", "127.0.0.1",
               "-U", user, target.database]
        run_kwargs = {"stdout": dump_file.open("wb")}
    else:
        raise ResetError("pg_dump indisponível: nem no host nem pelo container postgres (use --no-pre-reset-dump).")
    try:
        proc = subprocess.run(cmd, env=env, stderr=subprocess.PIPE, timeout=600, **run_kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResetError(f"pg_dump falhou: {type(exc).__name__}: {exc}") from exc
    finally:
        if "stdout" in run_kwargs:
            run_kwargs["stdout"].close()
    if proc.returncode != 0 or not dump_file.is_file() or dump_file.stat().st_size == 0:
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
        raise ResetError(f"pg_dump terminou com código {proc.returncode}: {detail}")
    return dump_file


def _qdrant_client(target: BenchmarkTarget):
    from qdrant_client import QdrantClient

    return QdrantClient(url=target.qdrant_url)


def _snapshot_qdrant(target: BenchmarkTarget, dest: Path) -> list[str]:
    """Snapshot (e download) de cada coleção do sistema que existe; devolve os arquivos gravados."""
    import httpx

    client = _qdrant_client(target)
    existing = {c.name for c in client.get_collections().collections}
    saved: list[str] = []
    for name in target.system_collections:
        if name not in existing:
            continue
        snapshot = client.create_snapshot(collection_name=name)
        if snapshot is None:
            raise ResetError(f"Qdrant não criou o snapshot da coleção '{name}'.")
        dest.mkdir(parents=True, exist_ok=True)
        file = dest / f"{name}-{snapshot.name}"
        url = f"{target.qdrant_url.rstrip('/')}/collections/{name}/snapshots/{snapshot.name}"
        try:
            with httpx.stream("GET", url, timeout=300.0) as response:
                response.raise_for_status()
                with file.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise ResetError(f"Download do snapshot de '{name}' falhou: {type(exc).__name__}: {exc}") from exc
        saved.append(str(file))
    return saved


def _drop_qdrant(target: BenchmarkTarget) -> list[str]:
    client = _qdrant_client(target)
    existing = {c.name for c in client.get_collections().collections}
    dropped = []
    for name in target.system_collections:
        if name in existing:
            client.delete_collection(name)
            dropped.append(name)
    return dropped


def _recreate_database(target: BenchmarkTarget) -> None:
    """``DROP DATABASE ... WITH (FORCE)`` e ``CREATE DATABASE``: dispensa TRUNCATE e os gatilhos somente-acréscimo."""
    import psycopg
    from psycopg import sql

    ident = sql.Identifier(target.database)
    with psycopg.connect(_admin_url(target), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(ident))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(ident))


def _run_script(args: list[str], env: dict[str, str]) -> str:
    proc = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise ResetError(f"{' '.join(args)} terminou com código {proc.returncode}: {tail}")
    return proc.stdout


def _bootstrap(target: BenchmarkTarget, env: dict[str, str], report: ResetReport) -> None:
    import psycopg

    with psycopg.connect(target.database_url, autocommit=True) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
        report.migrations_applied.append(INIT_SQL.name)
    _run_script(["scripts/migrate_v17_knowledge.py"], env)
    report.migrations_applied.append("migrate_v17_knowledge.py")
    with psycopg.connect(target.database_url, autocommit=True) as conn:
        conn.execute("SET search_path TO public")
        for sql_file in sorted(MIGRATIONS_DIR.glob("v18_5_*.sql")):
            conn.execute(sql_file.read_text(encoding="utf-8"))
            report.migrations_applied.append(sql_file.name)
    out = _run_script(["scripts/seed_vocabulary.py"], env)
    for item in out.strip().splitlines()[-1].split(","):
        key, _, value = item.strip().partition("=")
        if value.isdigit():
            report.vocabulary[key] = int(value)


def _verify(target: BenchmarkTarget) -> list[str]:
    """Conferência pós-reset (design §2.3, item 4); devolve as falhas (vazio = tudo certo)."""
    import psycopg

    problems: list[str] = []
    with psycopg.connect(target.database_url, autocommit=True) as conn:
        for table in EXPECTED_TABLES:
            row = conn.execute("SELECT to_regclass(%s) AS name", (f"public.{table}",)).fetchone()
            if not row[0]:
                row = conn.execute("SELECT to_regclass(%s) AS name", (f"ag_catalog.{table}",)).fetchone()
            if not row[0]:
                problems.append(f"tabela ausente: {table}")
                continue
            if table in EMPTY_TABLES:
                count = conn.execute(f"SELECT count(*) FROM {row[0]}").fetchone()[0]
                if count:
                    problems.append(f"tabela {table} não está vazia ({count} linhas)")
        graph = conn.execute("SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s", (target.graph_name,)).fetchone()
        if graph is None:
            problems.append(f"grafo '{target.graph_name}' ausente")
        else:
            conn.execute("LOAD 'age'")
            conn.execute('SET search_path = ag_catalog, "$user", public')
            query = (
                f"SELECT * FROM cypher('{target.graph_name}', $$ MATCH (m:Metrica) "
                "WHERE m.nome = 'acuracia' AND m.status = 'aprovado' RETURN m.sinonimos $$) AS (s agtype)"
            )
            rows = conn.execute(query).fetchall()
            if not rows:
                problems.append("Metrica 'acuracia' aprovada ausente do vocabulário")
            elif "accuracy" not in str(rows[0][0]):
                problems.append("Metrica 'acuracia' sem o sinônimo 'accuracy'")
    client = _qdrant_client(target)
    for collection in client.get_collections().collections:
        # A carga do vocabulário pode indexar termos em ``knowledge_nodes``; as demais devem estar vazias.
        if collection.name in target.system_collections and collection.name != target.knowledge_collection:
            count = int(client.get_collection(collection.name).points_count or 0)
            if count:
                problems.append(f"coleção {collection.name} do Qdrant não está vazia ({count} pontos)")
    return problems


def reset_stores(
    target: BenchmarkTarget, *, archive_dir: Path, dump: bool = True, base_env: dict[str, str] | None = None
) -> ResetReport:
    """Arquiva, recria o banco de benchmark e as coleções do Qdrant, aplica o bootstrap e confere.

    As guardas (:func:`check_guards`) são responsabilidade de quem chama, antes desta função.

    Args:
        target: Banco e Qdrant de benchmark.
        archive_dir: ``<results>.d/<combinação>/r<r>``; o arquivo de segurança vai em ``pre_reset/``.
        dump: ``False`` com ``--no-pre-reset-dump``.
        base_env: Ambiente herdado pelos scripts de bootstrap (padrão: ``os.environ``).

    Raises:
        ResetError: Falha no arquivo de segurança (nada foi apagado), na recriação, no bootstrap ou na conferência.
    """
    started = time.monotonic()
    report = ResetReport(database=target.database, host=target.host)
    if dump:
        safety = archive_dir / "pre_reset"
        if _database_exists(target):
            report.dump_path = str(_dump_postgres(target, safety))
        report.qdrant_snapshots = _snapshot_qdrant(target, safety)
    report.dropped_collections = _drop_qdrant(target)
    _recreate_database(target)
    _bootstrap(target, target_env(target, base_env if base_env is not None else dict(os.environ)), report)
    problems = _verify(target)
    if problems:
        raise ResetError("Conferência pós-reset falhou: " + "; ".join(problems))
    report.duration_s = round(time.monotonic() - started, 1)
    return report


def main() -> int:  # pragma: no cover - uso manual
    import argparse

    from dotenv import dotenv_values

    parser = argparse.ArgumentParser(description="Reset do banco e das coleções de benchmark (operação destrutiva).")
    parser.add_argument("--reset-stores", action="store_true")
    parser.add_argument("--confirm-target", default=None)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--no-pre-reset-dump", action="store_true")
    args = parser.parse_args()
    env = {**dotenv_values(".env"), **os.environ}
    try:
        target = BenchmarkTarget.from_env({k: v for k, v in env.items() if v is not None})
        check_guards(target, reset_requested=args.reset_stores, confirm_target=args.confirm_target)
        print(json.dumps(reset_stores(target, archive_dir=args.archive_dir, dump=not args.no_pre_reset_dump).to_dict(),
                         indent=2))
    except ResetRefused as exc:
        print(f"Recusado: {exc}", file=sys.stderr)
        return 2
    except ResetError as exc:
        print(f"Falha: {exc}", file=sys.stderr)
        return EXIT_RESET_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main())
