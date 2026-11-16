"""Implementações SQLAlchemy das portas. Apenas consultas parametrizadas (ORM/Core)."""
from __future__ import annotations

from datetime import date
from typing import Sequence

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.domain.errors import ConcurrencyConflict
from app.domain.rules import CylinderStatus, LotStatus
from app.infra.orm import AuditEvent, Customer, Cylinder, GasType, Lot, Movement, SyncReceipt, User


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqlUserRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def get(self, user_id: int) -> User | None:
        return self.s.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.s.scalar(select(User).where(User.email == email))

    def list(self) -> Sequence[User]:
        return self.s.scalars(select(User).order_by(User.name)).all()

    def add(self, user: User) -> None:
        self.s.add(user)

    def count(self) -> int:
        return self.s.scalar(select(func.count(User.id))) or 0


class SqlGasTypeRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def get(self, gas_type_id: int) -> GasType | None:
        return self.s.get(GasType, gas_type_id)

    def get_by_code(self, code: str) -> GasType | None:
        return self.s.scalar(select(GasType).where(GasType.code == code))

    def list(self) -> Sequence[GasType]:
        return self.s.scalars(select(GasType).order_by(GasType.category, GasType.name)).all()

    def add(self, gas_type: GasType) -> None:
        self.s.add(gas_type)


class SqlCustomerRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def get(self, customer_id: int) -> Customer | None:
        return self.s.get(Customer, customer_id)

    def get_by_document(self, document: str) -> Customer | None:
        return self.s.scalar(select(Customer).where(Customer.document == document))

    def search(self, q: str | None, limit: int, offset: int) -> Sequence[Customer]:
        stmt = select(Customer).order_by(Customer.name).limit(limit).offset(offset)
        if q:
            stmt = stmt.where(or_(Customer.name.ilike(_like(q), escape="\\"),
                                  Customer.document.like(_like(q), escape="\\")))
        return self.s.scalars(stmt).all()

    def add(self, customer: Customer) -> None:
        self.s.add(customer)


class SqlLotRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def get(self, lot_id: int) -> Lot | None:
        return self.s.get(Lot, lot_id)

    def get_by_code(self, code: str) -> Lot | None:
        return self.s.scalar(select(Lot).where(Lot.code == code))

    def list(self, status: LotStatus | None, limit: int, offset: int) -> Sequence[Lot]:
        stmt = select(Lot).order_by(Lot.created_at.desc()).limit(limit).offset(offset)
        if status:
            stmt = stmt.where(Lot.status == status)
        return self.s.scalars(stmt).all()

    def add(self, lot: Lot) -> None:
        self.s.add(lot)


class SqlCylinderRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def get(self, cylinder_id: int) -> Cylinder | None:
        return self.s.get(Cylinder, cylinder_id)

    def get_by_serial(self, serial: str) -> Cylinder | None:
        return self.s.scalar(select(Cylinder).where(Cylinder.serial == serial))

    def search(self, q: str | None, status: CylinderStatus | None, customer_id: int | None,
               gas_type_id: int | None, limit: int, offset: int) -> Sequence[Cylinder]:
        stmt = select(Cylinder).order_by(Cylinder.serial).limit(limit).offset(offset)
        if q:
            stmt = stmt.where(Cylinder.serial.like(_like(q.upper()), escape="\\"))
        if status:
            stmt = stmt.where(Cylinder.status == status)
        if customer_id:
            stmt = stmt.where(Cylinder.current_customer_id == customer_id)
        if gas_type_id:
            stmt = stmt.where(Cylinder.gas_type_id == gas_type_id)
        return self.s.scalars(stmt).unique().all()

    def add(self, cylinder: Cylinder) -> None:
        self.s.add(cylinder)

    def count_by_status(self) -> dict[str, int]:
        rows = self.s.execute(select(Cylinder.status, func.count()).group_by(Cylinder.status)).all()
        result = {s.value: 0 for s in CylinderStatus}
        result.update({str(st.value if hasattr(st, "value") else st): n for st, n in rows})
        return result

    def count_by_gas_and_status(self) -> list[tuple[str, str, int]]:
        rows = self.s.execute(
            select(GasType.code, Cylinder.status, func.count())
            .join(GasType, GasType.id == Cylinder.gas_type_id)
            .group_by(GasType.code, Cylinder.status)
            .order_by(GasType.code)
        ).all()
        return [(code, str(st.value if hasattr(st, "value") else st), n) for code, st, n in rows]

    def hydro_due_before(self, last_test_cutoff: date) -> Sequence[Cylinder]:
        stmt = (select(Cylinder)
                .where(Cylinder.last_hydro_test <= last_test_cutoff,
                       Cylinder.status != CylinderStatus.CONDENADO)
                .order_by(Cylinder.last_hydro_test))
        return self.s.scalars(stmt).unique().all()

    def balance_by_customer(self) -> list[tuple[int, str, int, int]]:
        rows = self.s.execute(
            select(Customer.id, Customer.name, func.count(Cylinder.id),
                   func.sum(case((Cylinder.is_loan.is_(True), 1), else_=0)))
            .join(Cylinder, Cylinder.current_customer_id == Customer.id)
            .where(Cylinder.status == CylinderStatus.EM_CLIENTE)
            .group_by(Customer.id, Customer.name)
            .order_by(func.count(Cylinder.id).desc())
        ).all()
        return [(cid, name, int(total), int(loans or 0)) for cid, name, total, loans in rows]

    def all_active(self, limit: int) -> Sequence[Cylinder]:
        stmt = (select(Cylinder).where(Cylinder.status != CylinderStatus.CONDENADO)
                .order_by(Cylinder.serial).limit(limit))
        return self.s.scalars(stmt).unique().all()

    def by_lot(self, lot_id: int) -> Sequence[Cylinder]:
        return self.s.scalars(select(Cylinder).where(Cylinder.current_lot_id == lot_id)).unique().all()


class SqlMovementRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def add(self, movement: Movement) -> None:
        self.s.add(movement)

    def for_cylinder(self, cylinder_id: int) -> Sequence[Movement]:
        return self.s.scalars(select(Movement).where(Movement.cylinder_id == cylinder_id)
                              .order_by(Movement.id)).unique().all()

    def for_lot(self, lot_id: int) -> Sequence[Movement]:
        return self.s.scalars(select(Movement).where(Movement.lot_id == lot_id)
                              .order_by(Movement.id)).unique().all()

    def recent(self, limit: int, offset: int, customer_id: int | None,
               user_id: int | None) -> Sequence[Movement]:
        stmt = select(Movement).order_by(Movement.id.desc()).limit(limit).offset(offset)
        if customer_id:
            stmt = stmt.where(Movement.customer_id == customer_id)
        if user_id:
            stmt = stmt.where(Movement.user_id == user_id)
        return self.s.scalars(stmt).unique().all()

    def all_cylinder_ids(self) -> Sequence[int]:
        return self.s.scalars(select(Cylinder.id).order_by(Cylinder.id)).all()


class SqlReceiptRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def get(self, client_uuid: str) -> SyncReceipt | None:
        return self.s.get(SyncReceipt, client_uuid)

    def add(self, receipt: SyncReceipt) -> None:
        self.s.add(receipt)


class SqlAuditRepository:
    def __init__(self, s: Session) -> None:
        self.s = s

    def last_hash(self) -> str | None:
        return self.s.scalar(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1))

    def add(self, event: AuditEvent) -> None:
        self.s.add(event)

    def list(self, entity: str | None, limit: int, offset: int) -> Sequence[AuditEvent]:
        stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit).offset(offset)
        if entity:
            stmt = stmt.where(AuditEvent.entity == entity)
        return self.s.scalars(stmt).unique().all()

    def all_ordered(self) -> Sequence[AuditEvent]:
        return self.s.scalars(select(AuditEvent).order_by(AuditEvent.id)).unique().all()


class SqlUnitOfWork:
    """Transação única por caso de uso. Converte erros de concorrência/integridade em Conflict."""

    def __init__(self, factory: sessionmaker) -> None:
        self._factory = factory

    def __enter__(self) -> "SqlUnitOfWork":
        self.session: Session = self._factory()
        s = self.session
        self.users = SqlUserRepository(s)
        self.gas_types = SqlGasTypeRepository(s)
        self.customers = SqlCustomerRepository(s)
        self.lots = SqlLotRepository(s)
        self.cylinders = SqlCylinderRepository(s)
        self.movements = SqlMovementRepository(s)
        self.receipts = SqlReceiptRepository(s)
        self.audit = SqlAuditRepository(s)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if exc_type is not None:
            self.session.rollback()
        self.session.close()

    def flush(self) -> None:
        try:
            self.session.flush()
        except StaleDataError as e:
            self.session.rollback()
            raise ConcurrencyConflict("Registro alterado por outra operação; tente novamente") from e
        except IntegrityError as e:
            self.session.rollback()
            raise ConcurrencyConflict("Conflito de gravação simultânea ou duplicidade; tente novamente") from e

    def commit(self) -> None:
        try:
            self.session.commit()
        except StaleDataError as e:
            self.session.rollback()
            raise ConcurrencyConflict("Registro alterado por outra operação; tente novamente") from e
        except IntegrityError as e:
            self.session.rollback()
            raise ConcurrencyConflict("Conflito de gravação simultânea ou duplicidade; tente novamente") from e

    def rollback(self) -> None:
        self.session.rollback()

    def refresh(self, obj: object) -> None:
        """Recarrega atributos e relacionamentos eager após commit (para serialização fora da sessão)."""
        self.session.refresh(obj)
