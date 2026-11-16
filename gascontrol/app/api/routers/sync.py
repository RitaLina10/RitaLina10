"""Sincronização do app de campo offline."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Container, current_actor, get_container
from app.api.routers.cylinders import QR_PREFIX, to_movement_input
from app.api.schemas import SyncBatchIn, SyncExchangeItem, SyncResultOut
from app.application.services import Actor, ExchangeInput, SyncItem

router = APIRouter(prefix="/api/sync", tags=["sincronização"])


@router.get("/snapshot")
def snapshot(_: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.sync.snapshot()


@router.post("/batch", response_model=list[SyncResultOut])
def batch(body: SyncBatchIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    items: list[SyncItem] = []
    for it in body.items:
        if isinstance(it, SyncExchangeItem):
            p = it.payload
            items.append(SyncItem(client_uuid=it.client_uuid.lower(), kind="exchange", exchange=ExchangeInput(
                full_serial=p.full_serial.removeprefix(QR_PREFIX), empty_serial=p.empty_serial.removeprefix(QR_PREFIX),
                customer_id=p.customer_id, is_loan=p.is_loan, document_ref=p.document_ref, latitude=p.latitude,
                longitude=p.longitude, notes=p.notes, client_occurred_at=it.occurred_at, offline=True)))
        else:
            items.append(SyncItem(client_uuid=it.client_uuid.lower(), kind="movement",
                                  movement=to_movement_input(it.payload, it.occurred_at, offline=True)))
    return c.sync.process_batch(actor, items)
