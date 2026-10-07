"""Construtor de grafos de teste para o Curator e o ``KnowledgeService`` (v17-curator-agent).

Monta, num ``GraphStore`` já criado, o que a ingestão estrutural gravaria: ``Projeto``, ``Problema`` confirmado com
``criterio_sucesso``, ``Metrica`` aprovada, ``Hipotese``, ``Abordagem``, ``Experimento`` (``TESTA``, ``APLICOU``,
``PRODUZIU``) e ``Resultado`` (``MEDE``). Nada aqui usa rede, LLM ou banco.
"""

from __future__ import annotations

from typing import Any

from src.knowledge.graph_store import GraphStore
from src.knowledge.provenance import Actor

ORQ = Actor(kind="orquestrador")
PESQUISADOR = Actor(kind="pesquisador")
RESEARCHER = Actor(kind="agente", role="researcher")


class CuratorGraph:
    """Atalhos para montar nós e arestas do projeto de teste."""

    def __init__(self, store: GraphStore, projeto_id: str = "proj1", sessao_id: str = "s1") -> None:
        self.store = store
        self.projeto_id = projeto_id
        self.sessao_id = sessao_id
        self.projeto: str | None = None
        self.metrica: str | None = None
        self.problema: str | None = None
        self._n = 0
        self._sessoes: dict[tuple[str, str], str] = {}

    def base(self, **extra: Any) -> dict[str, Any]:
        return {"projeto_id": self.projeto_id, "sessao_id": self.sessao_id, **extra}

    def setup_project(
        self,
        *,
        sentido: str = "maior_melhor",
        delta_min: float = 0.05,
        metrica: str = "r2",
        problema_titulo: str = "Prever o rendimento",
    ) -> "CuratorGraph":
        """``Projeto`` + ``Metrica`` + ``Problema`` confirmado (só o pesquisador confirma)."""
        self.projeto = self.store.create_node(
            "Projeto", self.base(titulo="P", objetivo="O", status="ativo"), actor=ORQ
        )
        self.metrica = self.store.create_node(
            "Metrica",
            self.base(nome=metrica, sentido=sentido, status="aprovado"),
            actor=ORQ,
        )
        self.problema = self.store.create_node(
            "Problema",
            self.base(
                titulo=problema_titulo,
                resumo="Resumo",
                status="confirmado",
                criterio_sucesso={"metrica": metrica, "metrica_id": self.metrica, "delta_min": delta_min},
            ),
            actor=PESQUISADOR,
        )
        self.store.create_edge(self.projeto, "INVESTIGA", self.problema, {}, actor=PESQUISADOR)
        return self

    def hipotese(self, enunciado: str = "H1", *, com_problema: bool = True) -> str:
        hid = self.store.create_node(
            "Hipotese",
            self.base(
                enunciado=enunciado, justificativa="J", status="em_teste", origem="researcher",
                justificativa_criacao="plano", nos_consultados=[],
            ),
            actor=RESEARCHER,
        )
        if com_problema and self.problema:
            self.store.create_edge(hid, "SOBRE", self.problema, {}, actor=RESEARCHER)
        return hid

    def abordagem(self, nome: str = "GradientBoosting", **extra: Any) -> str:
        return self.store.create_node(
            "Abordagem",
            self.base(nome=nome, tipo="algoritmo", descricao="D", justificativa_criacao="plano", nos_consultados=[],
                      **extra),
            actor=RESEARCHER,
        )

    def tentativa(
        self,
        hipotese: str,
        abordagem: str | None,
        *,
        valor: float | None = 0.8,
        baseline: float | None = 0.7,
        validacao: str = "validado",
        no: str = "A",
        sessao: str | None = None,
        seed: int | None = 1,
        datasets: list[str] | None = None,
        config: dict[str, Any] | None = None,
        projeto_id: str | None = None,
        falha: tuple[str, str | None] | None = None,
        com_metrica: bool = True,
        visibilidade: str | None = None,
        com_sessao: bool = True,
    ) -> tuple[str, str | None]:
        """Um ``Experimento`` (e, se não for falha, o ``Resultado`` da métrica do critério).

        Returns:
            ``(experimento_id, resultado_id)``.
        """
        projeto = projeto_id or self.projeto_id
        self._n += 1
        props: dict[str, Any] = {
            "projeto_id": projeto,
            "sessao_id": sessao or self.sessao_id,
            "subtarefa_id": f"sub-{self._n}",
            "status": "falha" if falha else "sucesso",
            "caminho_artefatos": "/x",
            "no_execucao": no,
        }
        if visibilidade:
            props["visibilidade"] = visibilidade
        if seed is not None:
            props["seed"] = seed
            props["hash_params"] = "hp"
        if datasets:
            props["dataset_ids"] = datasets
        if falha:
            props["causa_falha"], sig = falha
            if sig:
                props["assinatura_falha"] = sig
        exp = self.store.create_node("Experimento", props, actor=ORQ)
        self.store.create_edge(exp, "TESTA", hipotese, {}, actor=ORQ)
        if com_sessao:
            chave = (projeto, sessao or self.sessao_id)
            if chave not in self._sessoes:
                self._sessoes[chave] = self.store.create_node(
                    "Sessao",
                    {"projeto_id": projeto, "sessao_id": chave[1], "modo": "auto", "inicio": "2026-10-06T00:00:00+00:00",
                     "no_execucao": no},
                    actor=ORQ,
                )
            self.store.create_edge(exp, "EXECUTADO_EM", self._sessoes[chave], {}, actor=ORQ)
        if abordagem is not None:
            edge: dict[str, Any] = {"config": config or {"modelo": "gb"}}
            self.store.create_edge(exp, "APLICOU", abordagem, edge, actor=ORQ)
        if falha or valor is None:
            return exp, None
        res_props: dict[str, Any] = {
            "projeto_id": projeto,
            "sessao_id": sessao or self.sessao_id,
            "nome_original": "r2",
            "valor": valor,
            "status_validacao": validacao,
            "caminho_metrics": "/m",
        }
        if visibilidade:
            res_props["visibilidade"] = visibilidade
        if baseline is not None:
            res_props["baseline"] = baseline
        res = self.store.create_node("Resultado", res_props, actor=ORQ)
        self.store.create_edge(exp, "PRODUZIU", res, {}, actor=ORQ)
        if com_metrica and self.metrica:
            self.store.create_edge(res, "MEDE", self.metrica, {}, actor=ORQ)
        return exp, res

    def adr_e1_e6(self, hipotese: str, abordagem: str) -> dict[str, str]:
        """As seis evidências do exemplo do ADR 015 §9.6; devolve ``{"E1": resultado_id, ...}``."""
        gb_x = {"modelo": "gb", "profundidade": 3}
        gb_y = {"modelo": "gb", "profundidade": 5}
        rows = [
            ("E1", dict(no="A", sessao="s1", seed=1, datasets=["ds1"], config=gb_x, valor=0.80)),
            ("E2", dict(no="A", sessao="s1", seed=2, datasets=["ds1"], config=gb_x, valor=0.78)),
            ("E3", dict(no="A", sessao="s2", seed=None, datasets=["ds1"], config=gb_x, valor=0.79)),
            ("E4", dict(no="B", sessao="s4", seed=1, datasets=["ds1"], config=gb_x, valor=0.76)),
            ("E5", dict(no="B", sessao="s5", seed=1, datasets=["ds2"], config=gb_y, valor=0.71)),
            ("E6", dict(no="A", sessao="s6", seed=1, datasets=["ds1"], config=gb_x, valor=0.82,
                        validacao="divergente_documentado")),
        ]
        out: dict[str, str] = {}
        for name, kwargs in rows:
            _, res = self.tentativa(hipotese, abordagem, baseline=0.70, **kwargs)
            assert res is not None
            out[name] = res
        return out
