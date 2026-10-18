"""Verificações de coerência e de redação do regimento e dos prompts (v18.7-agent-system-prompts, ADR 022 §4.5 e §5).

Funções puras sobre texto, usadas por ``tests/unit/test_regimento_coerencia.py``: o teste junta o que só o código
conhece (conjuntos de ids, prompts renderizados) e entrega a estas funções, que também rodam sobre cópias do
regimento para provar que detectam o desvio.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.agents.prompts import SECOES_DO_PROMPT
from src.agents.regimento.carga import Regimento

SIGLAS_PERMITIDAS = frozenset({
    "JSON", "CSV", "YAML", "ADR", "URL", "API", "DAG", "LLM", "PNG", "SHA",
    # marcadores de modo que o orquestrador escreve na primeira linha da chamada do Researcher
    "MODO", "PLAN", "REPLAN",
})
TITULOS_FIXOS = ("FORMATO DO PLANO",)  # título que o requisito exige literal; sai antes da checagem de maiúsculas
REGRAS_SEGURANCA_NOMINAIS = (
    "dado_observado_nao_confiavel", "decisoes_reservadas", "egresso_agregados", "confinamento_sandbox",
    "caminho_inputs",
)
_BACKTICK_ID = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")
_CAPS = re.compile(r"\b[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{4,}\b")
_ARROWS = re.compile("[←-⇿⤀-⥿]")
_DECOR = (("**", "negrito com **"), ("===", "separador ==="))
_OLD_REFS = re.compile(r"Roadmap V|Spec G")
_DASHES = re.compile(r"^\s*-{3,}\s*$")
_MIN_FRASE = 40


@dataclass(frozen=True)
class Problema:
    """Um desvio encontrado: onde (documento, linha e coluna ou seção) e o que há de errado."""

    onde: str
    detalhe: str

    def __str__(self) -> str:
        return f"{self.onde}: {self.detalhe}"


def verificar_prosa(reg: Regimento, permitidos: Iterable[str]) -> list[Problema]:
    """Todo identificador entre crases na prosa existe no YAML ou é campo/ferramenta conhecido; sem linha de tabela."""
    est = reg.estrutura
    declarados: set[str] = set(est["decisoes_reservadas"])
    for chave in ("papeis_experimento", "tipos_objetivo", "motivos_parada", "motivos_retirada", "regras_integridade",
                  "regras_seguranca", "modos"):
        declarados.update(item["id"] for item in est[chave])
    declarados.update(r["regra"] for r in est["ordem_decisao_papel"])
    declarados.update(d["id"] for t in est["tipos_objetivo"] for d in t.get("desfechos", []))
    aceitos = declarados | set(permitidos)
    problemas: list[Problema] = []
    for secao in reg.secoes:
        for achado in _BACKTICK_ID.findall(secao.texto):
            if achado not in aceitos:
                problemas.append(Problema(f"seção {secao.id}", f"`{achado}` não está declarado no regimento.yaml"))
        for numero, linha in enumerate(secao.texto.splitlines(), 1):
            if "|" in linha:
                problemas.append(Problema(f"seção {secao.id}, linha {numero}", "a prosa não tem linhas de tabela"))
    return problemas


def verificar_redacao(textos: Mapping[str, str], extras_permitidos: Iterable[str] = ()) -> list[Problema]:
    """Emoji, pictograma, negrito, separadores, setas, maiúsculas e referências antigas, com a posição de cada um."""
    siglas = SIGLAS_PERMITIDAS | set(extras_permitidos)
    problemas: list[Problema] = []
    for nome, texto in textos.items():
        limpo = texto
        for titulo in TITULOS_FIXOS:
            limpo = limpo.replace(titulo, " " * len(titulo))
        for numero, linha in enumerate(limpo.splitlines(), 1):
            onde = f"{nome}, linha {numero}"
            for coluna, char in enumerate(linha, 1):
                # A crase delimita código e identificadores em todo o texto; o grau (°) é unidade de medida.
                if unicodedata.category(char) in ("So", "Sk") and char not in "°`":
                    problemas.append(Problema(f"{onde}, coluna {coluna}", f"pictograma ou símbolo {char!r}"))
            for marca, rotulo in _DECOR:
                if marca in linha:
                    problemas.append(Problema(f"{onde}, coluna {linha.index(marca) + 1}", rotulo))
            if _DASHES.match(linha):
                problemas.append(Problema(onde, "separador decorativo ---"))
            seta = _ARROWS.search(linha)
            if seta:
                problemas.append(Problema(f"{onde}, coluna {seta.start() + 1}", f"seta Unicode {seta.group()!r}"))
            for achado in _CAPS.finditer(linha):
                if achado.group() not in siglas:
                    problemas.append(
                        Problema(f"{onde}, coluna {achado.start() + 1}", f"palavra em maiúsculas {achado.group()}")
                    )
            for antiga in _OLD_REFS.finditer(linha):
                problemas.append(
                    Problema(f"{onde}, coluna {antiga.start() + 1}", f"referência antiga {antiga.group()!r}")
                )
    return problemas


def _normalizar(frase: str) -> str:
    sem_pontuacao = re.sub(r"[^\w\s]", " ", frase.lower())
    return " ".join(sem_pontuacao.split())


def _frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.;:!?])\s+|\n+", texto)
    return [_normalizar(p) for p in partes if len(_normalizar(p)) >= _MIN_FRASE]


def verificar_duplicacao(textos: Mapping[str, str], excluir: Iterable[str] = ()) -> list[Problema]:
    """Nenhuma frase normalizada com 40 caracteres ou mais aparece duas vezes no conjunto (``excluir`` é isenta)."""
    isentas = {f for texto in excluir for f in _frases(texto)}
    vistas: dict[str, list[str]] = {}
    for nome, texto in textos.items():
        for frase in _frases(texto):
            if frase not in isentas:
                vistas.setdefault(frase, []).append(nome)
    return [
        Problema(" e ".join(sorted(set(lugares))) if len(set(lugares)) > 1 else f"{lugares[0]} (duas vezes)", frase)
        for frase, lugares in vistas.items() if len(lugares) > 1
    ]


def verificar_secoes_do_prompt(nome: str, texto: str) -> list[Problema]:
    """As seis seções padrão, cada uma com o título em linha própria e na ordem."""
    linhas = [ln.strip() for ln in texto.splitlines()]
    posicoes: list[int] = []
    problemas: list[Problema] = []
    for titulo in SECOES_DO_PROMPT:
        if titulo not in linhas:
            problemas.append(Problema(nome, f"falta a seção '{titulo}'"))
        else:
            posicoes.append(linhas.index(titulo))
    if not problemas and posicoes != sorted(posicoes):
        problemas.append(Problema(nome, "as seções estão fora de ordem"))
    return problemas


def verificar_regras_de_seguranca(
    reg: Regimento,
    recortes: Iterable[str],
    prompts_por_papel: Mapping[str, str],
    nominais: Iterable[str] = REGRAS_SEGURANCA_NOMINAIS,
) -> list[Problema]:
    """Cada regra nominal existe com destino e o texto renderizado dela aparece onde o destino manda."""
    por_id = {r["id"]: r for r in reg.estrutura["regras_seguranca"]}
    problemas: list[Problema] = []
    recortes = list(recortes)
    for ident in nominais:
        regra: Any = por_id.get(ident)
        if regra is None or not regra.get("destino"):
            problemas.append(Problema(ident, "regra de segurança ausente do regimento.yaml ou sem destino"))
            continue
        for destino in regra["destino"]:
            if destino == "regimento":
                faltando = [i for i, r in enumerate(recortes) if regra["texto"] not in r]
                if faltando:
                    problemas.append(Problema(ident, f"o texto não aparece em {len(faltando)} recorte(s) do regimento"))
            elif regra["texto"] not in prompts_por_papel.get(destino, ""):
                problemas.append(Problema(ident, f"o texto não aparece no prompt do papel {destino}"))
    return problemas
