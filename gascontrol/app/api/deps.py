"""Container de dependências e autenticação/autorização por papel."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.fiscal_service import FiscalService
from app.application.privacy_service import PrivacyService
from app.application.quality_service import QualityService
from app.application.security import LoginThrottle, TokenService, password_version
from app.application.services import (
    Actor, AuthService, CatalogService, CylinderService, LotService, ReportService, SyncService,
)
from app.config import Settings
from app.domain.rules import Role


@dataclass
class Container:
    settings: Settings
    tokens: TokenService
    throttle: LoginThrottle
    auth: AuthService
    catalog: CatalogService
    lots: LotService
    cylinders: CylinderService
    reports: ReportService
    sync: SyncService
    quality: QualityService
    fiscal: FiscalService
    privacy: PrivacyService
    ping_db: object  # Callable[[], None]


def get_container(request: Request) -> Container:
    return request.app.state.container


_bearer = HTTPBearer(auto_error=False)


def current_actor(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                  c: Container = Depends(get_container)) -> Actor:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    try:
        payload = c.tokens.decode(creds.credentials)
        user_id = int(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    # Revalida no banco: usuário desativado ou com papel alterado perde acesso imediatamente.
    user = c.auth.get_active_user(user_id)
    if user is None:
        raise unauthorized
    try:
        token_pwv = int(str(payload.get("pwv", 0)))
    except ValueError:
        raise unauthorized from None
    if token_pwv != password_version(user.password_changed_at):
        raise unauthorized  # sessão anterior à troca de senha
    return Actor(user_id=user.id, role=Role(user.role))


def require(*roles: Role):
    def _dep(actor: Actor = Depends(current_actor)) -> Actor:
        if actor.role != Role.ADMIN and actor.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Perfil sem permissão")
        return actor
    return _dep
