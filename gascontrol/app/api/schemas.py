"""DTOs de entrada/saída. Toda entrada é validada aqui antes de chegar ao domínio."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from decimal import Decimal

from app.domain.fiscal import InvoiceStatus
from app.domain.quality import ActionStatus, ActionType, OccurrenceStatus, OccurrenceType, Severity
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


class PasswordChangeIn(Strict):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Annotated[str, StringConstraints(min_length=10, max_length=128)]


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
    email: EmailStr | None = None
    state_registration: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20,
                                                                pattern=r"^([0-9.\-/]+|ISENTO)$")] = None
    street: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = None
    street_number: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20)] = None
    complement: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60)] = None
    district: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60)] = None
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60)] = None
    uf: Annotated[str | None, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$")] = None
    cep: Annotated[str | None, StringConstraints(strip_whitespace=True, pattern=r"^\d{5}-?\d{3}$")] = None


class CustomerPatch(Strict):
    name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)] = None
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=30,
                                                   pattern=r"^[0-9()+\- ]*$")] = None
    address: OptStr = None
    is_health_facility: bool | None = None
    active: bool | None = None
    email: EmailStr | None = None
    state_registration: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20,
                                                                pattern=r"^([0-9.\-/]+|ISENTO)$")] = None
    street: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = None
    street_number: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20)] = None
    complement: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60)] = None
    district: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60)] = None
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=60)] = None
    uf: Annotated[str | None, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$")] = None
    cep: Annotated[str | None, StringConstraints(strip_whitespace=True, pattern=r"^\d{5}-?\d{3}$")] = None


class CustomerOut(ORM):
    id: int
    name: str
    document: str
    phone: str | None
    address: str | None
    is_health_facility: bool
    active: bool
    email: str | None = None
    state_registration: str | None = None
    street: str | None = None
    street_number: str | None = None
    complement: str | None = None
    district: str | None = None
    city: str | None = None
    uf: str | None = None
    cep: str | None = None


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


# ---- qualidade / CAPA ----
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=5000)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class OccurrenceIn(Strict):
    kind: OccurrenceType
    severity: Severity
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=160)]
    description: LongText
    customer_id: int | None = Field(default=None, gt=0)
    lot_id: int | None = Field(default=None, gt=0)
    serial: ScannedSerial | None = None


class InvestigateIn(Strict):
    owner_id: int | None = Field(default=None, gt=0)


class RootCauseIn(Strict):
    root_cause: LongText


class ActionIn(Strict):
    kind: ActionType
    description: LongText
    responsible_id: int = Field(gt=0)
    due_date: date


class EvidenceIn(Strict):
    evidence: LongText


class ReasonIn(Strict):
    reason: LongText


class SignedTextIn(Strict):
    text: LongText
    signature_password: Password


class SignatureIn(Strict):
    signature_password: Password


class ActionOut(ORM):
    id: int
    kind: ActionType
    description: str
    responsible: UserBrief
    due_date: date
    status: ActionStatus
    evidence: str | None
    completed_at: datetime | None


class OccurrenceOut(ORM):
    id: int
    code: str
    kind: OccurrenceType
    severity: Severity
    status: OccurrenceStatus
    title: str
    description: str
    customer: CustomerBrief | None
    lot: LotBrief | None
    cylinder: CylinderBrief | None
    reported_by: UserBrief
    owner: UserBrief | None
    opened_at: datetime
    due_date: date
    root_cause: str | None
    effectiveness_check: str | None
    closed_at: datetime | None
    closing_signature_hash: str | None
    lot_blocked: bool | None
    actions: list[ActionOut]


# ---- fiscal ----
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=4)]


class FiscalProfileIn(Strict):
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
    ncm: Annotated[str, StringConstraints(pattern=r"^\d{4}\.?\d{2}\.?\d{2}$")]
    cfop_internal: Annotated[str, StringConstraints(pattern=r"^\d{4}$")]
    cfop_interstate: Annotated[str, StringConstraints(pattern=r"^\d{4}$")]
    unit: Annotated[str, StringConstraints(to_upper=True, max_length=6)]
    icms_cst: Annotated[str, StringConstraints(pattern=r"^\d{2,3}$")]
    icms_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal(0)
    pis_cst: Annotated[str, StringConstraints(pattern=r"^\d{2}$")]
    cofins_cst: Annotated[str, StringConstraints(pattern=r"^\d{2}$")]
    origin: int = Field(default=0, ge=0, le=8)
    default_price: Money | None = None


class FiscalProfileOut(ORM):
    gas_type: GasTypeOut
    description: str
    ncm: str
    cfop_internal: str
    cfop_interstate: str
    unit: str
    icms_cst: str
    icms_rate: Decimal
    pis_cst: str
    cofins_cst: str
    origin: int
    default_price: Decimal | None


class InvoiceItemIn(Strict):
    gas_type_id: int = Field(gt=0)
    quantity: Money
    unit_price: Money | None = None
    description: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = None


class InvoiceIn(Strict):
    customer_id: int = Field(gt=0)
    nature: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=60)] = "Venda de mercadoria"
    items: list[InvoiceItemIn] = Field(min_length=1, max_length=50)
    notes: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None


class InvoiceUpdateIn(Strict):
    nature: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=60)]
    items: list[InvoiceItemIn] = Field(min_length=1, max_length=50)
    notes: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None


class FromOperationIn(Strict):
    operation_id: UUIDStr


class CancelInvoiceIn(Strict):
    justification: Annotated[str, StringConstraints(strip_whitespace=True, min_length=15, max_length=255)]
    signature_password: Password


class InvoiceItemOut(ORM):
    gas_type: GasTypeOut
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


class InvoiceOut(ORM):
    id: int
    ref: str
    customer: CustomerBrief
    status: InvoiceStatus
    nature: str
    operation_id: str | None
    notes: str | None
    total: Decimal
    access_key: str | None
    number: str | None
    series: str | None
    danfe_url: str | None
    xml_url: str | None
    provider_message: str | None
    authorized_at: datetime | None
    cancel_justification: str | None
    created_at: datetime
    items: list[InvoiceItemOut]
