"""Logging JSON estruturado com trace_id e métricas Prometheus."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

from prometheus_client import CollectorRegistry, Counter, Histogram

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


class JsonFormatter(logging.Formatter):
    _RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": trace_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "gascontrol_http_requests_total", "Requisições HTTP", ["method", "route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "gascontrol_http_request_duration_seconds", "Latência HTTP", ["method", "route"], registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
MOVEMENTS = Counter(
    "gascontrol_movements_total", "Movimentações de cilindros registradas", ["type"], registry=REGISTRY
)
DOMAIN_REJECTIONS = Counter(
    "gascontrol_domain_rejections_total", "Operações rejeitadas por regra de negócio", ["code"], registry=REGISTRY
)
LOGIN_FAILURES = Counter("gascontrol_login_failures_total", "Falhas de login", registry=REGISTRY)
