"""Composition root: monta dependências, middlewares, rotas e frontend estático."""
from __future__ import annotations

import hmac
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import Container
from app.api.routers import auth, catalog, cylinders, reports, sync
from app.application.security import LoginThrottle, TokenService
from app.application.services import (
    AuthService, CatalogService, CylinderService, LotService, ReportService, SyncService,
)
from app.config import Settings, get_settings
from app.domain.errors import DomainError
from app.infra.db import build_engine, build_session_factory, upgrade_schema
from app.infra.repositories import SqlUnitOfWork
from app.observability import HTTP_LATENCY, HTTP_REQUESTS, REGISTRY, configure_logging, trace_id_var

log = logging.getLogger("gascontrol")
STATIC_DIR = Path(__file__).parent / "static"
_TRACE_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), geolocation=(self), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    ),
}


def build_container(settings: Settings) -> tuple[Container, object]:
    engine = build_engine(settings.database_url)
    added = upgrade_schema(engine)
    if added:
        log.info("schema_upgraded", extra={"columns": added})
    factory = build_session_factory(engine)

    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(factory)

    def ping_db() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    cylinder_service = CylinderService(uow, settings.hydro_test_validity_years)
    container = Container(
        settings=settings,
        tokens=TokenService(settings.jwt_secret, settings.jwt_ttl_minutes),
        throttle=LoginThrottle(settings.login_max_attempts, settings.login_lockout_seconds),
        auth=AuthService(uow),
        catalog=CatalogService(uow),
        lots=LotService(uow),
        cylinders=cylinder_service,
        reports=ReportService(uow, settings.hydro_test_validity_years, settings.hydro_alert_days),
        sync=SyncService(uow, cylinder_service, settings.hydro_test_validity_years),
        ping_db=ping_db,
    )
    return container, engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    container, engine = build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.catalog.seed_gas_types()
        container.auth.bootstrap_admin(settings.admin_email, settings.admin_password)
        log.info("startup", extra={"env": settings.env})
        yield
        engine.dispose()  # type: ignore[attr-defined]
        log.info("shutdown")

    app = FastAPI(
        title="GasControl", version="1.0.0", lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None, openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.container = container

    @app.middleware("http")
    async def observability_mw(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        trace_id = incoming if _TRACE_RE.fullmatch(incoming) else uuid.uuid4().hex
        token = trace_id_var.set(trace_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, route_path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route_path).observe(elapsed)
            if not route_path.startswith(("/static", "/health", "/ready", "/metrics")):
                log.info("http_request", extra={"method": request.method, "route": route_path,
                                                "status": status, "duration_ms": round(elapsed * 1000, 2)})
            trace_id_var.reset(token)
        response.headers["X-Request-ID"] = trace_id
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    def _err(status: int, code: str, message: object) -> JSONResponse:
        return JSONResponse(status_code=status,
                            content={"error": code, "message": message, "trace_id": trace_id_var.get()})

    @app.exception_handler(DomainError)
    async def domain_handler(_: Request, exc: DomainError):
        return _err(exc.http_status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return _err(422, "invalid_request", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        resp = _err(exc.status_code, "http_error", exc.detail)
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled_error")
        return _err(500, "internal_error", "Erro interno")

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    def ready():
        try:
            container.ping_db()  # type: ignore[operator]
        except Exception:
            log.exception("readiness_failed")
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        if settings.metrics_token:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied, settings.metrics_token):
                return Response(status_code=401)
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(cylinders.router)
    app.include_router(reports.router)
    app.include_router(sync.router)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        # Servido na raiz para controlar todo o escopo "/" (app offline).
        return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    return app

