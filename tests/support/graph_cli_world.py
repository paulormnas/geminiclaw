"""Mundo de teste da CLI do grafo (v17-graph-cli): grafo em memória, provedor roteirizado e execução da CLI.

Nada aqui usa rede, banco ou provedor pago: o LLM é um dublê roteirizado que registra o que recebeu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.cli_graph import handle_graph_command
from src.human_gate import HumanGate
from src.knowledge.graph_store import InMemoryGraphStore
from src.llm.base import LLMProvider, LLMResponse, ToolCall
from tests.support.curator_graph import ORQ, PESQUISADOR, CuratorGraph

PID = "11111111-1111-4111-8111-111111111111"
OTHER_PID = "22222222-2222-4222-8222-222222222222"
ESC = "\x1b"


class Scripted(LLMProvider):
    """Provedor simulado: devolve as respostas na ordem e registra tudo o que recebeu."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        self.calls.append({"messages": list(messages), "tools": tools, "system": system})
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(text="fim", usage={"prompt_tokens": 5, "completion_tokens": 5})

    async def generate_stream(self, messages, system=None):  # pragma: no cover - não usado
        yield ""

    async def health_check(self) -> bool:  # pragma: no cover
        return True

    @property
    def model_name(self) -> str:
        return "scripted"


def propose(ops: list[dict[str, Any]], explicacao: str = "explicação") -> list[LLMResponse]:
    """Roteiro: uma chamada de ``propose_changes`` e o resumo final."""
    call = ToolCall(id="c1", name="propose_changes", arguments={"ops": ops, "explicacao": explicacao})
    return [
        LLMResponse(text=None, tool_calls=[call], finish_reason="tool_calls",
                    usage={"prompt_tokens": 10, "completion_tokens": 5}),
        LLMResponse(text="proposta enviada", usage={"prompt_tokens": 5, "completion_tokens": 5}),
    ]


@dataclass
class World:
    """Grafo do projeto ``PID`` (mais um projeto privado ``OTHER_PID``) e atalhos para rodar a CLI."""

    store: InMemoryGraphStore = field(default_factory=InMemoryGraphStore)
    ids: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        store, ids = self.store, self.ids
        graph = CuratorGraph(store, projeto_id=PID).setup_project()
        ids["projeto"], ids["problema"], ids["metrica"] = graph.projeto or "", graph.problema or "", graph.metrica or ""
        hip = graph.hipotese("Árvores de decisão melhoram o R2")
        abordagem = graph.abordagem("árvores de decisão")
        graph.tentativa(hip, abordagem, valor=0.80)
        graph.tentativa(hip, abordagem, valor=0.82, no="B", sessao="s2")
        store.update_node(hip, {"veredito": 0.36, "suporte": 0.8, "certeza": 0.4, "n_tentativas": 2}, actor=ORQ)
        ids["hipotese"], ids["abordagem"] = hip, abordagem
        ids["descoberta"] = store.create_node(
            "Descoberta",
            graph.base(tipo="condicional", enunciado="Árvores só funcionam em dados tabulares",
                       condicoes="tabular", n_evidencias=1, status="ativa"),
            actor=PESQUISADOR,
        )
        ids["descoberta2"] = store.create_node(
            "Descoberta",
            graph.base(tipo="licao_de_caminho", enunciado="Normalizar antes de treinar", n_evidencias=1,
                       status="contestada"),
            actor=PESQUISADOR,
        )
        store.create_edge(ids["descoberta"], "SOBRE", abordagem, {}, actor=PESQUISADOR)
        ids["oportunidade"] = store.create_node(
            "Oportunidade",
            graph.base(enunciado="Testar random forest", justificativa="J", status="documentada"),
            actor=ORQ,
        )
        # Projeto privado de outro pesquisador (nunca deve aparecer nem ser alterado).
        other = CuratorGraph(store, projeto_id=OTHER_PID, sessao_id="o1")
        ids["outro_projeto_no"] = store.create_node(
            "Abordagem", other.base(nome="segredo do outro projeto", tipo="algoritmo", descricao="D"), actor=ORQ
        )
        ids["compartilhado"] = store.create_node(
            "Dominio",
            {"projeto_id": "__global__", "sessao_id": "g", "termo": "aprendizado de máquina", "nivel": "area",
             "status": "aprovado", "visibilidade": "compartilhavel"},
            actor=ORQ,
        )

    def run(
        self,
        argv: list[str],
        *,
        inputs: list[str] | None = None,
        interactive: bool = True,
        provider: Scripted | None = None,
        gate: HumanGate | None = None,
        with_project: bool = True,
        config_dir: Any = None,
    ) -> tuple[int, str, list[str]]:
        """Executa ``geminiclaw graph ...``; devolve ``(código, saída, prompts do input)``."""
        lines: list[str] = []
        prompts: list[str] = []
        queue = list(inputs or [])

        def input_fn(prompt: str) -> str:
            prompts.append(prompt)
            if not queue:
                raise EOFError
            return queue.pop(0)

        args = list(argv)
        if with_project and "--project" not in args and args and args[0] in ("show", "node", "edit"):
            args += ["--project", PID]
        code = handle_graph_command(
            args, self.store, output_fn=lines.append, input_fn=input_fn, interactive=interactive,
            provider_factory=(lambda: provider) if provider is not None else None, gate=gate,
            config_dir=config_dir,
        )
        return code, "\n".join(lines), prompts
