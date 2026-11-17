"""LGPD — direitos do titular (somente ADMIN; anonimização exige assinatura eletrônica)."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import StringConstraints

from app.api.schemas import DbId
from app.api.deps import Container, current_actor, get_container
from app.api.schemas import Strict
from app.application.services import Actor
from app.domain.errors import Forbidden

router = APIRouter(prefix="/api/privacy", tags=["lgpd"])


class SignatureIn(Strict):
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


@router.get("/customers/{customer_id}/export")
def export_customer(customer_id: DbId, actor: Actor = Depends(current_actor),
                    c: Container = Depends(get_container)) -> Response:
    data = c.privacy.export_customer(actor, customer_id)
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="titular-{customer_id}.json"'})


@router.post("/customers/{customer_id}/anonymize", status_code=204)
def anonymize_customer(customer_id: DbId, body: SignatureIn, actor: Actor = Depends(current_actor),
                       c: Container = Depends(get_container)) -> None:
    key = f"sign|{actor.user_id}"
    if c.throttle.is_locked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas; aguarde")
    try:
        c.privacy.anonymize_customer(actor, customer_id, body.password)
    except Forbidden:
        c.throttle.fail(key)
        raise
    c.throttle.success(key)
