"""Texto enriquecido dos trechos de documentos (v17-input-document-index, design §3).

O texto enviado ao modelo de embedding de cada trecho é um cabeçalho fixo, montado sem LLM,
seguido do texto do trecho. O cabeçalho é sempre recalculável a partir dos metadados do documento e
do projeto; o que se guarda e se devolve na busca é só o trecho (ADR 015 §6).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# Versão do modelo de cabeçalho; mudar o formato exige incrementar e reenriquecer os pontos existentes.
VERSAO_ENRIQUECIMENTO = 1

SEPARADOR = "\n---\n"
_OBJETIVO_MAX = 200
_OBJETIVO_MIN = 20


@dataclass(frozen=True)
class ProjectMeta:
    """Metadados do projeto de pesquisa usados no cabeçalho dos trechos.

    Attributes:
        projeto_id: Identificador do projeto (UUID).
        titulo: Título do projeto (vazio se o grafo estava indisponível).
        objetivo: Objetivo do projeto (vazio se o grafo estava indisponível).
        dominios: Termos canônicos dos domínios ligados ao projeto (``NO_DOMINIO``).
    """

    projeto_id: str
    titulo: str = ""
    objetivo: str = ""
    dominios: tuple[str, ...] = field(default_factory=tuple)


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def project_line(meta: ProjectMeta, objetivo_max: int = _OBJETIVO_MAX) -> str:
    """Linha ``Projeto:`` do cabeçalho (título, objetivo truncado e domínios)."""
    titulo = _one_line(meta.titulo) or meta.projeto_id
    objetivo = _one_line(meta.objetivo)[:objetivo_max]
    dominios = ", ".join(_one_line(d) for d in meta.dominios if d)
    return f"Projeto: {titulo} | objetivo: {objetivo} | domínios: {dominios}"


def hash_cabecalho_projeto(meta: ProjectMeta) -> str:
    """SHA-256 da linha ``Projeto:``; muda quando título, objetivo ou domínios do projeto mudam."""
    return hashlib.sha256(project_line(meta).encode("utf-8")).hexdigest()


def build_header(
    *,
    titulo: str,
    tipo_insumo: str,
    nome_arquivo: str,
    meta: ProjectMeta,
    secao: str | None = None,
    max_chars: int = 400,
) -> str:
    """Monta o cabeçalho fixo de um trecho, truncado em ``max_chars``.

    O truncamento encurta primeiro o objetivo do projeto (a parte mais longa); só se ainda
    exceder o limite o cabeçalho é cortado.

    Args:
        titulo: Título do documento (nome do arquivo se o extrator não informa título).
        tipo_insumo: ``artigo``, ``dataset``, ``imagem`` ou ``outro``.
        nome_arquivo: Nome do arquivo de origem.
        meta: Metadados do projeto.
        secao: Seção do trecho, quando o extrator a informa.
        max_chars: Tamanho máximo do cabeçalho.

    Returns:
        O cabeçalho, sem o separador final.
    """

    def _assemble(objetivo_max: int) -> str:
        lines = [
            f"Documento: {_one_line(titulo)} | tipo: {tipo_insumo} | arquivo: {_one_line(nome_arquivo)}",
            project_line(meta, objetivo_max),
        ]
        if secao:
            lines.append(f"Seção: {_one_line(secao)}")
        return "\n".join(lines)

    objetivo_max = _OBJETIVO_MAX
    header = _assemble(objetivo_max)
    while len(header) > max_chars and objetivo_max > _OBJETIVO_MIN:
        objetivo_max = max(_OBJETIVO_MIN, objetivo_max - max(1, len(header) - max_chars))
        header = _assemble(objetivo_max)
    return header[:max_chars]


def enriched_text(header: str, trecho: str) -> str:
    """Texto enviado ao modelo de embedding: cabeçalho, separador e trecho."""
    return f"{header}{SEPARADOR}{trecho}"
