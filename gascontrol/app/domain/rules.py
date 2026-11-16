"""Regras de negócio puras (sem I/O). Toda decisão regulatória vive aqui."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from enum import StrEnum

from app.domain.errors import ComplianceViolation, InvalidTransition, ValidationFailed


class Role(StrEnum):
    ADMIN = "ADMIN"            # gestão de usuários + tudo
    GESTOR = "GESTOR"          # libera lotes (responsável técnico), cadastros
    OPERADOR = "OPERADOR"      # envase, manutenção, cadastro de cilindros
    MOTORISTA = "MOTORISTA"    # entrega, coleta, troca


class GasCategory(StrEnum):
    MEDICINAL = "MEDICINAL"
    INDUSTRIAL = "INDUSTRIAL"


class CylinderStatus(StrEnum):
    VAZIO = "VAZIO"
    CHEIO = "CHEIO"
    EM_CLIENTE = "EM_CLIENTE"
    MANUTENCAO = "MANUTENCAO"
    CONDENADO = "CONDENADO"


class MovementType(StrEnum):
    CADASTRO = "CADASTRO"
    ENVASE = "ENVASE"
    ENTREGA = "ENTREGA"
    COLETA = "COLETA"
    ENVIO_MANUTENCAO = "ENVIO_MANUTENCAO"
    RETORNO_MANUTENCAO = "RETORNO_MANUTENCAO"
    CONDENACAO = "CONDENACAO"


class LotStatus(StrEnum):
    QUARENTENA = "QUARENTENA"
    APROVADO = "APROVADO"
    REPROVADO = "REPROVADO"


# Máquina de estados: tipo -> (estados de origem permitidos, estado destino)
TRANSITIONS: dict[MovementType, tuple[frozenset[CylinderStatus], CylinderStatus]] = {
    MovementType.ENVASE: (frozenset({CylinderStatus.VAZIO}), CylinderStatus.CHEIO),
    MovementType.ENTREGA: (frozenset({CylinderStatus.CHEIO}), CylinderStatus.EM_CLIENTE),
    MovementType.COLETA: (frozenset({CylinderStatus.EM_CLIENTE}), CylinderStatus.VAZIO),
    MovementType.ENVIO_MANUTENCAO: (
        frozenset({CylinderStatus.VAZIO, CylinderStatus.CHEIO}), CylinderStatus.MANUTENCAO
    ),
    MovementType.RETORNO_MANUTENCAO: (frozenset({CylinderStatus.MANUTENCAO}), CylinderStatus.VAZIO),
    MovementType.CONDENACAO: (
        frozenset({CylinderStatus.VAZIO, CylinderStatus.MANUTENCAO}), CylinderStatus.CONDENADO
    ),
}

# Quais papéis podem executar cada movimentação (ADMIN implícito em todas).
MOVEMENT_PERMISSIONS: dict[MovementType, frozenset[Role]] = {
    MovementType.ENVASE: frozenset({Role.OPERADOR, Role.GESTOR}),
    MovementType.ENTREGA: frozenset({Role.MOTORISTA, Role.GESTOR, Role.OPERADOR}),
    MovementType.COLETA: frozenset({Role.MOTORISTA, Role.GESTOR, Role.OPERADOR}),
    MovementType.ENVIO_MANUTENCAO: frozenset({Role.OPERADOR, Role.GESTOR}),
    MovementType.RETORNO_MANUTENCAO: frozenset({Role.OPERADOR, Role.GESTOR}),
    MovementType.CONDENACAO: frozenset({Role.GESTOR}),
}


def can_perform(role: Role, movement: MovementType) -> bool:
    return role == Role.ADMIN or role in MOVEMENT_PERMISSIONS.get(movement, frozenset())


def next_status(current: CylinderStatus, movement: MovementType) -> CylinderStatus:
    rule = TRANSITIONS.get(movement)
    if rule is None:
        raise InvalidTransition(f"Movimentação {movement} não é uma transição operacional")
    allowed, target = rule
    if current not in allowed:
        raise InvalidTransition(
            f"Cilindro em '{current}' não aceita '{movement}' (permitido a partir de: "
            f"{', '.join(sorted(allowed))})"
        )
    return target


# ---------------- Teste hidrostático ----------------

def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29/02 -> 28/02
        return d.replace(year=d.year + years, day=28)


def hydro_due_date(last_test: date, validity_years: int) -> date:
    return add_years(last_test, validity_years)


def ensure_hydro_valid(last_test: date, validity_years: int, today: date) -> None:
    due = hydro_due_date(last_test, validity_years)
    if due < today:
        raise ComplianceViolation(
            f"Teste hidrostático vencido em {due.isoformat()}; cilindro bloqueado para envase"
        )


# ---------------- Lote (rastreabilidade RDC ANVISA) ----------------

def ensure_lot_usable_for_fill(lot_status: LotStatus, lot_gas_type_id: int, cyl_gas_type_id: int,
                               lot_expiry: date, today: date) -> None:
    if lot_gas_type_id != cyl_gas_type_id:
        raise ComplianceViolation("Gás do lote diferente do gás do cilindro")
    if lot_status == LotStatus.REPROVADO:
        raise ComplianceViolation("Lote reprovado não pode ser usado em envase")
    if lot_expiry < today:
        raise ComplianceViolation("Lote com validade expirada")


def ensure_lot_releasable_for_delivery(category: GasCategory, lot_status: LotStatus | None,
                                       lot_expiry: date | None, today: date) -> None:
    """Gás medicinal só sai para o cliente com lote APROVADO e dentro da validade."""
    if category != GasCategory.MEDICINAL:
        return
    if lot_status is None or lot_expiry is None:
        raise ComplianceViolation("Cilindro medicinal sem lote vinculado; entrega bloqueada")
    if lot_status != LotStatus.APROVADO:
        raise ComplianceViolation(f"Lote em '{lot_status}'; entrega de gás medicinal bloqueada")
    if lot_expiry < today:
        raise ComplianceViolation("Lote vencido; entrega de gás medicinal bloqueada")


# ---------------- Validação de documentos ----------------

_DIGITS = re.compile(r"\D")


def normalize_document(raw: str) -> str:
    return _DIGITS.sub("", raw or "")


def _cpf_valid(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _cnpj_valid(d: str) -> bool:
    if len(d) != 14 or d == d[0] * 14:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    for weights, pos in ((w1, 12), (w2, 13)):
        s = sum(int(d[i]) * weights[i] for i in range(pos))
        r = s % 11
        if (0 if r < 2 else 11 - r) != int(d[pos]):
            return False
    return True


def validate_document(raw: str) -> str:
    d = normalize_document(raw)
    if len(d) == 11 and _cpf_valid(d):
        return d
    if len(d) == 14 and _cnpj_valid(d):
        return d
    raise ValidationFailed("CPF/CNPJ inválido")


SERIAL_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{2,39}$")


def normalize_serial(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not SERIAL_RE.fullmatch(s):
        raise ValidationFailed("Número de série inválido (3-40 caracteres: A-Z, 0-9, '-')")
    return s


# ---------------- Trilha de auditoria encadeada ----------------

GENESIS_HASH = "0" * 64


def movement_hash(prev_hash: str, payload: dict[str, object]) -> str:
    """SHA-256 de (hash anterior + payload canônico). Qualquer edição posterior quebra a cadeia."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _json_default(o: object) -> str:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"tipo não serializável: {type(o)!r}")
