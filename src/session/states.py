"""Estados e motivos de parada da sessão mestra (v18.7-background-sessions, design §2.2).

O ``status`` da sessão continua em ``TEXT`` livre no banco; a lista conhecida fica aqui. Os motivos de parada vão
para o ``motivo_parada`` do nó ``Sessao`` e do ``payload`` da sessão.
"""

from __future__ import annotations

STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrompida"
STATUS_SUSPENDED_LEGACY = "suspended"  # gravado só por versões antigas; continua aceito na leitura
STATUS_AWAITING_RESEARCHER = "aguarda_pesquisador"
STATUS_SUSPENDED_NO_RESEARCHER = "suspensa_sem_pesquisador"

#: Sessões que terminaram; só estas podem ser removidas pela retenção.
FINISHED_STATUSES = (STATUS_CLOSED, STATUS_SUCCESS, STATUS_FAILED)
#: Sessões com trabalho por terminar: o terminal oferece retomar, manter ou encerrar.
UNFINISHED_STATUSES = (
    STATUS_INTERRUPTED,
    STATUS_AWAITING_RESEARCHER,
    STATUS_SUSPENDED_NO_RESEARCHER,
    STATUS_SUSPENDED_LEGACY,
)

#: Sessões pausadas pelo próprio processo (o processo sai e a sessão continua retomável): o fechamento da requisição
#: as mantém como estão, em vez de fechá-las.
PAUSED_STATUSES = (STATUS_SUSPENDED_LEGACY, STATUS_AWAITING_RESEARCHER, STATUS_SUSPENDED_NO_RESEARCHER)

MOTIVO_AGUARDA_PESQUISADOR = "aguarda_pesquisador"
MOTIVO_SUSPENSA_SEM_PESQUISADOR = "suspensa_sem_pesquisador"
MOTIVO_ENCERRADA_PESQUISADOR = "encerrada_pesquisador"
