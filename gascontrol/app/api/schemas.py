"""DTOs de entrada/saída. Toda entrada é validada aqui antes de chegar ao domínio."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.domain.rules import CylinderStatus, GasCategory, LotStatus, MovementType, Role

Str120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
OptStr = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=300)]
Notes = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=1000)]
DocRef = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60,
                                                 pattern=r"^[A-Za-z0-9\-/\. ]*$")]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40,
                                        pattern=r"^[A-Za-z0-9\-_/\.]+$")]

# Aceita o payload do QR ("GC1:<serial>") ou o serial puro; o domínio normaliza.
ScannedSerial = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=44,
                                                 pattern=r"^(GC1:)?[A-Za-z0-9\-]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth/users ----
class LoginIn(Strict):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Role
    name: str


class UserIn(Strict):
    email: EmailStr
    name: Str120
    password: Annotated[str, StringConstraints(min_length=10, max_length=128)]
    role: Role


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: Role
    active: bool


class ActiveIn(Strict):
    active: bool


# ---- catálogo ----
class GasTypeIn(Strict):
    code: Code
    name: Str120
    category: GasCategory


class GasTypeOut(ORM):
    id: int
    code: str
    name: str
    category: GasCategory


class CustomerIn(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    document: Annotated[str, StringConstraints(strip_whitespace=True, min_length=11, max_length=20)]
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=30,
                                                   pattern=r"^[0-9()+\- ]*$")] = None
    address: OptStr = None
    is_health_facility: bool = False


class CustomerPatch(Strict):
    name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)] = None
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=30,
                                                   pattern=r"^[0-9()+\- ]*$")] = None
    address: OptStr = None
    is_health_facility: bool | None = None
    active: bool | None = None


class CustomerOut(ORM):
    id: int
    name: str
    document: str
    phone: str | None
    address: str | None
    is_health_facility: bool
    active: bool


# ---- lotes ----
class LotIn(Strict):
    code: Code
    gas_type_id: int = Field(gt=0)
    production_date: date
    expiry_date: date
    purity_percent: float | None = Field(default=None, ge=0, le=100)
    analysis_report: DocRef = None


class LotDecisionIn(Strict):
    approve: bool
    notes: Notes = None
    signature_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class LotOut(ORM):
    id: int
    code: str
    gas_type: GasTypeOut
    production_date: date
    expiry_date: date
    purity_percent: float | None
    analysis_report: str | None
    status: LotStatus
    released_by_id: int | None
    released_at: datetime | None
    release_notes: str | None
    signature_meaning: str | None = None
    signature_hash: str | None = None


class LotBrief(ORM):
    id: int
    code: str
    status: LotStatus
    expiry_date: date


class CustomerBrief(ORM):
    id: int
    name: str


# ---- cilindros ----
class CylinderIn(Strict):
    serial: Code
    gas_type_id: int = Field(gt=0)
    capacity_liters: float = Field(gt=0, le=100_000)
    last_hydro_test: date
    manufacturer: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = None
    manufacture_date: date | None = None
    owned_by_company: bool = True


class CylinderOut(ORM):
    id: int
    serial: str
    gas_type: GasTypeOut
    capacity_liters: float
    manufacturer: str | None
    manufacture_date: date | None
    last_hydro_test: date
    hydro_due_date: date | None = None
    owned_by_company: bool
    status: CylinderStatus
    current_customer: CustomerBrief | None
    current_lot: LotBrief | None
    is_loan: bool


class MovementIn(Strict):
    serial: ScannedSerial
    type: MovementType
    customer_id: int | None = Field(default=None, gt=0)
    lot_id: int | None = Field(default=None, gt=0)
    is_loan: bool = False
    document_ref: DocRef = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: Notes = None
    new_hydro_test: date | None = None
    checklist: dict[Annotated[str, StringConstraints(max_length=40)], bool] | None = Field(default=None, max_length=20)

    @field_validator("type")
    @classmethod
    def _no_cadastro(cls, v: MovementType) -> MovementType:
        if v == MovementType.CADASTRO:
            raise ValueError("CADASTRO é gerado automaticamente")
        return v


class ExchangeIn(Strict):
    full_serial: ScannedSerial
    empty_serial: ScannedSerial
    customer_id: int = Field(gt=0)
    is_loan: bool = False
    document_ref: DocRef = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    notes: Notes = None


class UserBrief(ORM):
    id: int
    name: str


class CylinderBrief(ORM):
    id: int
    serial: str


class MovementOut(ORM):
    id: int
    operation_id: str
    cylinder: CylinderBrief
    type: MovementType
    from_status: CylinderStatus | None
    to_status: CylinderStatus
    customer: CustomerBrief | None
    lot: LotBrief | None
    user: UserBrief
    is_loan: bool
    document_ref: str | None
    latitude: float | None
    longitude: float | None
    notes: str | None
    occurred_at: datetime
    client_occurred_at: datetime | None = None
    offline: bool | None = None
    checklist: str | None = None
    hash: str


class CylinderHistoryOut(BaseModel):
    cylinder: CylinderOut
    movements: list[MovementOut]


class LotTraceOut(BaseModel):
    lot: LotOut
    movements: list[MovementOut]


class ErrorOut(BaseModel):
    error: str
    message: str
    trace_id: str


UUIDStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]


class SyncMovementItem(Strict):
    client_uuid: UUIDStr
    kind: Literal["movement"]
    occurred_at: datetime
    payload: MovementIn


class SyncExchangeItem(Strict):
    client_uuid: UUIDStr
    kind: Literal["exchange"]
    occurred_at: datetime
    payload: ExchangeIn


class SyncBatchIn(Strict):
    items: list[Annotated[SyncMovementItem | SyncExchangeItem, Field(discriminator="kind")]] = Field(max_length=200)


class SyncResultOut(BaseModel):
    client_uuid: str
    status: Literal["ok", "duplicate", "rejected"]
    movement_ids: list[int] | None = None
    error: str | None = None
    message: str | None = None
    retryable: bool | None = None


class AuditEventOut(ORM):
    id: int
    occurred_at: datetime
    user: UserBrief | None
    action: str
    entity: str
    entity_id: int | None
    data: str
    hash: str
