"""Casos de uso fiscais: perfis por gás, rascunho de NF-e, emissão, consulta e cancelamento."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.application.ports import FiscalDocument, FiscalGateway, FiscalLine, FiscalParty, FiscalResult
from app.application.services import Actor, Clock, UowFactory, _audit, _require_role, _verify_signer, utcnow
from app.domain import fiscal as f
from app.domain.errors import Conflict, ExternalServiceError, NotFound, ValidationFailed
from app.domain.fiscal import InvoiceStatus
from app.domain.rules import MovementType, Role
from app.infra.orm import FiscalProfile, Invoice, InvoiceItem

log = logging.getLogger("gascontrol.fiscal")


@dataclass(frozen=True)
class ItemInput:
    gas_type_id: int
    quantity: Decimal
    unit_price: Decimal | None = None
    description: str | None = None


@dataclass(frozen=True)
class ProfileInput:
    gas_type_id: int
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


class FiscalService:
    def __init__(self, uow: UowFactory, gateway: FiscalGateway, emitter_cnpj: str | None,
                 emitter_uf: str | None, cancel_hours: int, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._gw = gateway
        self._cnpj = emitter_cnpj
        self._uf = emitter_uf
        self._cancel_hours = cancel_hours
        self._clock = clock

    # ---------- perfis fiscais ----------
    def upsert_profile(self, actor: Actor, p: ProfileInput) -> FiscalProfile:
        _require_role(actor, Role.GESTOR)
        norm = f.validate_fiscal_profile(p.ncm, p.cfop_internal, p.cfop_interstate, p.unit, p.icms_cst,
                                         p.pis_cst, p.cofins_cst, p.origin)
        if not Decimal(0) <= p.icms_rate <= Decimal(100):
            raise ValidationFailed("Alíquota de ICMS deve estar entre 0 e 100")
        now = self._clock()
        with self._uow() as uow:
            if not uow.gas_types.get(p.gas_type_id):
                raise NotFound("Tipo de gás não encontrado")
            prof = uow.fiscal.get_profile(p.gas_type_id)
            data = dict(description=p.description.strip(), ncm=norm["ncm"], cfop_internal=p.cfop_internal,
                        cfop_interstate=p.cfop_interstate, unit=p.unit, icms_cst=p.icms_cst, icms_rate=p.icms_rate,
                        pis_cst=p.pis_cst, cofins_cst=p.cofins_cst, origin=p.origin,
                        default_price=p.default_price, updated_at=now)
            if prof is None:
                prof = FiscalProfile(gas_type_id=p.gas_type_id, **data)
                uow.fiscal.add_profile(prof)
            else:
                for k, v in data.items():
                    setattr(prof, k, v)
            _audit(uow, actor.user_id, "PERFIL_FISCAL", "gas", p.gas_type_id,
                   {k: v for k, v in data.items() if k != "updated_at"}, now)
            uow.commit()
            uow.refresh(prof)
            return prof

    def list_profiles(self) -> Sequence[FiscalProfile]:
        with self._uow() as uow:
            return uow.fiscal.list_profiles()

    # ---------- rascunho ----------
    def create_draft(self, actor: Actor, customer_id: int, nature: str, items: Sequence[ItemInput],
                     notes: str | None, operation_id: str | None = None) -> Invoice:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        now = self._clock()
        with self._uow() as uow:
            customer = uow.customers.get(customer_id)
            if not customer or not customer.active:
                raise NotFound("Cliente não encontrado ou inativo")
            inv = Invoice(ref=f"gc-{uuid.uuid4().hex[:24]}", customer_id=customer.id, status=InvoiceStatus.RASCUNHO,
                          nature=nature.strip(), operation_id=operation_id, notes=notes, total=Decimal(0),
                          created_by_id=actor.user_id, created_at=now, updated_at=now)
            self._set_items(uow, inv, items)
            uow.fiscal.add(inv)
            uow.flush()
            _audit(uow, actor.user_id, "RASCUNHO", "nota", inv.id,
                   {"customer_id": customer.id, "total": str(inv.total), "operation_id": operation_id}, now)
            uow.commit()
            uow.refresh(inv)
            return inv

    def draft_from_operation(self, actor: Actor, operation_id: str) -> Invoice:
        """Fatura uma entrega/troca: um item por gás, quantidade = nº de cilindros entregues (editável)."""
        with self._uow() as uow:
            moves = [m for m in uow.movements.by_operation(operation_id) if m.type == MovementType.ENTREGA]
            if not moves:
                raise NotFound("Operação sem entregas")
            if uow.fiscal.by_operation(operation_id):
                raise Conflict("Esta entrega já possui nota fiscal")
            customer_id = moves[0].customer_id
            counts: dict[int, int] = {}
            for m in moves:
                counts[m.cylinder.gas_type_id] = counts.get(m.cylinder.gas_type_id, 0) + 1
            serials = ", ".join(m.cylinder.serial for m in moves)
            refs = {m.document_ref for m in moves if m.document_ref}
        notes = f"Cilindros: {serials}" + (f". Romaneio: {', '.join(sorted(refs))}" if refs else "")
        return self.create_draft(actor, customer_id, "Venda de mercadoria",
                                 [ItemInput(gas_type_id=g, quantity=Decimal(n)) for g, n in counts.items()],
                                 notes, operation_id)

    def update_draft(self, actor: Actor, invoice_id: int, nature: str, items: Sequence[ItemInput],
                     notes: str | None) -> Invoice:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        now = self._clock()
        with self._uow() as uow:
            inv = self._get(uow, invoice_id)
            f.ensure_editable(InvoiceStatus(inv.status))
            inv.nature = nature.strip()
            inv.notes = notes
            inv.items.clear()
            uow.flush()
            self._set_items(uow, inv, items)
            inv.updated_at = now
            _audit(uow, actor.user_id, "ALTERAR", "nota", inv.id, {"total": str(inv.total)}, now)
            uow.commit()
            uow.refresh(inv)
            return inv

    def _set_items(self, uow, inv: Invoice, items: Sequence[ItemInput]) -> None:  # noqa: ANN001
        if not items:
            raise ValidationFailed("Informe ao menos um item")
        total = Decimal(0)
        for it in items:
            prof = uow.fiscal.get_profile(it.gas_type_id)
            if not prof:
                raise ValidationFailed("Gás sem perfil fiscal cadastrado (Fiscal → Perfis)")
            price = it.unit_price if it.unit_price is not None else (
                Decimal(str(prof.default_price)) if prof.default_price is not None else None)
            if price is None:
                raise ValidationFailed(f"Informe o preço de {prof.description}")
            qty = Decimal(str(it.quantity))
            line = f.line_total(qty, Decimal(str(price)))
            inv.items.append(InvoiceItem(gas_type_id=it.gas_type_id,
                                         description=(it.description or prof.description).strip()[:120],
                                         quantity=qty, unit_price=Decimal(str(price)), total=line))
            total += line
        inv.total = f.money(total)

    # ---------- emissão ----------
    def emit(self, actor: Actor, invoice_id: int) -> Invoice:
        _require_role(actor, Role.GESTOR)
        if not self._cnpj or not self._uf:
            raise ValidationFailed("Configure EMITTER_CNPJ e EMITTER_UF")
        now = self._clock()
        with self._uow() as uow:
            inv = self._get(uow, invoice_id)
            previous = InvoiceStatus(inv.status)
            f.ensure_can_emit(previous, len(inv.items))
            c = inv.customer
            f.ensure_customer_ready(c.street, c.street_number, c.district, c.city, c.uf, c.cep)
            if previous == InvoiceStatus.REJEITADA:
                inv.ref = f"gc-{uuid.uuid4().hex[:24]}"  # ref rejeitada é definitiva no emissor; nova tentativa = nova ref
            doc = self._document(uow, inv, now)
            # Persiste PROCESSANDO antes de chamar o emissor: se o processo cair no meio, a nota
            # fica rastreável e é resolvida pela consulta por "ref".
            inv.status = InvoiceStatus.PROCESSANDO
            inv.updated_at = now
            _audit(uow, actor.user_id, "EMITIR", "nota", inv.id, {"ref": inv.ref, "total": str(inv.total)}, now)
            uow.commit()
        try:
            result = self._gw.emit(doc)
        except ExternalServiceError:
            self._revert(invoice_id, previous)
            raise
        return self._apply(invoice_id, result, actor.user_id)

    def refresh(self, actor: Actor | None, invoice_id: int) -> Invoice:
        if actor is not None:
            _require_role(actor, Role.GESTOR, Role.OPERADOR)
        with self._uow() as uow:
            inv = self._get(uow, invoice_id)
            ref, status = inv.ref, InvoiceStatus(inv.status)
        if status not in (InvoiceStatus.PROCESSANDO, InvoiceStatus.AUTORIZADA):
            return inv
        return self._apply(invoice_id, self._gw.query(ref), actor.user_id if actor else None)

    def cancel(self, actor: Actor, invoice_id: int, justification: str, password: str) -> Invoice:
        _require_role(actor, Role.GESTOR)
        now = self._clock()
        with self._uow() as uow:
            _verify_signer(uow, actor, password)
            inv = self._get(uow, invoice_id)
            authorized_at = inv.authorized_at
            if authorized_at is not None and authorized_at.tzinfo is None:
                authorized_at = authorized_at.replace(tzinfo=now.tzinfo)
            f.ensure_can_cancel(InvoiceStatus(inv.status), authorized_at, now, justification, self._cancel_hours)
            ref = inv.ref
            _audit(uow, actor.user_id, "CANCELAR_SOLICITADO", "nota", inv.id, {"justificativa": justification}, now)
            inv.cancel_justification = justification.strip()
            uow.commit()
        return self._apply(invoice_id, self._gw.cancel(ref, justification.strip()), actor.user_id)

    def poll_processing(self, limit: int = 20) -> int:
        """Usado pela tarefa periódica: resolve notas em PROCESSANDO."""
        with self._uow() as uow:
            ids = list(uow.fiscal.processing_ids(limit))
        done = 0
        for invoice_id in ids:
            try:
                self.refresh(None, invoice_id)
                done += 1
            except ExternalServiceError:
                log.warning("fiscal_poll_unavailable")
                break
        return done

    # ---------- consulta ----------
    def get(self, invoice_id: int) -> Invoice:
        with self._uow() as uow:
            return self._get(uow, invoice_id)

    def search(self, status: InvoiceStatus | None, customer_id: int | None, limit: int, offset: int) -> Sequence[Invoice]:
        with self._uow() as uow:
            return uow.fiscal.search(status, customer_id, limit, offset)

    def summary(self) -> dict[str, int]:
        with self._uow() as uow:
            return uow.fiscal.count_by_status()

    @property
    def provider(self) -> str:
        return self._gw.name

    # ---------- internos ----------
    def _document(self, uow, inv: Invoice, now) -> FiscalDocument:  # noqa: ANN001
        c = inv.customer
        lines = []
        for n, it in enumerate(inv.items, start=1):
            prof = uow.fiscal.get_profile(it.gas_type_id)
            if not prof:
                raise ValidationFailed(f"Gás {it.gas_type.code} sem perfil fiscal")
            lines.append(FiscalLine(
                number=n, code=it.gas_type.code, description=it.description, ncm=prof.ncm,
                cfop=f.cfop_for(self._uf, c.uf, prof.cfop_internal, prof.cfop_interstate), unit=prof.unit,
                quantity=Decimal(str(it.quantity)), unit_price=Decimal(str(it.unit_price)),
                total=Decimal(str(it.total)), icms_cst=prof.icms_cst, icms_rate=Decimal(str(prof.icms_rate or 0)),
                pis_cst=prof.pis_cst, cofins_cst=prof.cofins_cst, origin=prof.origin))
        party = FiscalParty(document=c.document, name=c.name, state_registration=c.state_registration,
                            email=c.email, street=c.street, number=c.street_number, complement=c.complement,
                            district=c.district, city=c.city, uf=c.uf, cep=f.digits(c.cep))
        return FiscalDocument(ref=inv.ref, nature=inv.nature, issued_at=now, customer=party,
                              lines=tuple(lines), total=Decimal(str(inv.total)), notes=inv.notes)

    def _revert(self, invoice_id: int, status: InvoiceStatus) -> None:
        with self._uow() as uow:
            inv = self._get(uow, invoice_id)
            inv.status = status
            inv.provider_message = "Emissor indisponível; nada foi enviado"
            uow.commit()

    def _apply(self, invoice_id: int, r: FiscalResult, user_id: int | None) -> Invoice:
        now = self._clock()
        with self._uow() as uow:
            inv = self._get(uow, invoice_id)
            before = InvoiceStatus(inv.status)
            if r.status == "authorized":
                if before != InvoiceStatus.AUTORIZADA:
                    inv.authorized_at = now
                inv.status = InvoiceStatus.AUTORIZADA
            elif r.status == "rejected":
                inv.status = InvoiceStatus.REJEITADA
            elif r.status == "cancelled":
                inv.status = InvoiceStatus.CANCELADA
            elif r.status == "not_found" and before == InvoiceStatus.PROCESSANDO:
                inv.status = InvoiceStatus.RASCUNHO  # nunca chegou ao emissor: pode reenviar (mesma ref)
            inv.access_key = r.access_key or inv.access_key
            inv.number = r.number or inv.number
            inv.series = r.series or inv.series
            inv.danfe_url = r.danfe_url or inv.danfe_url
            inv.xml_url = r.xml_url or inv.xml_url
            inv.provider_message = r.message
            inv.updated_at = now
            if inv.status != before:
                _audit(uow, user_id, "STATUS_" + str(inv.status), "nota", inv.id,
                       {"de": str(before), "chave": inv.access_key, "numero": inv.number, "mensagem": r.message}, now)
                log.info("invoice_status", extra={"invoice_id": inv.id, "from": str(before), "to": str(inv.status)})
            uow.commit()
            uow.refresh(inv)
            return inv

    @staticmethod
    def _get(uow, invoice_id: int) -> Invoice:  # noqa: ANN001
        inv = uow.fiscal.get(invoice_id)
        if not inv:
            raise NotFound("Nota não encontrada")
        return inv
