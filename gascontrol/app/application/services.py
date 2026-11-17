"""Casos de uso. Cada método = uma transação (Unit of Work)."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Sequence

from app.application.ports import UnitOfWork
from app.application.security import DUMMY_HASH, hash_password, verify_password
from app.domain import rules
from app.domain.errors import (
    ComplianceViolation, ConcurrencyConflict, Conflict, DomainError, Forbidden, NotFound, ValidationFailed,
)
from app.domain.rules import (
    GENESIS_HASH, CylinderStatus, GasCategory, LotStatus, MovementType, Role,
)
from app.infra.orm import AuditEvent, Customer, Cylinder, GasType, Lot, Movement, SyncReceipt, User
from app.observability import DOMAIN_REJECTIONS, MOVEMENTS

log = logging.getLogger("gascontrol.services")

UowFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(dt: datetime) -> datetime:
    """Normaliza para UTC sem tz (SQLite descarta tz); usado no hash para ser reprodutível."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: Role


@dataclass(frozen=True)
class MovementInput:
    serial: str
    type: MovementType
    customer_id: int | None = None
    lot_id: int | None = None
    is_loan: bool = False
    document_ref: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None
    new_hydro_test: date | None = None
    checklist: dict[str, bool] | None = None
    client_occurred_at: datetime | None = None
    offline: bool = False


@dataclass(frozen=True)
class ExchangeInput:
    full_serial: str
    empty_serial: str
    customer_id: int
    is_loan: bool = False
    document_ref: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None
    client_occurred_at: datetime | None = None
    offline: bool = False


@dataclass(frozen=True)
class SyncItem:
    client_uuid: str
    kind: str  # "movement" | "exchange"
    movement: MovementInput | None = None
    exchange: ExchangeInput | None = None


def _verify_signer(uow: UnitOfWork, actor: Actor, password: str) -> User:
    """Assinatura eletrônica: reautentica o usuário no ato (senha), dentro da mesma transação."""
    signer = uow.users.get(actor.user_id)
    if signer is None or not signer.active or not verify_password(password or "", signer.password_hash):
        log.warning("signature_failed", extra={"user_id": actor.user_id})
        raise Forbidden("Assinatura eletrônica inválida: senha incorreta")
    return signer


def _signature_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _require_role(actor: Actor, *roles: Role) -> None:
    if actor.role != Role.ADMIN and actor.role not in roles:
        raise Forbidden("Perfil sem permissão para esta operação")


def _hash_payload(m: Movement) -> dict[str, object]:
    payload: dict[str, object] = {
        "operation_id": m.operation_id, "cylinder_id": m.cylinder_id, "type": str(m.type),
        "from": str(m.from_status) if m.from_status else None, "to": str(m.to_status),
        "customer_id": m.customer_id, "lot_id": m.lot_id, "user_id": m.user_id,
        "is_loan": bool(m.is_loan), "document_ref": m.document_ref,
        "lat": None if m.latitude is None else f"{float(m.latitude):.6f}",
        "lon": None if m.longitude is None else f"{float(m.longitude):.6f}",
        "notes": m.notes, "occurred_at": _naive_utc(m.occurred_at).isoformat(timespec="microseconds"),
    }
    # Campos adicionados depois: só entram no hash quando presentes (compatível com cadeias antigas).
    if m.client_occurred_at is not None:
        payload["client_occurred_at"] = _naive_utc(m.client_occurred_at).isoformat(timespec="microseconds")
    if m.offline:
        payload["offline"] = True
    if m.checklist:
        payload["checklist"] = m.checklist
    return payload


def _audit(uow: UnitOfWork, user_id: int | None, action: str, entity: str, entity_id: int | None,
           data: dict[str, object], now: datetime) -> None:
    """Registra evento de cadastro na trilha global encadeada (mesma transação da alteração)."""
    prev = uow.audit.last_hash() or GENESIS_HASH
    body = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    ev = AuditEvent(occurred_at=_naive_utc(now), user_id=user_id, action=action, entity=entity,
                    entity_id=entity_id, data=body, prev_hash=prev)
    ev.hash = rules.movement_hash(prev, _audit_payload(ev))
    uow.audit.add(ev)


def _audit_payload(ev: AuditEvent) -> dict[str, object]:
    return {"at": _naive_utc(ev.occurred_at).isoformat(timespec="microseconds"), "user_id": ev.user_id,
            "action": ev.action, "entity": ev.entity, "entity_id": ev.entity_id, "data": ev.data}


