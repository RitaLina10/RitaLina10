"""Casos de uso. Cada método = uma transação (Unit of Work)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Sequence

from app.application.ports import UnitOfWork
from app.application.security import DUMMY_HASH, hash_password, verify_password
from app.domain import rules
from app.domain.errors import ComplianceViolation, Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.rules import (
    GENESIS_HASH, CylinderStatus, GasCategory, LotStatus, MovementType, Role,
)
from app.infra.orm import Customer, Cylinder, GasType, Lot, Movement, User
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


def _require_role(actor: Actor, *roles: Role) -> None:
    if actor.role != Role.ADMIN and actor.role not in roles:
        raise Forbidden("Perfil sem permissão para esta operação")


def _hash_payload(m: Movement) -> dict[str, object]:
    return {
        "operation_id": m.operation_id, "cylinder_id": m.cylinder_id, "type": str(m.type),
        "from": str(m.from_status) if m.from_status else None, "to": str(m.to_status),
        "customer_id": m.customer_id, "lot_id": m.lot_id, "user_id": m.user_id,
        "is_loan": bool(m.is_loan), "document_ref": m.document_ref,
        "lat": None if m.latitude is None else f"{float(m.latitude):.6f}",
        "lon": None if m.longitude is None else f"{float(m.longitude):.6f}",
        "notes": m.notes, "occurred_at": _naive_utc(m.occurred_at).isoformat(timespec="microseconds"),
    }


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
            uow.commit()
            log.info("user_created", extra={"user_id": user.id, "role": str(role)})
            return user

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
            uow.commit()
            return g

    # ---- clientes ----
    def create_customer(self, actor: Actor, name: str, document: str, phone: str | None,
                        address: str | None, is_health_facility: bool) -> Customer:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        doc = rules.validate_document(document)
        with self._uow() as uow:
            if uow.customers.get_by_document(doc):
                raise Conflict("Cliente com este CPF/CNPJ já existe")
            c = Customer(name=name.strip(), document=doc, phone=phone, address=address,
                         is_health_facility=is_health_facility, active=True, created_at=self._clock())
            uow.customers.add(c)
            uow.commit()
            return c

    def update_customer(self, actor: Actor, customer_id: int, **fields: object) -> Customer:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        allowed = {"name", "phone", "address", "is_health_facility", "active"}
        with self._uow() as uow:
            c = uow.customers.get(customer_id)
            if not c:
                raise NotFound("Cliente não encontrado")
            for k, v in fields.items():
                if k in allowed and v is not None:
                    setattr(c, k, v.strip() if isinstance(v, str) else v)
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
            uow.commit()
            uow.refresh(lot)
            return lot

    def decide(self, actor: Actor, lot_id: int, approve: bool, notes: str | None) -> Lot:
        """Liberação pelo responsável técnico (GESTOR). Exige laudo para gás medicinal."""
        _require_role(actor, Role.GESTOR)
        with self._uow() as uow:
            lot = uow.lots.get(lot_id)
            if not lot:
                raise NotFound("Lote não encontrado")
            if lot.status != LotStatus.QUARENTENA:
                raise Conflict(f"Lote já decidido ({lot.status})")
            if approve and lot.gas_type.category == GasCategory.MEDICINAL and not lot.analysis_report:
                raise ComplianceViolation("Lote medicinal exige número do laudo de análise para aprovação")
            lot.status = LotStatus.APROVADO if approve else LotStatus.REPROVADO
            lot.released_by_id = actor.user_id
            lot.released_at = self._clock()
            lot.release_notes = notes
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
        if rules.normalize_serial(full_serial) == rules.normalize_serial(empty_serial):
            raise ValidationFailed("Cilindro cheio e vazio devem ser diferentes")
        op = str(uuid.uuid4())
        common = dict(customer_id=customer_id, document_ref=document_ref, latitude=latitude,
                      longitude=longitude, notes=notes)
        with self._uow() as uow:
            collected = self._apply(uow, actor, MovementInput(serial=empty_serial, type=MovementType.COLETA,
                                                              **common), op)
            delivered = self._apply(uow, actor, MovementInput(serial=full_serial, type=MovementType.ENTREGA,
                                                              is_loan=is_loan, **common), op)
            uow.commit()
            uow.refresh(delivered)
            uow.refresh(collected)
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

        cyl.status = target
        m = self._append(uow, cyl, d.type, current, target, op, actor, now, customer_id=customer_id,
                         lot_id=lot_id, is_loan=d.is_loan if d.type == MovementType.ENTREGA else False,
                         document_ref=d.document_ref, latitude=d.latitude, longitude=d.longitude,
                         notes=d.notes)
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
                longitude: float | None = None, notes: str | None = None) -> Movement:
        m = Movement(operation_id=op, cylinder_id=cyl.id, type=mtype, from_status=from_s, to_status=to_s,
                     customer_id=customer_id, lot_id=lot_id, user_id=actor.user_id, is_loan=is_loan,
                     document_ref=document_ref, latitude=latitude, longitude=longitude, notes=notes,
                     occurred_at=_naive_utc(now), prev_hash=cyl.last_hash)
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
        return {"ok": not broken, "movements_checked": total, "broken": broken}
