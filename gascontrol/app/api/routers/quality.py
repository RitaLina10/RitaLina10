"""Qualidade: reclamações, desvios, não conformidades, eventos adversos e CAPA."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status as http

from app.api.deps import Container, current_actor, get_container
from app.api.schemas import (
    ActionIn, EvidenceIn, InvestigateIn, OccurrenceIn, OccurrenceOut, ReasonIn, RootCauseIn, SignatureIn,
    SignedTextIn,
)
from app.application.services import Actor
from app.domain.errors import Forbidden

router = APIRouter(prefix="/api/quality", tags=["qualidade"])


def _signed(c: Container, actor: Actor, fn):  # noqa: ANN001, ANN202
    """Aplica o mesmo bloqueio por tentativas da liberação de lote às assinaturas de qualidade."""
    key = f"sign|{actor.user_id}"
    if c.throttle.is_locked(key):
        raise HTTPException(http.HTTP_429_TOO_MANY_REQUESTS, "Assinatura bloqueada temporariamente")
    try:
        result = fn()
    except Forbidden:
        c.throttle.fail(key)
        raise
    c.throttle.success(key)
    return result


@router.get("/occurrences", response_model=list[OccurrenceOut])
def search(status: str | None = Query(default=None, pattern=r"^[A-Z_]{4,25}$"),
           lot_id: int | None = Query(default=None, gt=0), limit: int = Query(100, ge=1, le=500),
           offset: int = Query(0, ge=0), actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.quality.search(actor, status, lot_id, limit, offset)


@router.post("/occurrences", response_model=OccurrenceOut, status_code=201)
def open_occurrence(body: OccurrenceIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    serial = body.serial.removeprefix("GC1:") if body.serial else None
    return c.quality.open(actor, body.kind, body.severity, body.title, body.description, body.customer_id,
                          body.lot_id, serial)


@router.get("/occurrences/{occurrence_id}", response_model=OccurrenceOut)
def get_one(occurrence_id: int, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.quality.get(actor, occurrence_id)


@router.post("/occurrences/{occurrence_id}/investigate", response_model=OccurrenceOut)
def investigate(occurrence_id: int, body: InvestigateIn, actor: Actor = Depends(current_actor),
                c: Container = Depends(get_container)):
    return c.quality.start_investigation(actor, occurrence_id, body.owner_id)


@router.put("/occurrences/{occurrence_id}/root-cause", response_model=OccurrenceOut)
def root_cause(occurrence_id: int, body: RootCauseIn, actor: Actor = Depends(current_actor),
               c: Container = Depends(get_container)):
    return c.quality.set_root_cause(actor, occurrence_id, body.root_cause)


@router.post("/occurrences/{occurrence_id}/actions", response_model=OccurrenceOut, status_code=201)
def add_action(occurrence_id: int, body: ActionIn, actor: Actor = Depends(current_actor),
               c: Container = Depends(get_container)):
    return c.quality.add_action(actor, occurrence_id, body.kind, body.description, body.responsible_id, body.due_date)


@router.post("/actions/{action_id}/complete", response_model=OccurrenceOut)
def complete_action(action_id: int, body: EvidenceIn, actor: Actor = Depends(current_actor),
                    c: Container = Depends(get_container)):
    return c.quality.complete_action(actor, action_id, body.evidence)


@router.post("/occurrences/{occurrence_id}/effectiveness", response_model=OccurrenceOut)
def to_effectiveness(occurrence_id: int, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.quality.submit_for_effectiveness(actor, occurrence_id)


@router.post("/occurrences/{occurrence_id}/reopen", response_model=OccurrenceOut)
def reopen(occurrence_id: int, body: ReasonIn, actor: Actor = Depends(current_actor),
           c: Container = Depends(get_container)):
    return c.quality.reopen(actor, occurrence_id, body.reason)


@router.post("/occurrences/{occurrence_id}/close", response_model=OccurrenceOut)
def close(occurrence_id: int, body: SignedTextIn, actor: Actor = Depends(current_actor),
          c: Container = Depends(get_container)):
    return _signed(c, actor, lambda: c.quality.close(actor, occurrence_id, body.text, body.signature_password))


@router.post("/occurrences/{occurrence_id}/cancel", response_model=OccurrenceOut)
def cancel(occurrence_id: int, body: SignedTextIn, actor: Actor = Depends(current_actor),
           c: Container = Depends(get_container)):
    return _signed(c, actor, lambda: c.quality.cancel(actor, occurrence_id, body.text, body.signature_password))


@router.post("/occurrences/{occurrence_id}/block-lot", response_model=OccurrenceOut)
def block_lot(occurrence_id: int, body: SignatureIn, actor: Actor = Depends(current_actor),
              c: Container = Depends(get_container)):
    return _signed(c, actor, lambda: c.quality.block_lot(actor, occurrence_id, body.signature_password))


@router.post("/occurrences/{occurrence_id}/release-lot", response_model=OccurrenceOut)
def release_lot(occurrence_id: int, body: SignedTextIn, actor: Actor = Depends(current_actor),
                c: Container = Depends(get_container)):
    return _signed(c, actor, lambda: c.quality.release_lot_to_quarantine(
        actor, occurrence_id, body.signature_password, body.text))
