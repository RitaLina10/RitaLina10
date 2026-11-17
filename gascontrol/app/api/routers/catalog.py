from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status as http

from app.api.deps import Container, current_actor, get_container
from app.api.schemas import (
    CustomerIn, CustomerOut, CustomerPatch, GasTypeIn, GasTypeOut, LotDecisionIn, LotIn, LotOut,
    LotTraceOut, MovementOut,
)
from app.application.services import Actor
from app.domain.errors import Forbidden
from app.domain.rules import LotStatus

router = APIRouter(prefix="/api", tags=["catálogo"])


@router.get("/gas-types", response_model=list[GasTypeOut])
def gas_types(_: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.catalog.list_gas_types()


@router.post("/gas-types", response_model=GasTypeOut, status_code=201)
def create_gas_type(body: GasTypeIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.catalog.create_gas_type(actor, body.code, body.name, body.category)


@router.get("/customers", response_model=list[CustomerOut])
def customers(q: str | None = Query(default=None, max_length=60), limit: int = Query(50, ge=1, le=200),
              offset: int = Query(0, ge=0), _: Actor = Depends(current_actor),
              c: Container = Depends(get_container)):
    return c.catalog.search_customers(q, limit, offset)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def customer(customer_id: int, _: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.catalog.get_customer(customer_id)


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    extra = body.model_dump(exclude={"name", "document", "phone", "address", "is_health_facility"})
    return c.catalog.create_customer(actor, body.name, body.document, body.phone, body.address,
                                     body.is_health_facility, **extra)


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerPatch, actor: Actor = Depends(current_actor),
                    c: Container = Depends(get_container)):
    return c.catalog.update_customer(actor, customer_id, **body.model_dump(exclude_unset=True))


@router.get("/lots", response_model=list[LotOut])
def lots(status: LotStatus | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
         _: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.lots.list(status, limit, offset)


@router.post("/lots", response_model=LotOut, status_code=201)
def create_lot(body: LotIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.lots.create(actor, body.code, body.gas_type_id, body.production_date, body.expiry_date,
                         body.purity_percent, body.analysis_report)


@router.post("/lots/{lot_id}/decision", response_model=LotOut)
def decide_lot(lot_id: int, body: LotDecisionIn, actor: Actor = Depends(current_actor),
               c: Container = Depends(get_container)):
    key = f"sign|{actor.user_id}"
    if c.throttle.is_locked(key):
        raise HTTPException(http.HTTP_429_TOO_MANY_REQUESTS, "Assinatura bloqueada temporariamente")
    try:
        lot = c.lots.decide(actor, lot_id, body.approve, body.notes, body.signature_password)
    except Forbidden:
        c.throttle.fail(key)
        raise
    c.throttle.success(key)
    return lot


@router.get("/lots/{lot_id}/trace", response_model=LotTraceOut)
def trace_lot(lot_id: int, _: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    lot, movements = c.lots.trace(lot_id)
    return LotTraceOut(lot=LotOut.model_validate(lot),
                       movements=[MovementOut.model_validate(m) for m in movements])
