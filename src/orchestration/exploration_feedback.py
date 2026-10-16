"""Retorno ao Researcher sobre ligações e retiradas do ciclo (v18.7-hypothesis-linking, design §8; ADR 021 §7).

O que o sistema decidiu a partir do plano (papel, preparação ligada, hipótese do sistema, referência, retirada) volta ao
Researcher no replanejamento seguinte, como **dado delimitado** (``wrap_data``): contém nomes de subtarefa e ``id`` de
hipótese escritos pelo LLM ou pelo grafo. Cada item leva ``subtarefa``, ``papel``, ``acao``, ``motivo``, ``hipoteses`` e
uma frase curta (``texto``). Retiradas vêm primeiro; o total é limitado por ``LINKAGE_FEEDBACK_MAX_ITEMS``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src import config

ACAO_RETIRADA = "retirada"
ACAO_PREPARACAO = "preparacao_ligada"
ACAO_HIPOTESE_SISTEMA = "hipotese_do_sistema"
ACAO_REFERENCIA = "referencia_registrada"
ACAO_BASELINE = "baseline_provavel"
ACAO_REMOVIDA = "removida_pelo_replanejamento"
ACAO_FORMATO = "formato"

_BASELINE_HINTS = ("baseline", "dummy", "majoritari")
_MAX_NAME = 128


def looks_like_baseline(task_name: str) -> bool:
    """O nome da subtarefa sugere um baseline (``baseline``, ``dummy``, ``majoritari``)."""
    name = (task_name or "").lower()
    return any(hint in name for hint in _BASELINE_HINTS)


@dataclass
class LinkageFeedback:
    """Itens do retorno ao Researcher, acumulados por ``prepare_cycle``."""

    withdrawals: list[dict[str, Any]] = field(default_factory=list)
    others: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _item(task: str, papel: str, acao: str, motivo: str, hipoteses: list[str], texto: str) -> dict[str, Any]:
        return {
            "subtarefa": task[:_MAX_NAME], "papel": papel, "acao": acao, "motivo": motivo,
            "hipoteses": list(hipoteses), "texto": texto,
        }

    def withdrawn(self, task: str, papel: str, motivo: str) -> None:
        self.withdrawals.append(
            self._item(task, papel, ACAO_RETIRADA, motivo, [], f"`{task[:_MAX_NAME]}`: não executada (`{motivo}`).")
        )

    def prepares(self, task: str, hypothesis_ids: list[str]) -> None:
        if hypothesis_ids:
            text = f"`{task[:_MAX_NAME]}`: registrada como preparação de {', '.join(hypothesis_ids)}."
        else:
            text = f"`{task[:_MAX_NAME]}`: registrada como preparação do Problema."
        self.others.append(self._item(task, "preparacao", ACAO_PREPARACAO, "", hypothesis_ids, text))

    def system_hypothesis(self, task: str, hypothesis_id: str, *, reused: bool, reopened: bool) -> None:
        verb = "reaberta" if reopened else ("reutilizada" if reused else "criada")
        text = (
            f"`{task[:_MAX_NAME]}`: teste sem hipótese declarada; hipótese do sistema `{hypothesis_id}` {verb}. "
            "Declare `hypothesis_ref` para usar a sua."
        )
        self.others.append(self._item(task, "teste", ACAO_HIPOTESE_SISTEMA, verb, [hypothesis_id], text))

    def reference(self, task: str) -> None:
        text = f"`{task[:_MAX_NAME]}`: registrada como referência do Problema."
        self.others.append(self._item(task, "referencia", ACAO_REFERENCIA, "", [], text))

    def probable_baseline(self, task: str, hypothesis_id: str) -> None:
        text = (
            f"`{task[:_MAX_NAME]}`: executada como teste da hipótese do sistema `{hypothesis_id}`; "
            "se é um baseline, declare `papel: referencia`."
        )
        self.others.append(self._item(task, "teste", ACAO_BASELINE, "", [hypothesis_id], text))

    def removed(self, task: str) -> None:
        text = f"`{task[:_MAX_NAME]}`: removida da fila pelo plano novo."
        self.others.append(self._item(task, "", ACAO_REMOVIDA, "removida_pelo_replanejamento", [], text))

    def format_issue(self, task: str, code: str, detail: str = "") -> None:
        texts = {
            "papel_invalido": "`papel` inválido ignorado.",
            "abordagem_nao_declarada": "abordagem não declarada.",
            "sem_metrica": "sem métrica principal resolvida; seguiu como preparação do Problema.",
        }
        invalid_ref = f"`hypothesis_ref` inválido (`{detail}`); seguiu como teste da hipótese do sistema."
        text = f"`{task[:_MAX_NAME]}`: " + (texts[code] if code in texts else invalid_ref)
        self.others.append(self._item(task, "", ACAO_FORMATO, code if code in texts else detail, [], text))

    def items(self) -> list[dict[str, Any]]:
        """Retiradas primeiro, limitado a ``LINKAGE_FEEDBACK_MAX_ITEMS``."""
        return [*self.withdrawals, *self.others][: int(config.LINKAGE_FEEDBACK_MAX_ITEMS)]
