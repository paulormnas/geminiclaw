"""Manifesto de imagens, plano e obtenção conferida (v16-platform-images, designs §1, §3 e §4).

O manifesto ``containers/images.yaml`` lista as imagens do projeto, as arquiteturas suportadas e as plataformas onde
cada uma foi validada. ``plan`` calcula, sem efeitos, o que fazer em cada imagem; ``ensure`` obtém (``pull``/``build``
com ``platform=linux/<arquitetura do daemon>``), confere a arquitetura da imagem obtida e grava ``store/platform.json``.
Arquitetura fora das suportadas interrompe sem tentar emulação. O cliente de containers é injetável (testes).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.logger import get_logger
from src.platform_info import PlatformInfo, detect_current, normalize_arch

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "containers" / "images.yaml"
PLATFORM_FILE = PROJECT_ROOT / "store" / "platform.json"
MANIFEST_VERSION = 1
ENSURE_COMMAND = "uv run python -m scripts.platform_images ensure --imagens sandbox"

OBTER_VALUES = ("pull", "build", "compose")
_ALLOWED_KEYS = {
    "obter", "dockerfile", "tag_env", "tag_padrao", "referencia_env", "referencia_padrao", "arquiteturas",
    "validada_em", "opcional", "contexto",
}
_REQUIRED_BY_OBTER = {
    "build": ("dockerfile", "tag_env", "tag_padrao"),
    "pull": ("referencia_padrao",),
    "compose": ("dockerfile",),
}

STATE_OK = "ok"
STATE_PULL = "pull"
STATE_BUILD = "build"
STATE_COMPOSE = "compose"
STATE_UNSUPPORTED = "sem_suporte"
WARNING_NOT_VALIDATED = "nao_validada"


class PlatformImageError(RuntimeError):
    """Erro acionável da seleção/obtenção de imagens (a mensagem diz o que fazer)."""


class ManifestError(PlatformImageError):
    """Manifesto de imagens inválido (chave desconhecida, forma de obtenção inválida, campo ausente)."""


@dataclass(frozen=True)
class ImageSpec:
    """Entrada validada do manifesto."""

    nome: str
    obter: str
    arquiteturas: tuple[str, ...]
    validada_em: tuple[str, ...] = ()
    dockerfile: str | None = None
    tag_env: str | None = None
    tag_padrao: str | None = None
    referencia_env: str | None = None
    referencia_padrao: str | None = None
    opcional: bool = False
    contexto: tuple[str, ...] = ()  # caminhos (relativos à raiz) enviados ao build; vazio = a raiz inteira

    @property
    def reference(self) -> str:
        """Referência efetiva da imagem (ambiente > padrão do manifesto)."""
        from src import config

        if self.obter == "compose":  # construída pelo compose: não há referência para consultar
            return str(self.dockerfile)
        env_name = self.tag_env or self.referencia_env
        default = self.tag_padrao or self.referencia_padrao
        if env_name:
            value = getattr(config, env_name, None) or os.environ.get(env_name)
            if value:
                return str(value)
        if not default:
            raise ManifestError(f"A imagem '{self.nome}' (obter: {self.obter}) não tem referência no manifesto.")
        return default


def _as_str_tuple(name: str, key: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ManifestError(f"Imagem '{name}': '{key}' deve ser uma lista de textos.")
    return tuple(value)


def parse_manifest(data: Any) -> dict[str, ImageSpec]:
    """Valida o manifesto (esquema estrito) e devolve as imagens por nome.

    Raises:
        ManifestError: Versão diferente, chave desconhecida, forma de obtenção inválida ou campo obrigatório ausente.
    """
    if not isinstance(data, Mapping) or set(data) - {"versao", "imagens"}:
        raise ManifestError("O manifesto deve ter exatamente as chaves 'versao' e 'imagens'.")
    if data.get("versao") != MANIFEST_VERSION:
        raise ManifestError(f"Versão do manifesto {data.get('versao')!r} não suportada (esperada: {MANIFEST_VERSION}).")
    images = data.get("imagens")
    if not isinstance(images, Mapping) or not images:
        raise ManifestError("'imagens' deve ser um mapa não vazio.")
    result: dict[str, ImageSpec] = {}
    for name, raw in images.items():
        if not isinstance(raw, Mapping):
            raise ManifestError(f"Imagem '{name}': a entrada deve ser um mapa.")
        unknown = set(raw) - _ALLOWED_KEYS
        if unknown:
            raise ManifestError(f"Imagem '{name}': chave(s) desconhecida(s) {sorted(unknown)}.")
        obter = raw.get("obter")
        if obter not in OBTER_VALUES:
            raise ManifestError(f"Imagem '{name}': 'obter' deve ser um de {list(OBTER_VALUES)} (recebido: {obter!r}).")
        missing = [key for key in _REQUIRED_BY_OBTER[obter] if not raw.get(key)]
        if missing:
            raise ManifestError(f"Imagem '{name}' (obter: {obter}): campo(s) obrigatório(s) ausente(s) {missing}.")
        archs = _as_str_tuple(name, "arquiteturas", raw.get("arquiteturas"))
        if not archs:
            raise ManifestError(f"Imagem '{name}': 'arquiteturas' não pode ser vazia.")
        result[str(name)] = ImageSpec(
            nome=str(name),
            obter=obter,
            arquiteturas=archs,
            validada_em=_as_str_tuple(name, "validada_em", raw.get("validada_em", [])),
            dockerfile=raw.get("dockerfile"),
            tag_env=raw.get("tag_env"),
            tag_padrao=raw.get("tag_padrao"),
            referencia_env=raw.get("referencia_env"),
            referencia_padrao=raw.get("referencia_padrao"),
            opcional=bool(raw.get("opcional", False)),
            contexto=_as_str_tuple(name, "contexto", raw["contexto"]) if "contexto" in raw else (),
        )
    return result


def load_manifest(path: Path | str = MANIFEST_PATH) -> dict[str, ImageSpec]:
    """Lê e valida ``containers/images.yaml``.

    Raises:
        ManifestError: Arquivo ausente, YAML inválido ou esquema violado.
    """
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"Manifesto de imagens ilegível em '{path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"Manifesto de imagens com YAML inválido em '{path}': {exc}") from exc
    return parse_manifest(data)


# -- plano ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanItem:
    """Estado de uma imagem no plano."""

    nome: str
    estado: str
    referencia: str
    avisos: tuple[str, ...] = ()
    detalhe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"nome": self.nome, "estado": self.estado, "referencia": self.referencia,
                "avisos": list(self.avisos), "detalhe": self.detalhe}


def select_images(
    manifest: Mapping[str, ImageSpec], names: Iterable[str] | None = None, *, with_ollama: bool = False
) -> list[ImageSpec]:
    """Imagens do plano: as pedidas em ``names`` ou todas as não opcionais (+ opcionais com ``with_ollama``)."""
    if names:
        unknown = [n for n in names if n not in manifest]
        if unknown:
            raise PlatformImageError(f"Imagem(ns) fora do manifesto: {unknown}. Disponíveis: {sorted(manifest)}.")
        return [manifest[n] for n in names]
    return [spec for spec in manifest.values() if not spec.opcional or (with_ollama and spec.nome == "ollama")]


def _local_image(client: Any, reference: str) -> Any | None:
    """A imagem local ou ``None`` se não existir."""
    try:
        return client.images.get(reference)
    except Exception as exc:  # noqa: BLE001 - ImageNotFound e erros de API: sem a imagem local, o plano manda obter
        if type(exc).__name__ in ("ImageNotFound", "NotFound"):
            return None
        raise PlatformImageError(f"Não foi possível consultar a imagem '{reference}': {exc}") from exc


def _image_arch(image: Any) -> str | None:
    attrs = getattr(image, "attrs", None)
    return normalize_arch(attrs.get("Architecture")) if isinstance(attrs, dict) else None


def plan_images(
    specs: Iterable[ImageSpec], platform_info: PlatformInfo, client: Any
) -> list[PlanItem]:
    """Calcula o estado de cada imagem, **sem baixar nem construir nada**.

    ``ok`` (presente com a arquitetura do daemon), ``pull``, ``build``, ``compose`` (construída pelo compose) ou
    ``sem_suporte`` (arquitetura do daemon fora de ``arquiteturas``); ``nao_validada`` entra em ``avisos`` quando a
    plataforma não está em ``validada_em``.

    Raises:
        PlatformImageError: Daemon de containers não consultado (sem arquitetura alvo).
    """
    arch = platform_info.daemon_arch
    if not arch:
        raise PlatformImageError(
            "Daemon de containers inacessível: a arquitetura alvo das imagens é a do daemon. "
            "Inicie o Docker (ou o Docker Desktop) e repita."
        )
    items: list[PlanItem] = []
    for spec in specs:
        reference = spec.reference
        warnings = () if platform_info.id in spec.validada_em else (WARNING_NOT_VALIDATED,)
        if arch not in spec.arquiteturas:
            items.append(PlanItem(spec.nome, STATE_UNSUPPORTED, reference, warnings,
                                  f"arquitetura {arch} fora das suportadas {list(spec.arquiteturas)}"))
            continue
        if spec.obter == "compose":
            items.append(PlanItem(spec.nome, STATE_COMPOSE, reference, warnings,
                                  "construída pelo `docker compose up`"))
            continue
        image = _local_image(client, reference)
        if image is None:
            items.append(PlanItem(spec.nome, spec.obter, reference, warnings, "ausente localmente"))
        elif _image_arch(image) == arch:
            items.append(PlanItem(spec.nome, STATE_OK, reference, warnings))
        else:
            items.append(PlanItem(spec.nome, spec.obter, reference, warnings,
                                  f"arquitetura local {_image_arch(image)} difere da do daemon ({arch})"))
    return items


# -- obtenção -------------------------------------------------------------------------------------


@dataclass
class EnsureResult:
    """Resultado de ``ensure``."""

    plataforma: PlatformInfo
    imagens: dict[str, dict[str, Any]] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


def _record(spec: ImageSpec, image: Any, arch: str | None, validated: bool) -> dict[str, Any]:
    return {
        "referencia": spec.reference,
        "id": getattr(image, "id", None),
        "arquitetura": arch,
        "validada": validated,
    }


def ensure_images(
    specs: Iterable[ImageSpec],
    platform_info: PlatformInfo,
    client: Any,
    *,
    assume_yes: bool = False,
    input_fn: Callable[[str], str] = input,
    project_root: Path = PROJECT_ROOT,
    platform_file: Path | None = PLATFORM_FILE,
    out: Callable[[str], Any] = print,
) -> EnsureResult:
    """Executa o plano: confirma, obtém com ``platform=linux/<daemon>``, confere a arquitetura e grava o resultado.

    Raises:
        PlatformImageError: Arquitetura sem suporte (nada é baixado), arquitetura divergente após a obtenção,
            confirmação negada ou falha do daemon.
    """
    specs = list(specs)
    plan = plan_images(specs, platform_info, client)
    unsupported = [item for item in plan if item.estado == STATE_UNSUPPORTED]
    if unsupported:
        names = ", ".join(item.nome for item in unsupported)
        supported = {s.nome: list(s.arquiteturas) for s in specs if s.nome in {i.nome for i in unsupported}}
        raise PlatformImageError(
            f"Arquitetura {platform_info.daemon_arch} sem suporte para: {names}. Arquiteturas suportadas: "
            f"{supported}. A emulação não é tentada."
        )
    result = EnsureResult(plataforma=platform_info)
    target = platform_info.target
    by_name = {s.nome: s for s in specs}
    for item in plan:
        spec = by_name[item.nome]
        validated = WARNING_NOT_VALIDATED not in item.avisos
        if WARNING_NOT_VALIDATED in item.avisos:
            result.avisos.append(f"{item.nome}: plataforma {platform_info.id} ainda não validada para esta imagem.")
        if item.estado in (STATE_COMPOSE, STATE_OK):
            image = _local_image(client, item.referencia) if item.estado == STATE_OK else None
            result.imagens[item.nome] = _record(spec, image, _image_arch(image) if image else None, validated)
            if item.estado == STATE_COMPOSE:
                result.imagens[item.nome]["observacao"] = "construída pelo docker compose"
            continue
        if not assume_yes:
            answer = input_fn(f"{item.estado} de '{item.referencia}' para {target}? [s/N] ")
            if answer.strip().lower() not in ("s", "sim", "y", "yes"):
                raise PlatformImageError(
                    f"Obtenção de '{item.nome}' negada pelo pesquisador; nada foi alterado nesta imagem."
                )
        out(f"{item.estado}: {item.referencia} ({target})")
        try:
            if item.estado == STATE_PULL:
                image = client.images.pull(item.referencia, platform=target)
            else:  # build
                with build_context(spec, project_root) as context_dir:
                    image, _logs = client.images.build(
                        path=str(context_dir), dockerfile=spec.dockerfile, tag=item.referencia, platform=target,
                        rm=True,
                    )
        except PlatformImageError:
            raise
        except Exception as exc:  # noqa: BLE001 - qualquer falha do daemon vira erro acionável
            raise PlatformImageError(
                f"Falha em {item.estado} de '{item.referencia}': {type(exc).__name__}: {exc}"
            ) from exc
        if isinstance(image, list):  # pull sem tag pode devolver lista
            image = image[0] if image else None
        arch = _image_arch(image)
        if arch != platform_info.daemon_arch:
            raise PlatformImageError(
                f"A imagem '{item.referencia}' obtida tem arquitetura {arch}, mas o daemon é "
                f"{platform_info.daemon_arch}. Nada foi registrado para ela."
            )
        result.imagens[item.nome] = _record(spec, image, arch, validated)
    if platform_file is not None:
        write_platform_file(result, platform_file)
    return result


@contextlib.contextmanager
def build_context(spec: ImageSpec, project_root: Path) -> Iterator[Path]:
    """Diretório de contexto do build: a raiz, ou uma cópia só com os caminhos de ``contexto`` do manifesto.

    Enviar a raiz inteira levaria ao daemon o ``.venv``, ``.worktrees`` e demais diretórios (vários GB no Pi); o
    cliente Python não aplica o ``.dockerignore`` como o ``docker build``.
    """
    if not spec.contexto:
        yield project_root
        return
    with tempfile.TemporaryDirectory(prefix=f"ctx-{spec.nome}-") as tmp:
        for rel in spec.contexto:
            source = (project_root / rel).resolve()
            if not source.exists() or project_root.resolve() not in (source, *source.parents):
                raise PlatformImageError(f"Contexto de build '{rel}' da imagem '{spec.nome}' não existe no projeto.")
            target = Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, target)
        yield Path(tmp)


def write_platform_file(result: EnsureResult, path: Path = PLATFORM_FILE) -> None:
    """Grava ``store/platform.json`` de forma atômica (sem tocar no ``.env``)."""
    payload = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "plataforma": result.plataforma.to_dict(),
        "manifesto_versao": MANIFEST_VERSION,
        "imagens": result.imagens,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".platform-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise PlatformImageError(f"Não foi possível gravar '{path}': {exc}") from exc


# -- cliente e início de sessão -------------------------------------------------------------------


def docker_client(timeout: int = 10) -> Any:
    """Cliente do daemon de containers.

    Raises:
        PlatformImageError: Daemon inacessível.
    """
    try:
        import docker

        client = docker.from_env(timeout=timeout)
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        raise PlatformImageError(f"Daemon de containers inacessível ({type(exc).__name__}): {exc}") from exc


def current_platform(client: Any) -> PlatformInfo:
    """Plataforma atual, com a arquitetura do daemon consultada em ``client.info()``."""
    return detect_current(client.info())


_warned_not_validated = False


def check_sandbox_image(client: Any | None = None, manifest_path: Path | str = MANIFEST_PATH) -> None:
    """Confere, no início da sessão, que a imagem do sandbox existe e tem a arquitetura do daemon (design §4).

    Daemon inacessível não bloqueia aqui (``ensure_infrastructure`` já avisa; a skill de código falha de forma
    explícita ao ser usada). Plataforma fora de ``validada_em`` gera um único ``WARNING`` por processo.

    Raises:
        PlatformImageError: Imagem ausente ou com arquitetura diferente da do daemon (traz o comando de ``ensure``).
    """
    global _warned_not_validated
    try:
        client = client or docker_client(timeout=5)
    except PlatformImageError:
        return
    spec = load_manifest(manifest_path)["sandbox"]
    info = current_platform(client)
    reference = spec.reference
    image = _local_image(client, reference)
    if image is None:
        raise PlatformImageError(
            f"A imagem do sandbox '{reference}' não existe neste daemon ({info.id}). Obtenha-a com: {ENSURE_COMMAND}"
        )
    arch = _image_arch(image)
    if arch != info.daemon_arch:
        raise PlatformImageError(
            f"A imagem do sandbox '{reference}' tem arquitetura {arch}, mas o daemon é {info.daemon_arch}. "
            f"Reconstrua-a com: {ENSURE_COMMAND}"
        )
    if info.id not in spec.validada_em and not _warned_not_validated:
        _warned_not_validated = True
        logger.warning(
            "Plataforma ainda não validada para o sandbox",
            extra={"plataforma": info.id, "validada_em": list(spec.validada_em)},
        )


def reset_warning_state() -> None:
    """Reinicia o aviso único por sessão (início de sessão e testes)."""
    global _warned_not_validated
    _warned_not_validated = False
