"""Carga, recorte e leitura do regimento da pesquisa (v18.7-agent-system-prompts, ADR 022 §4).

O regimento é o texto comum a todos os agentes: ``regimento.md`` (prosa em seções, cada uma com a linha de
metadados ``<!-- secao: <id>; aplica: <comum | objetivo:<tipo> | modo:<modo>> -->``) e ``regimento.yaml`` (a parte
estruturada, da qual saem as listas de ids). Este módulo é determinístico e não chama LLM.

O recorte de uma sessão tem as seções comuns, a do tipo de objetivo e a do modo, mais as listas geradas da parte
estruturada; o hash do arquivo e o de cada recorte ficam registrados na sessão.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src import config

REGIMENTO_DIR = Path(__file__).resolve().parent
_MD = "regimento.md"
_YAML = "regimento.yaml"
_META_RE = re.compile(r"^<!--\s*secao:\s*([a-z][a-z0-9_]*)\s*;\s*aplica:\s*([a-z]+(?::[a-z]+)?)\s*-->\s*$")
_TITLE_RE = re.compile(r"^## (.+?)\s*$")
_REQUIRED_LISTS = (
    "papeis_experimento", "ordem_decisao_papel", "tipos_objetivo", "motivos_parada", "motivos_retirada",
    "regras_integridade", "regras_seguranca", "modos",
)
SEM_OBJETIVO = "sem objetivo"


class RegimentoError(ValueError):
    """Regimento inválido (metadados, estrutura ou tamanho)."""


@dataclass(frozen=True)
class Secao:
    """Seção em prosa: ``aplica`` é ``comum``, ``objetivo:<tipo>`` ou ``modo:<modo>``."""

    id: str
    titulo: str
    aplica: str
    texto: str


@dataclass(frozen=True)
class Regimento:
    """Regimento carregado: seções em prosa, parte estruturada e hash dos arquivos."""

    versao: int
    sha256: str
    secoes: tuple[Secao, ...]
    estrutura: dict[str, Any]


@dataclass(frozen=True)
class Recorte:
    """Texto injetado no ``system`` de uma combinação de tipo de objetivo e modo."""

    texto: str
    sha256: str
    tipo_objetivo: str
    modo: str


def _rotulo_objetivo(tipo: str | None) -> str:
    return f"objetivo {tipo}" if tipo else SEM_OBJETIVO


def _hash(*partes: bytes) -> str:
    return hashlib.sha256(b"\0".join(partes)).hexdigest()


def _parse_secoes(md: str) -> tuple[Secao, ...]:
    lines = md.splitlines()
    starts = [i for i, line in enumerate(lines) if _TITLE_RE.match(line)]
    if not starts:
        raise RegimentoError("regimento.md sem nenhuma seção (título de nível 2)")
    secoes: list[Secao] = []
    for pos, start in enumerate(starts):
        titulo = _TITLE_RE.match(lines[start]).group(1)  # type: ignore[union-attr]
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        meta = _META_RE.match(lines[start + 1]) if start + 1 < end else None
        if meta is None:
            raise RegimentoError(f"seção '{titulo}' sem a linha de metadados '<!-- secao: <id>; aplica: <...> -->'")
        corpo = "\n".join(lines[start + 2:end]).strip()
        if not corpo:
            raise RegimentoError(f"seção '{titulo}' sem texto")
        secoes.append(Secao(id=meta.group(1), titulo=titulo, aplica=meta.group(2), texto=corpo))
    ids = [s.id for s in secoes]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise RegimentoError(f"ids de seção repetidos: {', '.join(repetidos)}")
    return tuple(secoes)


def _ids(estrutura: dict[str, Any], chave: str) -> list[str]:
    return [item["id"] for item in estrutura[chave]]


def _validar(secoes: tuple[Secao, ...], estrutura: dict[str, Any]) -> None:
    if not isinstance(estrutura, dict):
        raise RegimentoError("regimento.yaml deve ser um mapa")
    if not isinstance(estrutura.get("versao"), int):
        raise RegimentoError("regimento.yaml sem 'versao' inteira")
    for chave in _REQUIRED_LISTS:
        valor = estrutura.get(chave)
        if not isinstance(valor, list) or not valor:
            raise RegimentoError(f"regimento.yaml sem a lista '{chave}'")
    for chave in ("papeis_experimento", "tipos_objetivo", "motivos_parada", "motivos_retirada", "regras_integridade",
                  "regras_seguranca", "modos"):
        for item in estrutura[chave]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise RegimentoError(f"item sem 'id' em '{chave}'")
        ids = _ids(estrutura, chave)
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        if repetidos:
            raise RegimentoError(f"ids repetidos em '{chave}': {', '.join(repetidos)}")
    tipos, modos = set(_ids(estrutura, "tipos_objetivo")), set(_ids(estrutura, "modos"))
    for secao in secoes:
        if secao.aplica == "comum":
            continue
        kind, _, valor = secao.aplica.partition(":")
        if kind == "objetivo" and valor in tipos or kind == "modo" and valor in modos:
            continue
        raise RegimentoError(f"seção '{secao.titulo}' com 'aplica' inválido: {secao.aplica}")
    aplicadas = {s.aplica for s in secoes}
    for tipo in sorted(tipos):
        if f"objetivo:{tipo}" not in aplicadas:
            raise RegimentoError(f"tipo de objetivo '{tipo}' sem seção em regimento.md")
    for modo in sorted(modos):
        if f"modo:{modo}" not in aplicadas:
            raise RegimentoError(f"modo '{modo}' sem seção em regimento.md")


def carregar_regimento(base: Path = REGIMENTO_DIR, max_chars: int | None = None) -> Regimento:
    """Lê e valida o regimento de ``base``.

    Args:
        base: Diretório com ``regimento.md`` e ``regimento.yaml``.
        max_chars: Teto do recorte de cada combinação (padrão ``REGIMENTO_EXCERPT_MAX_CHARS``).

    Raises:
        RegimentoError: Metadados, estrutura ou tamanho inválidos; a mensagem cita a seção ou a combinação.
    """
    md_bytes = (base / _MD).read_bytes()
    yaml_bytes = (base / _YAML).read_bytes()
    secoes = _parse_secoes(md_bytes.decode("utf-8"))
    try:
        estrutura = yaml.safe_load(yaml_bytes)
    except yaml.YAMLError as exc:
        raise RegimentoError(f"regimento.yaml inválido: {exc}") from exc
    _validar(secoes, estrutura)
    reg = Regimento(versao=estrutura["versao"], sha256=_hash(md_bytes, yaml_bytes), secoes=secoes, estrutura=estrutura)
    teto = config.REGIMENTO_EXCERPT_MAX_CHARS if max_chars is None else max_chars
    for tipo in [None, *_ids(estrutura, "tipos_objetivo")]:
        for modo in _ids(estrutura, "modos"):
            tamanho = len(recorte(reg, tipo, modo).texto)
            if tamanho > teto:
                raise RegimentoError(
                    f"recorte de {_rotulo_objetivo(tipo)}; modo {modo} tem {tamanho} caracteres, acima do "
                    f"teto REGIMENTO_EXCERPT_MAX_CHARS={teto}"
                )
    return reg


# --- Listas geradas da parte estruturada -----------------------------------------------------------------------------


def _lista(titulo: str, linhas: list[str]) -> str:
    return f"## {titulo}\n" + "\n".join(linhas)


def _papeis(est: dict[str, Any]) -> str:
    papeis = [f"- `{p['id']}`: {p['descricao']}" for p in est["papeis_experimento"]]
    ordem = [f"{i}. {r['texto']}" for i, r in enumerate(est["ordem_decisao_papel"], 1)]
    return _lista("Papéis de experimento", papeis) + "\n\n" + _lista("Como o papel é decidido, nesta ordem", ordem)


def _objetivo(est: dict[str, Any], tipo: str | None) -> str:
    tipos = [t for t in est["tipos_objetivo"] if tipo is None or t["id"] == tipo]
    linhas: list[str] = []
    for t in tipos:
        linhas.append(f"- `{t['id']}` atingido quando {t['atingido']}.")
        linhas.append(f"  Avanço: {t['avanco']}.")
        linhas.append(f"  Saturação: {t['saturacao']}.")
        for d in t.get("desfechos", []):
            linhas.append(f"  Desfecho `{d['id']}`: {d['texto']}.")
    return _lista("Critérios do tipo de objetivo", linhas)


def _paradas(est: dict[str, Any], modo: str | None) -> str:
    itens = [p for p in est["motivos_parada"] if modo is None or modo in p.get("modos", [modo])]
    paradas = [f"- `{p['id']}`: {p['texto']}" for p in itens]
    retiradas = [f"- `{r['id']}`: {r['texto']}" for r in est["motivos_retirada"]]
    return _lista("Motivos de parada", paradas) + "\n\n" + _lista("Motivos de retirada de subtarefa", retiradas)


def _integridade(est: dict[str, Any]) -> str:
    return _lista("Regras de integridade", [f"- `{r['id']}`: {r['texto']}" for r in est["regras_integridade"]])


def _reservadas(est: dict[str, Any]) -> str:
    return _lista("Decisões reservadas ao pesquisador", [f"- `{d}`" for d in est["decisoes_reservadas"]])


def regras_seguranca(est: dict[str, Any], destino: str) -> list[dict[str, Any]]:
    """Regras de segurança cujo ``destino`` inclui o texto pedido (``regimento`` ou o papel)."""
    return [r for r in est["regras_seguranca"] if destino in r["destino"]]


def _seguranca(est: dict[str, Any]) -> str:
    return _lista("Regras de segurança", [f"- {r['texto']}" for r in regras_seguranca(est, "regimento")])


_TabelaFn = Callable[[dict[str, Any], str | None, str | None], str]
_TABELAS: dict[str, _TabelaFn] = {
    "papeis": lambda est, tipo, modo: _papeis(est),
    "objetivo": lambda est, tipo, modo: _objetivo(est, tipo),
    "paradas": lambda est, tipo, modo: _paradas(est, modo),
    "integridade": lambda est, tipo, modo: _integridade(est),
    "reservadas": lambda est, tipo, modo: _reservadas(est),
    "seguranca": lambda est, tipo, modo: _seguranca(est),
}
# Tabelas que cada seção cita (usadas pelo recorte e por ``secao``).
_TABELAS_DA_SECAO: dict[str, tuple[str, ...]] = {
    "exploracao": ("papeis",),
    "paradas": ("objetivo", "paradas"),
    "integridade": ("integridade", "reservadas", "seguranca"),
}


def _secao_texto(secao: Secao) -> str:
    return f"## {secao.titulo}\n{secao.texto}"


def recorte(reg: Regimento, tipo_objetivo: str | None, modo: str, adendo: Any = None) -> Recorte:
    """Recorte do regimento para um tipo de objetivo (``None`` sem projeto ou sem ``Problema``) e um modo.

    As seções comuns, a do tipo e a do modo, na ordem do arquivo; cada seção comum vem seguida das listas geradas
    que ela cita, filtradas pelo tipo e pelo modo. O adendo de projeto aprovado (``Adendo``), quando houver, vem no
    fim, sob o título "Regras adicionais do projeto".
    """
    if modo not in _ids(reg.estrutura, "modos"):
        raise RegimentoError(f"modo desconhecido: {modo!r}")
    if tipo_objetivo is not None and tipo_objetivo not in _ids(reg.estrutura, "tipos_objetivo"):
        raise RegimentoError(f"tipo de objetivo desconhecido: {tipo_objetivo!r}")
    blocos: list[str] = []
    for secao in reg.secoes:
        if secao.aplica not in ("comum", f"modo:{modo}", f"objetivo:{tipo_objetivo}"):
            continue
        blocos.append(_secao_texto(secao))
        for nome in _TABELAS_DA_SECAO.get(secao.id, ()):
            if nome == "objetivo" and tipo_objetivo is None:
                continue
            blocos.append(_TABELAS[nome](reg.estrutura, tipo_objetivo, modo))
    if adendo is not None:
        blocos.append(adendo.renderizar())
    texto = "\n\n".join(blocos)
    return Recorte(texto=texto, sha256=_hash(texto.encode("utf-8")), tipo_objetivo=tipo_objetivo or "", modo=modo)


def secao(reg: Regimento, secao_id: str) -> str:
    """Texto da seção e das listas geradas que ela cita; sem ``secao_id`` válido, a lista de ids e títulos."""
    por_id = {s.id: s for s in reg.secoes}
    alvo = por_id.get(secao_id)
    if alvo is None:
        linhas = [f"- {s.id}: {s.titulo}" for s in reg.secoes]
        cabecalho = "Seções do regimento (passe um id):" if not secao_id else (
            "Seção desconhecida. Ids válidos (passe um deles):"
        )
        return cabecalho + "\n" + "\n".join(linhas)
    tipo = alvo.aplica.partition(":")[2] if alvo.aplica.startswith("objetivo:") else None
    blocos = [_secao_texto(alvo)]
    for nome in _TABELAS_DA_SECAO.get(alvo.id, ()):
        if nome == "objetivo":
            continue
        blocos.append(_TABELAS[nome](reg.estrutura, tipo, None))
    if tipo is not None:
        blocos.append(_objetivo(reg.estrutura, tipo))
    return "\n\n".join(blocos)


def cabecalho(reg: Regimento, rec: Recorte) -> str:
    """Cabeçalho do recorte no ``system`` (ADR 022 §4.3)."""
    return f"REGIMENTO DA PESQUISA (versão {reg.versao}; {_rotulo_objetivo(rec.tipo_objetivo)}; modo {rec.modo})"
