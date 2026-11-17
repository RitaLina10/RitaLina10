"""NF-e: perfis fiscais por gás, rascunhos, emissão, consulta e cancelamento."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status as http

from app.api.deps import Container, get_container, require
from app.api.schemas import (
    CancelInvoiceIn, FiscalProfileIn, FiscalProfileOut, FromOperationIn, InvoiceIn, InvoiceItemIn, InvoiceOut,
    InvoiceUpdateIn,
)
from app.application.fiscal_service import ItemInput, ProfileInput
from app.application.services import Actor
from app.domain.errors import Forbidden
from app.domain.fiscal import InvoiceStatus
from app.domain.rules import Role

router = APIRouter(prefix="/api/fiscal", tags=["fiscal"])
staff = require(Role.GESTOR, Role.OPERADOR)


def _items(items: list[InvoiceItemIn]) -> list[ItemInput]:
    return [ItemInput(gas_type_id=i.gas_type_id, quantity=i.quantity, unit_price=i.unit_price,
                      description=i.description) for i in items]


@router.get("/config")
def config(_: Actor = Depends(staff), c: Container = Depends(get_container)):
    s = c.settings
    return {"provider": c.fiscal.provider, "environment": s.focus_environment if s.fiscal_provider != "none" else None,
            "emitter_uf": s.emitter_uf, "emitter_configured": bool(s.emitter_cnpj and s.emitter_uf),
            "cancel_hours": s.fiscal_cancel_hours}


@router.get("/profiles", response_model=list[FiscalProfileOut])
def profiles(_: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.list_profiles()


@router.put("/profiles/{gas_type_id}", response_model=FiscalProfileOut)
def upsert_profile(gas_type_id: int, body: FiscalProfileIn, actor: Actor = Depends(staff),
                   c: Container = Depends(get_container)):
    return c.fiscal.upsert_profile(actor, ProfileInput(gas_type_id=gas_type_id, **body.model_dump()))


@router.get("/invoices", response_model=list[InvoiceOut])
def invoices(status: InvoiceStatus | None = None, customer_id: int | None = Query(default=None, gt=0),
             limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
             _: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.search(status, customer_id, limit, offset)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create(body: InvoiceIn, actor: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.create_draft(actor, body.customer_id, body.nature, _items(body.items), body.notes)


@router.post("/invoices/from-operation", response_model=InvoiceOut, status_code=201)
def from_operation(body: FromOperationIn, actor: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.draft_from_operation(actor, body.operation_id.lower())


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_one(invoice_id: int, _: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.get(invoice_id)


@router.put("/invoices/{invoice_id}", response_model=InvoiceOut)
def update(invoice_id: int, body: InvoiceUpdateIn, actor: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.update_draft(actor, invoice_id, body.nature, _items(body.items), body.notes)


@router.post("/invoices/{invoice_id}/emit", response_model=InvoiceOut)
def emit(invoice_id: int, actor: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.emit(actor, invoice_id)


@router.post("/invoices/{invoice_id}/refresh", response_model=InvoiceOut)
def refresh(invoice_id: int, actor: Actor = Depends(staff), c: Container = Depends(get_container)):
    return c.fiscal.refresh(actor, invoice_id)


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceOut)
def cancel(invoice_id: int, body: CancelInvoiceIn, actor: Actor = Depends(staff), c: Container = Depends(get_container)):
    key = f"sign|{actor.user_id}"
    if c.throttle.is_locked(key):
        raise HTTPException(http.HTTP_429_TOO_MANY_REQUESTS, "Assinatura bloqueada temporariamente")
    try:
        inv = c.fiscal.cancel(actor, invoice_id, body.justification, body.signature_password)
    except Forbidden:
        c.throttle.fail(key)
        raise
    c.throttle.success(key)
    return inv
