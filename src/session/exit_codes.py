"""Códigos de saída do comando direto (v18.7-background-sessions, design §1.4).

Contrato fixo (não configurável): scripts e o benchmark dependem dele. A classe vem do ``motivo_parada`` gravado na
sessão. Esta tabela é a única fonte dos códigos; cada mudança que acrescenta um motivo acrescenta a linha aqui, e o
teste de cobertura falha se um valor de ``Sessao.motivo_parada`` ficar sem classe.
"""

from __future__ import annotations

EXIT_RESEARCH_STOP = 0  # parada de pesquisa
EXIT_ERROR = 1  # erro ou recusa; motivo desconhecido (falha fechada)
EXIT_UNLIMITED_NOT_CONFIRMED = 2  # modo sem limite não confirmado
EXIT_LIMIT = 3  # limite
EXIT_AWAITING_RESEARCHER = 4  # a sessão precisa do pesquisador
EXIT_LOW_MEMORY = 5  # memória insuficiente ao iniciar ou retomar
EXIT_SESSION_LOST = 6  # a sessão foi continuada por outra
EXIT_INTERRUPTED = 130  # interrupção pelo pesquisador

_RESEARCH_STOPS = frozenset(
    {"solucao_encontrada", "sem_caminhos_promissores", "hipoteses_nao_testadas", "saturacao"}
)
_LIMITS_EXTRA = frozenset({"versao_modelo", "planos_rejeitados"})
_AWAITING = frozenset({"aguarda_pesquisador", "suspensa_sem_pesquisador", "pausada_pesquisador"})
_INTERRUPTIONS = frozenset({"interrompida_pesquisador", "interrompida", "encerrada_pesquisador"})


def exit_code_for(motivo_parada: str | None) -> int:
    """Código de saída para o ``motivo_parada``; motivo ausente ou desconhecido dá ``1`` (falha fechada)."""
    if not motivo_parada:
        return EXIT_ERROR
    if motivo_parada in _RESEARCH_STOPS:
        return EXIT_RESEARCH_STOP
    if motivo_parada.startswith("limite_") or motivo_parada in _LIMITS_EXTRA:
        return EXIT_LIMIT
    if motivo_parada in _AWAITING:
        return EXIT_AWAITING_RESEARCHER
    if motivo_parada in _INTERRUPTIONS:
        return EXIT_INTERRUPTED
    return EXIT_ERROR
