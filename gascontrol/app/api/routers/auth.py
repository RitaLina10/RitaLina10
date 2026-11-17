from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import DbId
from app.api.deps import Container, current_actor, get_container
from app.api.schemas import ActiveIn, LoginIn, PasswordChangeIn, TokenOut, UserIn, UserOut
from app.application.security import password_version
from app.application.services import Actor
from app.domain.errors import Forbidden
from app.observability import LOGIN_FAILURES

router = APIRouter(prefix="/api", tags=["auth"])
log = logging.getLogger("gascontrol.auth")


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, c: Container = Depends(get_container)) -> TokenOut:
    ip = request.client.host if request.client else "unknown"
    key = f"{body.email.lower()}|{ip}"
    if c.throttle.is_locked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas; aguarde")
    user = c.auth.authenticate(body.email, body.password)
    if user is None:
        c.throttle.fail(key)
        LOGIN_FAILURES.inc()
        log.warning("login_failed", extra={"ip": ip})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")
    c.throttle.success(key)
    token, ttl = c.tokens.issue(user.id, str(user.role), password_version(user.password_changed_at))
    log.info("login_ok", extra={"user_id": user.id})
    return TokenOut(access_token=token, expires_in=ttl, role=user.role, name=user.name)


@router.get("/auth/me", response_model=UserOut)
def me(actor: Actor = Depends(current_actor), c: Container = Depends(get_container)) -> UserOut:
    user = c.auth.get_active_user(actor.user_id)
    return UserOut.model_validate(user)


@router.post("/auth/password", response_model=TokenOut)
def change_password(body: PasswordChangeIn, actor: Actor = Depends(current_actor),
                    c: Container = Depends(get_container)) -> TokenOut:
    """Troca a senha, revoga todas as sessões anteriores e devolve um token novo para esta."""
    key = f"pwd|{actor.user_id}"
    if c.throttle.is_locked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas; aguarde")
    try:
        c.auth.change_password(actor, body.current_password, body.new_password)
    except Forbidden:
        c.throttle.fail(key)
        raise
    c.throttle.success(key)
    user = c.auth.get_active_user(actor.user_id)
    token, ttl = c.tokens.issue(user.id, str(user.role), password_version(user.password_changed_at))
    return TokenOut(access_token=token, expires_in=ttl, role=user.role, name=user.name)


@router.get("/users", response_model=list[UserOut])
def list_users(actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.auth.list_users(actor)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return c.auth.create_user(actor, str(body.email), body.name, body.password, body.role)


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(user_id: DbId, body: ActiveIn, actor: Actor = Depends(current_actor),
               c: Container = Depends(get_container)):
    return c.auth.set_active(actor, user_id, body.active)
