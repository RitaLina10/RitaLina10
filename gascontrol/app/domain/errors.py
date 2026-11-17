"""Exceções de domínio. A camada de API mapeia cada uma para um status HTTP."""
from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"
    http_status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    code = "not_found"
    http_status = 404


class Conflict(DomainError):
    code = "conflict"
    http_status = 409


class ConcurrencyConflict(Conflict):
    """Corrida entre operações simultâneas; seguro tentar novamente."""

    code = "concurrency_conflict"


class InvalidTransition(DomainError):
    code = "invalid_transition"


class ComplianceViolation(DomainError):
    """Bloqueio regulatório: teste hidrostático vencido, lote não liberado etc."""

    code = "compliance_violation"


class ValidationFailed(DomainError):
    code = "validation_failed"


class Forbidden(DomainError):
    code = "forbidden"
    http_status = 403


class ExternalServiceError(DomainError):
    """Serviço externo indisponível (ex.: emissor de NF-e). Nada foi enviado."""

    code = "external_service_unavailable"
    http_status = 503
