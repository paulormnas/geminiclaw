"""Pipeline do relatório final (v18.5-numeric-references, design §7.4).

``relatorio_final.fonte.md`` (texto canônico, com referências) → resolve → [extensões] → renderiza → verifica números →
seções do orquestrador → ``relatorio_final.md`` (gravação atômica) + ``proveniencia_numerica.json``.

Outras mudanças acrescentam etapas (``register_stage``, ex.: verificação de afirmações) e seções
(``register_section``, cujo nome é o delimitador X2 do verificador) sem alterar este módulo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.logger import get_logger
from src.numeric_refs import provenance_file
from src.numeric_refs.render import RenderResult, render_text
from src.numeric_refs.resolver import ReferenceResolver
from src.numeric_refs.verifier import DEFAULT_SECTION_NAMES, UnverifiedNumber, verify_numbers

logger = get_logger(__name__)

SOURCE_FILE = "relatorio_final.fonte.md"
REPORT_FILE = "relatorio_final.md"
NUMERIC_SECTION = "numeric-provenance"
NUMERIC_SECTION_TITLE = "Origem dos números"


@dataclass
class ReportState:
    """Estado que as etapas leem e transformam."""

    session_id: str
    session_dir: Path
    source_text: str
    text: str
    resolver: ReferenceResolver
    counts: dict[str, int] = field(default_factory=dict)  # contagens do orquestrador (exclusão X8)
    render: RenderResult | None = None
    nao_verificados: list[UnverifiedNumber] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)  # blocos já delimitados, em ordem
    extras: dict[str, Any] = field(default_factory=dict)


Stage = Callable[[ReportState], ReportState]
Section = Callable[[ReportState], str]


@dataclass
class _Section:
    name: str
    title: str
    build: Section


class ReportPipeline:
    """Etapas e seções do relatório, com pontos de extensão."""

    def __init__(self) -> None:
        self._stages: list[tuple[str, Stage]] = []
        self._sections: list[_Section] = []
        self.section_names: list[str] = list(DEFAULT_SECTION_NAMES)

    def register_stage(self, name: str, fn: Stage, after: str | None = None) -> None:
        """Insere a etapa ``name`` depois de ``after`` (no fim, se omitido).

        Raises:
            ValueError: ``name`` repetido ou ``after`` desconhecido.
        """
        if any(n == name for n, _ in self._stages):
            raise ValueError(f"etapa já registrada: {name}")
        if after is None:
            self._stages.append((name, fn))
            return
        for index, (existing, _) in enumerate(self._stages):
            if existing == after:
                self._stages.insert(index + 1, (name, fn))
                return
        raise ValueError(f"etapa '{after}' desconhecida")

    def register_section(self, name: str, fn: Section, title: str | None = None) -> None:
        """Registra uma seção do orquestrador (``name`` é o delimitador ``<!-- name:begin -->``)."""
        if any(s.name == name for s in self._sections):
            raise ValueError(f"seção já registrada: {name}")
        self._sections.append(_Section(name, title or name, fn))
        if name not in self.section_names:
            self.section_names.append(name)

    @property
    def stage_names(self) -> list[str]:
        return [n for n, _ in self._stages]

    def run(self, state: ReportState) -> ReportState:
        for name, fn in self._stages:
            try:
                state = fn(state)
            except Exception:
                logger.error("Etapa do relatório falhou", extra={"etapa": name})
                raise
        for section in self._sections:
            body = section.build(state).strip()
            if body:
                state.sections.append(delimit_section(section.name, section.title, body))
        return state

    def build(self, state: ReportState) -> Path:
        """Executa o pipeline e grava ``relatorio_final.md`` e ``proveniencia_numerica.json``."""
        state = self.run(state)
        text = state.text.rstrip() + "\n\n" + "\n\n".join(state.sections) if state.sections else state.text
        target = state.session_dir / REPORT_FILE
        _write_atomic(target, text.rstrip() + "\n")
        render = state.render
        counts = dict(render.contagens) if render else {}
        payload = provenance_file.build_payload(
            state.session_id,
            render.codigos if render else [],
            [
                {"local": u.local, "texto": u.texto, "motivo": u.motivo}
                for u in state.nao_verificados
            ]
            + [
                {"local": "relatorio", "texto": n["texto"], "motivo": n["motivo"]}
                for n in (render.nao_resolvidos if render else [])
            ],
            provenance_file.read_literal_findings(state.session_dir),
            counts,
        )
        provenance_file.write_payload(state.session_dir, payload)
        return target


def delimit_section(name: str, title: str, body: str) -> str:
    return f"<!-- {name}:begin -->\n## {title}\n{body}\n<!-- {name}:end -->"


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


# --- etapas e seções padrão ---------------------------------------------------------------------------------------

def resolve_and_render(state: ReportState) -> ReportState:
    """Resolve e renderiza todas as referências do texto canônico."""
    state.render = render_text(state.text, state.resolver)
    state.text = state.render.texto
    return state


def verify_unreferenced_numbers(pipeline: ReportPipeline) -> Stage:
    def stage(state: ReportState) -> ReportState:
        outcome = verify_numbers(
            state.text,
            protected_spans=state.render.spans if state.render else (),
            section_names=pipeline.section_names,
            counts=state.counts,
        )
        state.text = outcome.texto
        state.nao_verificados = outcome.nao_verificados
        return state

    return stage


def appendix_section(state: ReportState) -> str:
    """Apêndice "Origem dos números": códigos, números não verificados e métricas literais."""
    render = state.render
    lines: list[str] = []
    if render and render.codigos:
        lines += ["| Código | Valor exato | Unidade | Origem | Detalhe |", "|---|---|---|---|---|"]
        for code in render.codigos:
            lines.append(
                f"| <a id=\"origem-{code.codigo}\"></a>{code.codigo} | {_exact(code.valor_exato)} | "
                f"{code.unidade or '—'} | {_origin(code.tipo)} | {_detail(code)} |"
            )
    else:
        lines.append("Nenhuma referência numérica resolvida neste relatório.")
    unverified = [
        (u.local, u.texto, u.motivo) for u in state.nao_verificados
    ] + [("relatorio", n["texto"], n["motivo"]) for n in (render.nao_resolvidos if render else [])]
    if unverified:
        lines += ["", "**Números não verificados**", "", "| Local | Trecho | Motivo |", "|---|---|---|"]
        lines += [f"| {_cell(loc)} | `{_cell(txt)}` | {_cell(motivo)} |" for loc, txt, motivo in unverified]
    literals = provenance_file.read_literal_findings(state.session_dir)
    if literals:
        lines += ["", "**Métricas gravadas como literais no código**", "", "| exec_id | Métrica | Linha | Padrão |",
                  "|---|---|---|---|"]
        lines += [
            f"| {i.get('exec_id')} | {_cell(i.get('metrica'))} | {i.get('linha')} | {i.get('padrao')} |"
            for i in literals
        ]
    return "\n".join(lines)


def _cell(value: Any) -> str:
    return str(value if value not in (None, "") else "—").replace("\n", " ").replace("|", "\\|")


def _exact(value: float | None) -> str:
    return "—" if value is None else repr(value)


def _origin(kind: str) -> str:
    return {"res": "execução registrada", "calc": "cálculo determinístico", "src": "fonte citada"}.get(kind, kind)


def _detail(code: Any) -> str:
    d = code.detalhe
    if code.tipo == "res":
        sha = str(d.get("sha256") or "")[:12]
        return _cell(f"{d.get('exec_id')} · {d.get('subtarefa')} · {d.get('arquivo')} · sha256 {sha}")
    if code.tipo == "calc":
        ops = "; ".join(f"{o.get('ident')}={o.get('metrica') or o.get('trecho')}" for o in d.get("operandos", []))
        consts = d.get("constantes") or []
        return _cell(f"{d.get('expressao')} [{ops}]" + (f" · constantes {consts}" if consts else ""))
    when = f" · {d['obtido_em']}" if d.get("obtido_em") else ""
    return _cell(f"{d.get('titulo') or d.get('fonte')} · “{d.get('trecho')}”{when}")


def build_default_pipeline() -> ReportPipeline:
    """Pipeline padrão: ``resolve`` (renderiza as referências) → ``verify`` (números sem origem) + apêndice."""
    pipeline = ReportPipeline()
    pipeline.register_stage("resolve", resolve_and_render)
    pipeline.register_stage("verify", verify_unreferenced_numbers(pipeline), after="resolve")
    pipeline.register_section(NUMERIC_SECTION, appendix_section, NUMERIC_SECTION_TITLE)
    return pipeline
