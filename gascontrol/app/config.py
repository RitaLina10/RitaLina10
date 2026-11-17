"""Configuração carregada exclusivamente de variáveis de ambiente."""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class ConfigError(RuntimeError):
    pass


APP_NAME = "PB Gas Control"
APP_VENDOR = "PB Tecnologia"
APP_FULL_NAME = f"{APP_VENDOR} - {APP_NAME}"
# Origem fixa do app Android (WebViewAssetLoader): a interface roda embarcada no APK.
ANDROID_APP_ORIGIN = "https://appassets.androidplatform.net"


def parse_origins(raw: str) -> list[str]:
    """Valida origens CORS (esquema://host[:porta]) — nunca aceita curinga."""
    out: list[str] = []
    for item in (x.strip() for x in raw.split(",")):
        if not item:
            continue
        parts = urlsplit(item)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.path not in {"", "/"} \
                or parts.query or parts.fragment or parts.username or parts.password:
            raise ConfigError(f"Origem CORS inválida: {item!r}")
        out.append(f"{parts.scheme}://{parts.netloc}".lower())
    return out


class Settings(BaseModel):
    env: str = Field(default="development")
    database_url: str = Field(default="sqlite:///./data/gascontrol.db")
    jwt_secret: str
    jwt_ttl_minutes: int = Field(default=480, ge=5, le=1440)
    hydro_test_validity_years: int = Field(default=5, ge=1, le=10)
    hydro_alert_days: int = Field(default=60, ge=1, le=365)
    admin_email: str | None = None
    admin_password: str | None = None
    log_level: str = Field(default="INFO")
    login_max_attempts: int = Field(default=5, ge=1, le=50)
    login_lockout_seconds: int = Field(default=900, ge=10)
    metrics_token: str | None = None
    fiscal_provider: str = Field(default="none")
    focus_token: str | None = None
    focus_environment: str = Field(default="homologacao")
    emitter_cnpj: str | None = None
    emitter_uf: str | None = None
    fiscal_cancel_hours: int = Field(default=24, ge=1, le=720)
    fiscal_poll_seconds: int = Field(default=60, ge=0, le=3600)
    cors_origins: list[str] = Field(default_factory=lambda: [ANDROID_APP_ORIGIN])
    max_body_bytes: int = Field(default=2 * 1024 * 1024, ge=64 * 1024, le=50 * 1024 * 1024)
    lgpd_retention_years: int = Field(default=5, ge=1, le=30)

    @field_validator("fiscal_provider")
    @classmethod
    def _provider(cls, v: str) -> str:
        if v not in {"none", "focusnfe"}:
            raise ValueError("FISCAL_PROVIDER deve ser none|focusnfe")
        return v

    @field_validator("env")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in {"development", "test", "production"}:
            raise ValueError("APP_ENV deve ser development|test|production")
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_settings() -> Settings:
    env = os.getenv("APP_ENV", "development")
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        if env == "production":
            raise ConfigError("JWT_SECRET é obrigatório em produção")
        secret = secrets.token_urlsafe(48)
    if env == "production" and len(secret) < 32:
        raise ConfigError("JWT_SECRET deve ter no mínimo 32 caracteres")
    return Settings(
        env=env,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/gascontrol.db"),
        jwt_secret=secret,
        jwt_ttl_minutes=int(os.getenv("JWT_TTL_MINUTES", "480")),
        hydro_test_validity_years=int(os.getenv("HYDRO_TEST_VALIDITY_YEARS", "5")),
        hydro_alert_days=int(os.getenv("HYDRO_ALERT_DAYS", "60")),
        admin_email=os.getenv("ADMIN_EMAIL") or None,
        admin_password=os.getenv("ADMIN_PASSWORD") or None,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        login_max_attempts=int(os.getenv("LOGIN_MAX_ATTEMPTS", "5")),
        login_lockout_seconds=int(os.getenv("LOGIN_LOCKOUT_SECONDS", "900")),
        metrics_token=os.getenv("METRICS_TOKEN") or None,
        fiscal_provider=os.getenv("FISCAL_PROVIDER", "none"),
        focus_token=os.getenv("FOCUS_TOKEN") or None,
        focus_environment=os.getenv("FOCUS_ENVIRONMENT", "homologacao"),
        emitter_cnpj="".join(ch for ch in os.getenv("EMITTER_CNPJ", "") if ch.isdigit()) or None,
        emitter_uf=(os.getenv("EMITTER_UF") or "").upper() or None,
        fiscal_cancel_hours=int(os.getenv("FISCAL_CANCEL_HOURS", "24")),
        fiscal_poll_seconds=int(os.getenv("FISCAL_POLL_SECONDS", "60")),
        cors_origins=parse_origins(os.getenv("CORS_ORIGINS", ANDROID_APP_ORIGIN)),
        max_body_bytes=int(os.getenv("MAX_BODY_BYTES", str(2 * 1024 * 1024))),
        lgpd_retention_years=int(os.getenv("LGPD_RETENTION_YEARS", "5")),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
