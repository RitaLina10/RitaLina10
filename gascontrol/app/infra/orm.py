"""Modelo relacional. Movimentações são append-only (sem UPDATE/DELETE pela aplicação)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.rules import CylinderStatus, GasCategory, LotStatus, MovementType, Role
from app.infra.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GasType(Base):
    __tablename__ = "gas_types"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[GasCategory] = mapped_column(Enum(GasCategory, native_enum=False, length=20))


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    document: Mapped[str] = mapped_column(String(14), unique=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(300))
    is_health_facility: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Lot(Base):
    __tablename__ = "lots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    gas_type_id: Mapped[int] = mapped_column(ForeignKey("gas_types.id"))
    production_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date)
    purity_percent: Mapped[float | None] = mapped_column(Numeric(6, 3))
    analysis_report: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[LotStatus] = mapped_column(Enum(LotStatus, native_enum=False, length=20))
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_notes: Mapped[str | None] = mapped_column(String(500))
    signature_meaning: Mapped[str | None] = mapped_column(String(160))
    signature_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gas_type: Mapped[GasType] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint("expiry_date >= production_date", name="ck_lot_dates"),)


class Cylinder(Base):
    __tablename__ = "cylinders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    gas_type_id: Mapped[int] = mapped_column(ForeignKey("gas_types.id"))
    capacity_liters: Mapped[float] = mapped_column(Numeric(8, 2))
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    manufacture_date: Mapped[date | None] = mapped_column(Date)
    last_hydro_test: Mapped[date] = mapped_column(Date)
    owned_by_company: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[CylinderStatus] = mapped_column(
        Enum(CylinderStatus, native_enum=False, length=20), index=True
    )
    current_customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    current_lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"))
    is_loan: Mapped[bool] = mapped_column(Boolean, default=False)  # comodato
    last_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    gas_type: Mapped[GasType] = relationship(lazy="joined")
    current_customer: Mapped[Customer | None] = relationship(lazy="joined")
    current_lot: Mapped[Lot | None] = relationship(lazy="joined")

    __mapper_args__ = {"version_id_col": version}  # lock otimista contra bipagem dupla
    __table_args__ = (CheckConstraint("capacity_liters > 0", name="ck_cyl_capacity"),)


class Movement(Base):
    __tablename__ = "movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), index=True)
    cylinder_id: Mapped[int] = mapped_column(ForeignKey("cylinders.id"))
    type: Mapped[MovementType] = mapped_column(Enum(MovementType, native_enum=False, length=30))
    from_status: Mapped[CylinderStatus | None] = mapped_column(
        Enum(CylinderStatus, native_enum=False, length=20)
    )
    to_status: Mapped[CylinderStatus] = mapped_column(Enum(CylinderStatus, native_enum=False, length=20))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_loan: Mapped[bool] = mapped_column(Boolean, default=False)
    document_ref: Mapped[str | None] = mapped_column(String(60))  # NF-e / romaneio
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    client_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offline: Mapped[bool | None] = mapped_column(Boolean, default=False)
    checklist: Mapped[str | None] = mapped_column(Text)  # JSON da inspeção pré-envase
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)

    cylinder: Mapped[Cylinder] = relationship(lazy="joined")
    customer: Mapped[Customer | None] = relationship(lazy="joined")
    lot: Mapped[Lot | None] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_mov_cyl_time", "cylinder_id", "occurred_at"),
        UniqueConstraint("cylinder_id", "prev_hash", name="uq_mov_chain"),  # impede bifurcação
    )


class SyncReceipt(Base):
    """Recibo de idempotência: a mesma operação offline reenviada nunca duplica movimentação."""
    __tablename__ = "sync_receipts"
    client_uuid: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))
    movement_ids: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    """Trilha de auditoria de cadastros (append-only, encadeada por hash global)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64), unique=True)  # impede bifurcação
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    user: Mapped[User | None] = relationship(lazy="joined")
