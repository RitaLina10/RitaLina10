from datetime import date

import pytest

from app.domain import rules
from app.domain.errors import ComplianceViolation, InvalidTransition, ValidationFailed
from app.domain.rules import CylinderStatus as S, GasCategory, LotStatus, MovementType as M, Role


def test_state_machine():
    assert rules.next_status(S.VAZIO, M.ENVASE) == S.CHEIO
    assert rules.next_status(S.CHEIO, M.ENTREGA) == S.EM_CLIENTE
    assert rules.next_status(S.EM_CLIENTE, M.COLETA) == S.VAZIO
    with pytest.raises(InvalidTransition):
        rules.next_status(S.VAZIO, M.ENTREGA)
    with pytest.raises(InvalidTransition):
        rules.next_status(S.CONDENADO, M.ENVASE)


def test_permissions():
    assert rules.can_perform(Role.MOTORISTA, M.ENTREGA)
    assert not rules.can_perform(Role.MOTORISTA, M.ENVASE)
    assert not rules.can_perform(Role.OPERADOR, M.CONDENACAO)
    assert rules.can_perform(Role.ADMIN, M.CONDENACAO)


def test_hydro():
    assert rules.hydro_due_date(date(2020, 2, 29), 5) == date(2025, 2, 28)
    rules.ensure_hydro_valid(date(2022, 1, 1), 5, date(2026, 12, 31))
    with pytest.raises(ComplianceViolation):
        rules.ensure_hydro_valid(date(2020, 1, 1), 5, date(2026, 1, 2))


def test_documents():
    assert rules.validate_document("529.982.247-25") == "52998224725"
    assert rules.validate_document("11.222.333/0001-81") == "11222333000181"
    for bad in ("111.111.111-11", "123", "11.222.333/0001-80", ""):
        with pytest.raises(ValidationFailed):
            rules.validate_document(bad)


def test_medicinal_delivery_requires_approved_lot():
    today = date(2026, 1, 1)
    rules.ensure_lot_releasable_for_delivery(GasCategory.INDUSTRIAL, None, None, today)
    with pytest.raises(ComplianceViolation):
        rules.ensure_lot_releasable_for_delivery(GasCategory.MEDICINAL, None, None, today)
    with pytest.raises(ComplianceViolation):
        rules.ensure_lot_releasable_for_delivery(GasCategory.MEDICINAL, LotStatus.QUARENTENA, date(2027, 1, 1), today)
    with pytest.raises(ComplianceViolation):
        rules.ensure_lot_releasable_for_delivery(GasCategory.MEDICINAL, LotStatus.APROVADO, date(2025, 1, 1), today)


def test_hash_chain_is_deterministic():
    a = rules.movement_hash(rules.GENESIS_HASH, {"x": 1, "d": date(2026, 1, 1)})
    assert a == rules.movement_hash(rules.GENESIS_HASH, {"d": date(2026, 1, 1), "x": 1})
    assert a != rules.movement_hash(rules.GENESIS_HASH, {"x": 2, "d": date(2026, 1, 1)})


def test_serial():
    assert rules.normalize_serial(" ab-123 ") == "AB-123"
    with pytest.raises(ValidationFailed):
        rules.normalize_serial("a; DROP TABLE")
