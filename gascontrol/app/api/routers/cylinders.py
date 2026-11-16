from __future__ import annotations

import io

import qrcode
from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import Container, current_actor, get_container, require
from app.api.schemas import (
    CylinderHistoryOut, CylinderIn, CylinderOut, ExchangeIn, MovementIn, MovementOut,
)
from app.application.services import Actor, MovementInput
from app.domain.rules import CylinderStatus, Role

router = APIRouter(prefix="/api", tags=["cilindros"])

QR_PREFIX = "GC1:"  # payload opaco: não é URL, evita phishing via QR adulterado


def _out(c: Container, cyl) -> CylinderOut:  # noqa: ANN001
    out = CylinderOut.model_validate(cyl)
    out.hydro_due_date = c.cylinders.hydro_due_date(cyl)
    return out


@router.get("/cylinders", response_model=list[CylinderOut])
def search(q: str | None = Query(default=None, max_length=40), status: CylinderStatus | None = None,
           customer_id: int | None = Query(default=None, gt=0), gas_type_id: int | None = Query(default=None, gt=0),
           limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
           _: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return [_out(c, x) for x in c.cylinders.search(q, status, customer_id, gas_type_id, limit, offset)]


@router.post("/cylinders", response_model=CylinderOut, status_code=201)
def register(body: CylinderIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    cyl = c.cylinders.register(actor, body.serial, body.gas_type_id, body.capacity_liters, body.last_hydro_test,
                               body.manufacturer, body.manufacture_date, body.owned_by_company)
    return _out(c, cyl)


@router.get("/cylinders/{serial}", response_model=CylinderOut)
def get_one(serial: str, _: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return _out(c, c.cylinders.get_by_serial(serial.removeprefix(QR_PREFIX)))


@router.get("/cylinders/{serial}/history", response_model=CylinderHistoryOut)
def history(serial: str, _: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    cyl, movements = c.cylinders.history(serial.removeprefix(QR_PREFIX))
    return CylinderHistoryOut(cylinder=_out(c, cyl), movements=[MovementOut.model_validate(m) for m in movements])


@router.get("/cylinders/{serial}/qr.png", response_class=Response)
def qr(serial: str, _: Actor = Depends(current_actor), c: Container = Depends(get_container)) -> Response:
    cyl = c.cylinders.get_by_serial(serial)
    img = qrcode.make(f"{QR_PREFIX}{cyl.serial}", box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400",
                             "Content-Disposition": f'inline; filename="{cyl.serial}.png"'})


@router.post("/movements", response_model=MovementOut, status_code=201)
def move(body: MovementIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    data = MovementInput(**{**body.model_dump(), "serial": body.serial.removeprefix(QR_PREFIX)})
    return c.cylinders.move(actor, data)


@router.post("/movements/exchange", response_model=list[MovementOut], status_code=201)
def exchange(body: ExchangeIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    delivered, collected = c.cylinders.exchange(
        actor, body.full_serial.removeprefix(QR_PREFIX), body.empty_serial.removeprefix(QR_PREFIX),
        body.customer_id, body.is_loan, body.document_ref, body.latitude, body.longitude, body.notes)
    return [delivered, collected]


@router.get("/movements", response_model=list[MovementOut])
def recent(customer_id: int | None = Query(default=None, gt=0), mine: bool = False,
           limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
           actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    # Motorista só enxerga as próprias movimentações (escopo de acesso).
    user_id = actor.user_id if (mine or actor.role == Role.MOTORISTA) else None
    return c.reports.recent_movements(limit, offset, customer_id, user_id)


@router.get("/dashboard")
def dashboard(_: Actor = Depends(require(Role.GESTOR, Role.OPERADOR)), c: Container = Depends(get_container)):
    return c.reports.dashboard()


@router.get("/audit/verify")
def verify(_: Actor = Depends(require(Role.GESTOR)), c: Container = Depends(get_container)):
    return c.reports.verify_audit_chain()
