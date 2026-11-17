"""Gestão da qualidade: reclamações, desvios, não conformidades e CAPA. Regras puras."""
from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum

from app.domain.errors import InvalidTransition, ValidationFailed


class OccurrenceType(StrEnum):
    RECLAMACAO = "RECLAMACAO"            # reclamação de cliente
    DESVIO = "DESVIO"                    # desvio de processo/POP
    NAO_CONFORMIDADE = "NAO_CONFORMIDADE"  # produto/recipiente fora de especificação
    EVENTO_ADVERSO = "EVENTO_ADVERSO"    # suspeita de dano ao paciente/usuário


class Severity(StrEnum):
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class OccurrenceStatus(StrEnum):
    ABERTA = "ABERTA"
    EM_INVESTIGACAO = "EM_INVESTIGACAO"
    AGUARDANDO_EFICACIA = "AGUARDANDO_EFICACIA"
    ENCERRADA = "ENCERRADA"
    CANCELADA = "CANCELADA"


class ActionType(StrEnum):
    CONTENCAO = "CONTENCAO"
    CORRETIVA = "CORRETIVA"
    PREVENTIVA = "PREVENTIVA"


class ActionStatus(StrEnum):
    PENDENTE = "PENDENTE"
    CONCLUIDA = "CONCLUIDA"


# Prazo para concluir a investigação, por gravidade (dias corridos).
INVESTIGATION_DAYS: dict[Severity, int] = {
    Severity.CRITICA: 2, Severity.ALTA: 7, Severity.MEDIA: 15, Severity.BAIXA: 30,
}

OPEN_STATUSES = frozenset({OccurrenceStatus.ABERTA, OccurrenceStatus.EM_INVESTIGACAO,
                           OccurrenceStatus.AGUARDANDO_EFICACIA})


def investigation_due(opened: date, severity: Severity) -> date:
    return opened + timedelta(days=INVESTIGATION_DAYS[severity])


def effective_severity(kind: OccurrenceType, severity: Severity) -> Severity:
    """Evento adverso nunca é classificado abaixo de ALTA."""
    if kind == OccurrenceType.EVENTO_ADVERSO and severity in (Severity.BAIXA, Severity.MEDIA):
        return Severity.ALTA
    return severity


def requires_lot_or_cylinder(kind: OccurrenceType) -> bool:
    return kind in (OccurrenceType.NAO_CONFORMIDADE, OccurrenceType.EVENTO_ADVERSO)


def _require_text(value: str | None, field: str, min_len: int = 10) -> None:
    if not value or len(value.strip()) < min_len:
        raise ValidationFailed(f"{field} é obrigatório (mínimo {min_len} caracteres)")


def ensure_can_start_investigation(status: OccurrenceStatus) -> None:
    if status not in (OccurrenceStatus.ABERTA, OccurrenceStatus.AGUARDANDO_EFICACIA):
        raise InvalidTransition(f"Ocorrência em {status} não pode (re)iniciar investigação")


def ensure_can_submit_for_effectiveness(status: OccurrenceStatus, root_cause: str | None,
                                        action_statuses: list[ActionStatus],
                                        action_types: list[ActionType]) -> None:
    if status != OccurrenceStatus.EM_INVESTIGACAO:
        raise InvalidTransition("Só ocorrências em investigação seguem para verificação de eficácia")
    _require_text(root_cause, "Causa raiz")
    if not any(t in (ActionType.CORRETIVA, ActionType.PREVENTIVA) for t in action_types):
        raise ValidationFailed("Cadastre ao menos uma ação corretiva ou preventiva")
    if any(s != ActionStatus.CONCLUIDA for s in action_statuses):
        raise ValidationFailed("Todas as ações precisam estar concluídas")


def ensure_can_close(status: OccurrenceStatus, effectiveness: str | None) -> None:
    if status != OccurrenceStatus.AGUARDANDO_EFICACIA:
        raise InvalidTransition("Encerramento exige verificação de eficácia pendente")
    _require_text(effectiveness, "Verificação de eficácia")


def ensure_can_cancel(status: OccurrenceStatus, justification: str | None) -> None:
    if status not in (OccurrenceStatus.ABERTA, OccurrenceStatus.EM_INVESTIGACAO):
        raise InvalidTransition(f"Ocorrência em {status} não pode ser cancelada")
    _require_text(justification, "Justificativa do cancelamento")


def ensure_action_editable(occurrence_status: OccurrenceStatus) -> None:
    if occurrence_status not in (OccurrenceStatus.ABERTA, OccurrenceStatus.EM_INVESTIGACAO):
        raise InvalidTransition("Ações só podem ser alteradas com a ocorrência aberta ou em investigação")