class AuthService:
    def __init__(self, uow: UowFactory, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._clock = clock

    def authenticate(self, email: str, password: str) -> User | None:
        with self._uow() as uow:
            user = uow.users.get_by_email(email.strip().lower())
            if user is None or not user.active:
                verify_password(password, DUMMY_HASH)  # tempo constante
                return None
            return user if verify_password(password, user.password_hash) else None

    def verify_signature(self, user_id: int, password: str) -> bool:
        with self._uow() as uow:
            u = uow.users.get(user_id)
            return bool(u and u.active and verify_password(password, u.password_hash))

    def get_active_user(self, user_id: int) -> User | None:
        with self._uow() as uow:
            u = uow.users.get(user_id)
            return u if u and u.active else None

    def create_user(self, actor: Actor | None, email: str, name: str, password: str, role: Role) -> User:
        if actor is not None:
            _require_role(actor, Role.ADMIN)
        with self._uow() as uow:
            email = email.strip().lower()
            if uow.users.get_by_email(email):
                raise Conflict("E-mail já cadastrado")
            user = User(email=email, name=name.strip(), password_hash=hash_password(password),
                        role=role, active=True, created_at=self._clock())
            uow.users.add(user)
            uow.flush()
            _audit(uow, actor.user_id if actor else None, "CRIAR", "usuario", user.id,
                   {"email": email, "role": str(role)}, self._clock())
            uow.commit()
            log.info("user_created", extra={"user_id": user.id, "role": str(role)})
            return user

    def change_password(self, actor: Actor, current: str, new: str) -> None:
        if current == new:
            raise ValidationFailed("A nova senha deve ser diferente da atual")
        new_hash = hash_password(new)  # valida a força antes de tocar no banco
        with self._uow() as uow:
            u = uow.users.get(actor.user_id)
            if not u or not u.active or not verify_password(current, u.password_hash):
                raise Forbidden("Senha atual incorreta")
            u.password_hash = new_hash
            u.password_changed_at = self._clock()
            _audit(uow, actor.user_id, "TROCAR_SENHA", "usuario", u.id, {}, self._clock())
            uow.commit()
            log.info("password_changed", extra={"user_id": u.id})

    def list_users(self, actor: Actor) -> Sequence[User]:
        _require_role(actor, Role.ADMIN)
        with self._uow() as uow:
            return uow.users.list()

    def set_active(self, actor: Actor, user_id: int, active: bool) -> User:
        _require_role(actor, Role.ADMIN)
        if actor.user_id == user_id and not active:
            raise ValidationFailed("Não é possível desativar o próprio usuário")
        with self._uow() as uow:
            u = uow.users.get(user_id)
            if not u:
                raise NotFound("Usuário não encontrado")
            u.active = active
            _audit(uow, actor.user_id, "ATIVAR" if active else "DESATIVAR", "usuario", u.id, {}, self._clock())
            uow.commit()
            return u

    def bootstrap_admin(self, email: str | None, password: str | None) -> None:
        with self._uow() as uow:
            if uow.users.count() > 0:
                return
        if not email or not password:
            log.warning("no_users_and_no_bootstrap_admin",
                        extra={"hint": "defina ADMIN_EMAIL e ADMIN_PASSWORD"})
            return
        self.create_user(None, email, "Administrador", password, Role.ADMIN)
        log.info("bootstrap_admin_created")


DEFAULT_GASES: tuple[tuple[str, str, GasCategory], ...] = (
    ("O2-MED", "Oxigênio Medicinal", GasCategory.MEDICINAL),
    ("AR-MED", "Ar Comprimido Medicinal", GasCategory.MEDICINAL),
    ("N2O-MED", "Óxido Nitroso Medicinal", GasCategory.MEDICINAL),
    ("CO2-MED", "Dióxido de Carbono Medicinal", GasCategory.MEDICINAL),
    ("O2-IND", "Oxigênio Industrial", GasCategory.INDUSTRIAL),
    ("N2-IND", "Nitrogênio Industrial", GasCategory.INDUSTRIAL),
    ("AR-IND", "Argônio Industrial", GasCategory.INDUSTRIAL),
    ("CO2-IND", "Dióxido de Carbono Industrial", GasCategory.INDUSTRIAL),
    ("C2H2", "Acetileno", GasCategory.INDUSTRIAL),
    ("MIX-SOLDA", "Mistura Ar/CO2 (solda)", GasCategory.INDUSTRIAL),
)


class CatalogService:
    def __init__(self, uow: UowFactory, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._clock = clock

    def seed_gas_types(self) -> None:
        with self._uow() as uow:
            for code, name, cat in DEFAULT_GASES:
                if not uow.gas_types.get_by_code(code):
                    uow.gas_types.add(GasType(code=code, name=name, category=cat))
            uow.commit()

    def list_gas_types(self) -> Sequence[GasType]:
        with self._uow() as uow:
            return uow.gas_types.list()

    def create_gas_type(self, actor: Actor, code: str, name: str, category: GasCategory) -> GasType:
        _require_role(actor, Role.GESTOR)
        with self._uow() as uow:
            code = code.strip().upper()
            if uow.gas_types.get_by_code(code):
                raise Conflict("Código de gás já existe")
            g = GasType(code=code, name=name.strip(), category=category)
            uow.gas_types.add(g)
            uow.flush()
            _audit(uow, actor.user_id, "CRIAR", "gas", g.id, {"code": code, "category": str(category)}, self._clock())
            uow.commit()
            return g

    # ---- clientes ----
    ADDRESS_FIELDS = frozenset({"email", "state_registration", "street", "street_number", "complement",
                                "district", "city", "uf", "cep"})

    @staticmethod
    def _norm_address(fields: dict[str, object]) -> dict[str, object]:
        out = dict(fields)
        if out.get("cep"):
            out["cep"] = rules.normalize_document(str(out["cep"]))
        if out.get("uf"):
            out["uf"] = str(out["uf"]).upper()
        if out.get("email"):
            out["email"] = str(out["email"]).lower()
        return out

    def create_customer(self, actor: Actor, name: str, document: str, phone: str | None,
                        address: str | None, is_health_facility: bool, **extra: object) -> Customer:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        doc = rules.validate_document(document)
        extra = self._norm_address({k: v for k, v in extra.items() if k in self.ADDRESS_FIELDS and v})
        with self._uow() as uow:
            if uow.customers.get_by_document(doc):
                raise Conflict("Cliente com este CPF/CNPJ já existe")
            c = Customer(name=name.strip(), document=doc, phone=phone, address=address,
                         is_health_facility=is_health_facility, active=True, created_at=self._clock(), **extra)
            uow.customers.add(c)
            uow.flush()
            _audit(uow, actor.user_id, "CRIAR", "cliente", c.id, {"name": c.name, "document": doc}, self._clock())
            uow.commit()
            return c

    def update_customer(self, actor: Actor, customer_id: int, **fields: object) -> Customer:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        allowed = {"name", "phone", "address", "is_health_facility", "active"} | self.ADDRESS_FIELDS
        fields = self._norm_address(fields)
        with self._uow() as uow:
            c = uow.customers.get(customer_id)
            if not c:
                raise NotFound("Cliente não encontrado")
            changes: dict[str, object] = {}
            for k, v in fields.items():
                if k in allowed and v is not None:
                    new = v.strip() if isinstance(v, str) else v
                    if getattr(c, k) != new:
                        changes[k] = {"de": getattr(c, k), "para": new}
                        setattr(c, k, new)
            if changes:
                _audit(uow, actor.user_id, "ALTERAR", "cliente", c.id, changes, self._clock())
            uow.commit()
            return c

    def search_customers(self, q: str | None, limit: int, offset: int) -> Sequence[Customer]:
        with self._uow() as uow:
            return uow.customers.search(q, limit, offset)

    def get_customer(self, customer_id: int) -> Customer:
        with self._uow() as uow:
            c = uow.customers.get(customer_id)
            if not c:
                raise NotFound("Cliente não encontrado")
            return c


class LotService:
    def __init__(self, uow: UowFactory, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._clock = clock

    def create(self, actor: Actor, code: str, gas_type_id: int, production_date: date,
               expiry_date: date, purity_percent: float | None, analysis_report: str | None) -> Lot:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        if expiry_date < production_date:
            raise ValidationFailed("Validade anterior à produção")
        with self._uow() as uow:
            if not uow.gas_types.get(gas_type_id):
                raise NotFound("Tipo de gás não encontrado")
            code = code.strip().upper()
            if uow.lots.get_by_code(code):
                raise Conflict("Código de lote já existe")
            lot = Lot(code=code, gas_type_id=gas_type_id, production_date=production_date,
                      expiry_date=expiry_date, purity_percent=purity_percent,
                      analysis_report=analysis_report, status=LotStatus.QUARENTENA,
                      created_at=self._clock())
            uow.lots.add(lot)
            uow.flush()
            _audit(uow, actor.user_id, "CRIAR", "lote", lot.id,
                   {"code": code, "gas_type_id": gas_type_id, "expiry": expiry_date.isoformat(),
                    "analysis_report": analysis_report}, self._clock())
            uow.commit()
            uow.refresh(lot)
            return lot

    def decide(self, actor: Actor, lot_id: int, approve: bool, notes: str | None, password: str) -> Lot:
        """Liberação pelo responsável técnico (GESTOR) com assinatura eletrônica (reautenticação)."""
        _require_role(actor, Role.GESTOR)
        with self._uow() as uow:
            signer = uow.users.get(actor.user_id)
            if signer is None or not verify_password(password, signer.password_hash):
                log.warning("signature_failed", extra={"user_id": actor.user_id, "lot_id": lot_id})
                raise Forbidden("Assinatura eletrônica inválida: senha incorreta")
            lot = uow.lots.get(lot_id)
            if not lot:
                raise NotFound("Lote não encontrado")
            if lot.status != LotStatus.QUARENTENA:
                raise Conflict(f"Lote já decidido ({lot.status})")
            if approve and lot.gas_type.category == GasCategory.MEDICINAL and not lot.analysis_report:
                raise ComplianceViolation("Lote medicinal exige número do laudo de análise para aprovação")
            now = self._clock()
            lot.status = LotStatus.APROVADO if approve else LotStatus.REPROVADO
            lot.released_by_id = actor.user_id
            lot.released_at = now
            lot.release_notes = notes
            meaning = ("Aprovo a liberação deste lote para uso" if approve
                       else "Reprovo este lote; uso proibido")
            lot.signature_meaning = f"{signer.name} <{signer.email}>: {meaning}"
            lot.signature_hash = hashlib.sha256(json.dumps({
                "lot": lot.code, "gas": lot.gas_type_id, "expiry": lot.expiry_date.isoformat(),
                "report": lot.analysis_report, "status": str(lot.status), "signer": signer.id,
                "meaning": lot.signature_meaning, "at": _naive_utc(now).isoformat(), "notes": notes,
            }, sort_keys=True).encode()).hexdigest()
            _audit(uow, actor.user_id, "ASSINAR_" + str(lot.status), "lote", lot.id,
                   {"code": lot.code, "signature_hash": lot.signature_hash, "notes": notes}, now)
            uow.commit()
            log.info("lot_decided", extra={"lot_id": lot.id, "status": str(lot.status)})
            return lot

    def list(self, status: LotStatus | None, limit: int, offset: int) -> Sequence[Lot]:
        with self._uow() as uow:
            return uow.lots.list(status, limit, offset)

    def trace(self, lot_id: int) -> tuple[Lot, Sequence[Movement]]:
        """Recall: todos os cilindros/clientes que receberam este lote."""
        with self._uow() as uow:
            lot = uow.lots.get(lot_id)
            if not lot:
                raise NotFound("Lote não encontrado")
            filled_ids = {m.cylinder_id for m in uow.movements.for_lot(lot_id)}
            movements: list[Movement] = []
            for cid in sorted(filled_ids):
                movements.extend(m for m in uow.movements.for_cylinder(cid) if m.lot_id == lot_id)
            movements.sort(key=lambda m: m.id)
            return lot, movements


class CylinderService:
    def __init__(self, uow: UowFactory, hydro_years: int, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._hydro_years = hydro_years
        self._clock = clock

    # ---- cadastro ----
    def register(self, actor: Actor, serial: str, gas_type_id: int, capacity_liters: float,
                 last_hydro_test: date, manufacturer: str | None, manufacture_date: date | None,
                 owned_by_company: bool) -> Cylinder:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        serial = rules.normalize_serial(serial)
        today = self._clock().date()
        if last_hydro_test > today:
            raise ValidationFailed("Data do teste hidrostático no futuro")
        if manufacture_date and manufacture_date > last_hydro_test:
            raise ValidationFailed("Fabricação posterior ao último teste hidrostático")
        with self._uow() as uow:
            if not uow.gas_types.get(gas_type_id):
                raise NotFound("Tipo de gás não encontrado")
            if uow.cylinders.get_by_serial(serial):
                raise Conflict("Número de série já cadastrado")
            now = self._clock()
            cyl = Cylinder(serial=serial, gas_type_id=gas_type_id, capacity_liters=capacity_liters,
                           manufacturer=manufacturer, manufacture_date=manufacture_date,
                           last_hydro_test=last_hydro_test, owned_by_company=owned_by_company,
                           status=CylinderStatus.VAZIO, is_loan=False, last_hash=GENESIS_HASH,
                           created_at=now)
            uow.cylinders.add(cyl)
            uow.flush()
            self._append(uow, cyl, MovementType.CADASTRO, None, CylinderStatus.VAZIO,
                         str(uuid.uuid4()), actor, now, notes="Cadastro inicial")
            _audit(uow, actor.user_id, "CRIAR", "cilindro", cyl.id,
                   {"serial": serial, "gas_type_id": gas_type_id, "last_hydro_test": last_hydro_test.isoformat()},
                   now)
            uow.commit()
            uow.refresh(cyl)
            log.info("cylinder_registered", extra={"cylinder_id": cyl.id, "serial": serial})
            return cyl

    def get_by_serial(self, serial: str) -> Cylinder:
        with self._uow() as uow:
            cyl = uow.cylinders.get_by_serial(rules.normalize_serial(serial))
            if not cyl:
                raise NotFound("Cilindro não encontrado")
            return cyl

    def search(self, q: str | None, status: CylinderStatus | None, customer_id: int | None,
               gas_type_id: int | None, limit: int, offset: int) -> Sequence[Cylinder]:
        with self._uow() as uow:
            return uow.cylinders.search(q, status, customer_id, gas_type_id, limit, offset)

    def history(self, serial: str) -> tuple[Cylinder, Sequence[Movement]]:
        with self._uow() as uow:
            cyl = uow.cylinders.get_by_serial(rules.normalize_serial(serial))
            if not cyl:
                raise NotFound("Cilindro não encontrado")
            return cyl, uow.movements.for_cylinder(cyl.id)

    def hydro_due_date(self, cyl: Cylinder) -> date:
        return rules.hydro_due_date(cyl.last_hydro_test, self._hydro_years)

    # ---- movimentação ----
    def move(self, actor: Actor, data: MovementInput) -> Movement:
        with self._uow() as uow:
            op = str(uuid.uuid4())
            m = self._apply(uow, actor, data, op)
            uow.commit()
            uow.refresh(m)
            return m

    def exchange(self, actor: Actor, full_serial: str, empty_serial: str, customer_id: int,
                 is_loan: bool, document_ref: str | None, latitude: float | None,
                 longitude: float | None, notes: str | None) -> tuple[Movement, Movement]:
        """Troca: entrega um cheio e coleta um vazio do mesmo cliente em uma única transação."""
        with self._uow() as uow:
            delivered, collected = self._exchange_in(uow, actor, ExchangeInput(
                full_serial=full_serial, empty_serial=empty_serial, customer_id=customer_id, is_loan=is_loan,
                document_ref=document_ref, latitude=latitude, longitude=longitude, notes=notes))
            uow.commit()
            uow.refresh(delivered)
            uow.refresh(collected)
            return delivered, collected

    def _exchange_in(self, uow: UnitOfWork, actor: Actor, x: "ExchangeInput") -> tuple[Movement, Movement]:
        if rules.normalize_serial(x.full_serial) == rules.normalize_serial(x.empty_serial):
            raise ValidationFailed("Cilindro cheio e vazio devem ser diferentes")
        op = str(uuid.uuid4())
        common = dict(customer_id=x.customer_id, document_ref=x.document_ref, latitude=x.latitude,
                      longitude=x.longitude, notes=x.notes, client_occurred_at=x.client_occurred_at,
                      offline=x.offline)
        collected = self._apply(uow, actor, MovementInput(serial=x.empty_serial, type=MovementType.COLETA,
                                                          **common), op)
        delivered = self._apply(uow, actor, MovementInput(serial=x.full_serial, type=MovementType.ENTREGA,
                                                          is_loan=x.is_loan, **common), op)
        return delivered, collected

    def _apply(self, uow: UnitOfWork, actor: Actor, d: MovementInput, op: str) -> Movement:
        try:
            return self._apply_inner(uow, actor, d, op)
        except (ComplianceViolation, ValidationFailed, Forbidden, NotFound, Conflict) as e:
            DOMAIN_REJECTIONS.labels(code=e.code).inc()
            log.info("movement_rejected", extra={"serial": d.serial, "type": str(d.type),
                                                 "reason": e.message})
            raise
        except rules.InvalidTransition as e:
            DOMAIN_REJECTIONS.labels(code=e.code).inc()
            raise

    def _apply_inner(self, uow: UnitOfWork, actor: Actor, d: MovementInput, op: str) -> Movement:
        if not rules.can_perform(actor.role, d.type):
            raise Forbidden(f"Perfil {actor.role} não pode executar {d.type}")
        cyl = uow.cylinders.get_by_serial(rules.normalize_serial(d.serial))
        if not cyl:
            raise NotFound(f"Cilindro {d.serial} não encontrado")
        now = self._clock()
        today = now.date()
        current = CylinderStatus(cyl.status)
        target = rules.next_status(current, d.type)
        customer_id: int | None = None
        lot_id: int | None = None

        if d.type == MovementType.ENVASE:
            rules.ensure_hydro_valid(cyl.last_hydro_test, self._hydro_years, today)
            checklist = rules.normalize_checklist(d.checklist)
            rules.ensure_fill_checklist(GasCategory(cyl.gas_type.category), checklist)
            if cyl.gas_type.category == GasCategory.MEDICINAL and d.lot_id is None:
                raise ComplianceViolation("Envase de gás medicinal exige lote (rastreabilidade ANVISA)")
            if d.lot_id is not None:
                lot = uow.lots.get(d.lot_id)
                if not lot:
                    raise NotFound("Lote não encontrado")
                rules.ensure_lot_usable_for_fill(LotStatus(lot.status), lot.gas_type_id, cyl.gas_type_id,
                                                 lot.expiry_date, today)
                lot_id = lot.id
            cyl.current_lot_id = lot_id

        elif d.type == MovementType.ENTREGA:
            customer = self._active_customer(uow, d.customer_id)
            lot = cyl.current_lot
            rules.ensure_lot_releasable_for_delivery(
                GasCategory(cyl.gas_type.category),
                LotStatus(lot.status) if lot else None, lot.expiry_date if lot else None, today)
            customer_id = customer.id
            lot_id = cyl.current_lot_id
            cyl.current_customer_id = customer.id
            cyl.is_loan = d.is_loan

        elif d.type == MovementType.COLETA:
            customer = self._active_customer(uow, d.customer_id, allow_inactive=True)
            if cyl.current_customer_id != customer.id:
                raise Conflict("Cilindro não está registrado neste cliente")
            customer_id = customer.id
            lot_id = cyl.current_lot_id
            cyl.current_customer_id = None
            cyl.current_lot_id = None
            cyl.is_loan = False

        elif d.type == MovementType.ENVIO_MANUTENCAO:
            cyl.current_lot_id = None  # produto descartado/purgado na manutenção

        elif d.type == MovementType.RETORNO_MANUTENCAO:
            if d.new_hydro_test is not None:
                if d.new_hydro_test > today or d.new_hydro_test < cyl.last_hydro_test:
                    raise ValidationFailed("Data do novo teste hidrostático inválida")
                cyl.last_hydro_test = d.new_hydro_test

        elif d.type == MovementType.CONDENACAO:
            if not d.notes or len(d.notes.strip()) < 5:
                raise ValidationFailed("Condenação exige justificativa")
            cyl.current_lot_id = None

        if d.client_occurred_at is not None:
            rules.validate_client_time(d.client_occurred_at, now)
        checklist_json = (json.dumps(rules.normalize_checklist(d.checklist), sort_keys=True)
                          if d.type == MovementType.ENVASE and d.checklist is not None else None)
        cyl.status = target
        m = self._append(uow, cyl, d.type, current, target, op, actor, now, customer_id=customer_id,
                         lot_id=lot_id, is_loan=d.is_loan if d.type == MovementType.ENTREGA else False,
                         document_ref=d.document_ref, latitude=d.latitude, longitude=d.longitude,
                         notes=d.notes, client_occurred_at=d.client_occurred_at, offline=d.offline,
                         checklist=checklist_json)
        MOVEMENTS.labels(type=str(d.type)).inc()
        log.info("movement_recorded", extra={"cylinder": cyl.serial, "type": str(d.type),
                                             "from": str(current), "to": str(target),
                                             "operation_id": op, "user_id": actor.user_id})
        return m

    @staticmethod
    def _active_customer(uow: UnitOfWork, customer_id: int | None, allow_inactive: bool = False) -> Customer:
        if customer_id is None:
            raise ValidationFailed("Cliente é obrigatório para esta movimentação")
        c = uow.customers.get(customer_id)
        if not c:
            raise NotFound("Cliente não encontrado")
        if not c.active and not allow_inactive:
            raise ValidationFailed("Cliente inativo")
        return c

    @staticmethod
    def _append(uow: UnitOfWork, cyl: Cylinder, mtype: MovementType, from_s: CylinderStatus | None,
                to_s: CylinderStatus, op: str, actor: Actor, now: datetime, *,
                customer_id: int | None = None, lot_id: int | None = None, is_loan: bool = False,
                document_ref: str | None = None, latitude: float | None = None,
                longitude: float | None = None, notes: str | None = None,
                client_occurred_at: datetime | None = None, offline: bool = False,
                checklist: str | None = None) -> Movement:
        m = Movement(operation_id=op, cylinder_id=cyl.id, type=mtype, from_status=from_s, to_status=to_s,
                     customer_id=customer_id, lot_id=lot_id, user_id=actor.user_id, is_loan=is_loan,
                     document_ref=document_ref, latitude=latitude, longitude=longitude, notes=notes,
                     occurred_at=_naive_utc(now), prev_hash=cyl.last_hash,
                     client_occurred_at=_naive_utc(client_occurred_at) if client_occurred_at else None,
                     offline=offline, checklist=checklist)
        m.hash = rules.movement_hash(m.prev_hash, _hash_payload(m))
        cyl.last_hash = m.hash
        uow.movements.add(m)
        uow.flush()
        return m


class ReportService:
    def __init__(self, uow: UowFactory, hydro_years: int, alert_days: int, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._hydro_years = hydro_years
        self._alert_days = alert_days
        self._clock = clock

    def dashboard(self) -> dict[str, object]:
        today = self._clock().date()
        alert_until = today + timedelta(days=self._alert_days)
        # último teste <= alert_until - validade  =>  vence até alert_until
        cutoff = rules.add_years(alert_until, -self._hydro_years)
        with self._uow() as uow:
            due = uow.cylinders.hydro_due_before(cutoff)
            hydro = []
            for c in due:
                d = rules.hydro_due_date(c.last_hydro_test, self._hydro_years)
                hydro.append({"serial": c.serial, "gas": c.gas_type.code, "status": str(c.status),
                              "due_date": d.isoformat(), "expired": d < today,
                              "customer": c.current_customer.name if c.current_customer else None})
            quarantine = uow.lots.list(LotStatus.QUARENTENA, 100, 0)
            return {
                "by_status": uow.cylinders.count_by_status(),
                "by_gas": [{"gas": g, "status": s, "count": n} for g, s, n in uow.cylinders.count_by_gas_and_status()],
                "customer_balance": [{"customer_id": i, "customer": n, "cylinders": t, "loans": l}
                                     for i, n, t, l in uow.cylinders.balance_by_customer()],
                "hydro_alerts": hydro,
                "lots_in_quarantine": [{"id": l.id, "code": l.code, "gas": l.gas_type.code} for l in quarantine],
                "generated_at": self._clock().isoformat(),
            }

    def recent_movements(self, limit: int, offset: int, customer_id: int | None,
                         user_id: int | None) -> Sequence[Movement]:
        with self._uow() as uow:
            return uow.movements.recent(limit, offset, customer_id, user_id)

    def verify_audit_chain(self) -> dict[str, object]:
        broken: list[dict[str, object]] = []
        total = 0
        with self._uow() as uow:
            for cid in uow.movements.all_cylinder_ids():
                prev = GENESIS_HASH
                chain_ok = True
                for m in uow.movements.for_cylinder(cid):
                    total += 1
                    expected = rules.movement_hash(prev, _hash_payload(m))
                    if m.prev_hash != prev or m.hash != expected:
                        broken.append({"cylinder_id": cid, "movement_id": m.id})
                        chain_ok = False
                        break
                    prev = m.hash
                cyl = uow.cylinders.get(cid)
                if chain_ok and cyl is not None and cyl.last_hash != prev:
                    broken.append({"cylinder_id": cid, "movement_id": None})
            audit_prev = GENESIS_HASH
            audit_total = 0
            audit_broken: int | None = None
            for ev in uow.audit.all_ordered():
                audit_total += 1
                if ev.prev_hash != audit_prev or ev.hash != rules.movement_hash(audit_prev, _audit_payload(ev)):
                    audit_broken = ev.id
                    break
                audit_prev = ev.hash
        return {"ok": not broken and audit_broken is None, "movements_checked": total, "broken": broken,
                "audit_events_checked": audit_total, "audit_broken_event_id": audit_broken}

    def audit_events(self, entity: str | None, limit: int, offset: int) -> Sequence[AuditEvent]:
        with self._uow() as uow:
            return uow.audit.list(entity, limit, offset)


class SyncService:
    """Recebe operações feitas offline no celular. Cada item: transação própria + idempotência."""

    MAX_BATCH = 200

    def __init__(self, uow: UowFactory, cylinders: CylinderService, hydro_years: int,
                 clock: Clock = utcnow) -> None:
        self._uow = uow
        self._cyl = cylinders
        self._hydro_years = hydro_years
        self._clock = clock

    def process_batch(self, actor: Actor, items: Sequence[SyncItem]) -> list[dict[str, object]]:
        if len(items) > self.MAX_BATCH:
            raise ValidationFailed(f"Lote de sincronização acima de {self.MAX_BATCH} itens")
        # Ordem cronológica real do campo (ex.: entrega antes da coleta do mesmo cilindro).
        ordered = sorted(items, key=lambda i: (self._when(i) or self._clock()))
        return [self._process_one(actor, item) for item in ordered]

    @staticmethod
    def _when(item: SyncItem) -> datetime | None:
        src = item.movement or item.exchange
        return src.client_occurred_at if src else None

    def _process_one(self, actor: Actor, item: SyncItem) -> dict[str, object]:
        base: dict[str, object] = {"client_uuid": item.client_uuid}
        try:
            with self._uow() as uow:
                receipt = uow.receipts.get(item.client_uuid)
                if receipt is not None:
                    if receipt.user_id != actor.user_id:
                        raise Conflict("Identificador de operação já usado por outro usuário")
                    return {**base, "status": "duplicate",
                            "movement_ids": [int(x) for x in receipt.movement_ids.split(",")]}
                if item.kind == "movement" and item.movement is not None:
                    moves = [self._cyl._apply(uow, actor, item.movement, str(uuid.uuid4()))]
                elif item.kind == "exchange" and item.exchange is not None:
                    moves = list(self._cyl._exchange_in(uow, actor, item.exchange))
                else:
                    raise ValidationFailed("Tipo de item de sincronização inválido")
                uow.receipts.add(SyncReceipt(client_uuid=item.client_uuid, user_id=actor.user_id,
                                             kind=item.kind, movement_ids=",".join(str(m.id) for m in moves),
                                             created_at=self._clock()))
                uow.commit()
                log.info("sync_item_applied", extra={"client_uuid": item.client_uuid, "kind": item.kind})
                return {**base, "status": "ok", "movement_ids": [m.id for m in moves]}
        except ConcurrencyConflict as e:
            return {**base, "status": "rejected", "error": e.code, "message": e.message, "retryable": True}
        except DomainError as e:
            return {**base, "status": "rejected", "error": e.code, "message": e.message, "retryable": False}

    def snapshot(self, max_cylinders: int = 20000) -> dict[str, object]:
        """Dados de referência para o app operar offline (pré-validação local)."""
        today = self._clock().date()
        with self._uow() as uow:
            lots = [l for l in uow.lots.list(None, 500, 0) if l.status != LotStatus.REPROVADO]
            return {
                "server_time": self._clock().isoformat(),
                "checklist": rules.FILL_CHECKLIST,
                "gas_types": [{"id": g.id, "code": g.code, "name": g.name, "category": str(g.category)}
                              for g in uow.gas_types.list()],
                "customers": [{"id": c.id, "name": c.name, "document": c.document}
                              for c in uow.customers.search(None, 5000, 0) if c.active],
                "lots": [{"id": l.id, "code": l.code, "gas_type_id": l.gas_type_id, "status": str(l.status),
                          "expiry_date": l.expiry_date.isoformat()} for l in lots],
                "cylinders": [{
                    "serial": c.serial, "status": str(c.status), "gas_type_id": c.gas_type_id,
                    "category": str(c.gas_type.category), "customer_id": c.current_customer_id,
                    "lot_id": c.current_lot_id,
                    "hydro_expired": rules.hydro_due_date(c.last_hydro_test, self._hydro_years) < today,
                } for c in uow.cylinders.all_active(max_cylinders)],
            }
