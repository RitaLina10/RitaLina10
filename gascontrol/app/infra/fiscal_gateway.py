"""Adaptadores de emissão de NF-e.

O mapeamento de campos do Focus NFe fica todo neste arquivo. Antes de produção, valide em
HOMOLOGAÇÃO (FOCUS_ENVIRONMENT=homologacao) com o contador: CFOP, CST, alíquotas e campos da
Reforma Tributária (IBS/CBS) variam por empresa e mudam com a legislação.
"""
from __future__ import annotations

import logging
import threading
import time
from decimal import Decimal
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx

from app.application.ports import FiscalDocument, FiscalResult
from app.domain.errors import ExternalServiceError
from app.observability import REGISTRY

from prometheus_client import Counter

log = logging.getLogger("gascontrol.fiscal")

FISCAL_CALLS = Counter("gascontrol_fiscal_calls_total", "Chamadas ao emissor fiscal", ["op", "outcome"],
                       registry=REGISTRY)


class CircuitBreaker:
    """Abre após N falhas seguidas; fica aberto por `reset_seconds` (evita martelar um serviço caído)."""

    def __init__(self, threshold: int = 5, reset_seconds: float = 60, clock: Callable[[], float] = time.monotonic):
        self._threshold = threshold
        self._reset = reset_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if self._clock() - self._opened_at >= self._reset:
                self._opened_at = None  # meia-abertura: deixa uma tentativa passar
                self._failures = self._threshold - 1
                return
            raise ExternalServiceError("Emissor de NF-e indisponível; tente novamente em instantes")

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = self._clock()
                log.error("fiscal_circuit_open")


class DisabledFiscalGateway:
    name = "desativado"

    def _fail(self) -> FiscalResult:
        raise ExternalServiceError("Emissão de NF-e não configurada (defina FISCAL_PROVIDER e credenciais)")

    def emit(self, doc: FiscalDocument) -> FiscalResult:
        return self._fail()

    def query(self, ref: str) -> FiscalResult:
        return self._fail()

    def cancel(self, ref: str, justification: str) -> FiscalResult:
        return self._fail()


_FOCUS_STATUS = {
    "processando_autorizacao": "processing",
    "autorizado": "authorized",
    "cancelado": "cancelled",
    "erro_autorizacao": "rejected",
    "denegado": "rejected",
}


class FocusNFeGateway:
    name = "focusnfe"
    URLS = {"homologacao": "https://homologacao.focusnfe.com.br", "producao": "https://api.focusnfe.com.br"}

    def __init__(self, token: str, environment: str, emitter_cnpj: str, *,
                 client: httpx.Client | None = None, breaker: CircuitBreaker | None = None,
                 max_retries: int = 3, backoff_base: float = 0.5, sleep: Callable[[float], None] = time.sleep):
        if environment not in self.URLS:
            raise ValueError("FOCUS_ENVIRONMENT deve ser homologacao ou producao")
        if not token:
            raise ValueError("FOCUS_TOKEN é obrigatório")
        self.base = self.URLS[environment]
        self.cnpj = emitter_cnpj
        self._client = client or httpx.Client(
            base_url=self.base, auth=(token, ""), timeout=httpx.Timeout(20.0, connect=5.0),
            headers={"User-Agent": "GasControl/2"}, follow_redirects=False)
        self._breaker = breaker or CircuitBreaker()
        self._retries = max_retries
        self._backoff = backoff_base
        self._sleep = sleep
        self._allowed_hosts = {urlparse(self.base).hostname}

    # -------- transporte --------
    def _request(self, op: str, method: str, path: str, *, json: dict | None = None,
                 retry: bool = True) -> httpx.Response:
        attempts = self._retries if retry else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            self._breaker.before_call()  # a cada tentativa: se o circuito abriu no meio, para de insistir
            try:
                resp = self._client.request(method, path, json=json)
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                self._breaker.success()
                FISCAL_CALLS.labels(op, str(resp.status_code)).inc()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                self._breaker.failure()
                FISCAL_CALLS.labels(op, "error").inc()
                log.warning("fiscal_call_failed", extra={"op": op, "attempt": attempt + 1, "error": str(exc)})
                if attempt + 1 < attempts:
                    self._sleep(self._backoff * (2 ** attempt))
        raise _TransportFailure(str(last_exc))

    def _file_url(self, path: str | None) -> str | None:
        """Só aceita links HTTPS do próprio provedor (evita link malicioso salvo no banco)."""
        if not path:
            return None
        url = urljoin(self.base, path)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self._allowed_hosts:
            log.warning("fiscal_file_url_rejected", extra={"host": parsed.hostname})
            return None
        return url

    def _result(self, data: dict) -> FiscalResult:
        status = _FOCUS_STATUS.get(str(data.get("status")), "processing")
        key = str(data.get("chave_nfe") or "").removeprefix("NFe") or None
        msg = data.get("mensagem_sefaz") or data.get("mensagem")
        return FiscalResult(status=status, access_key=key, number=_s(data.get("numero")), series=_s(data.get("serie")),
                            danfe_url=self._file_url(data.get("caminho_danfe")),
                            xml_url=self._file_url(data.get("caminho_xml_nota_fiscal")),
                            message=str(msg)[:1000] if msg else None)

    # -------- operações --------
    def emit(self, doc: FiscalDocument) -> FiscalResult:
        try:
            # POST não é repetido automaticamente: se a resposta se perder, consulta-se por "ref".
            resp = self._request("emit", "POST", f"/v2/nfe?ref={doc.ref}", json=self.build_payload(doc), retry=False)
        except _TransportFailure as exc:
            return FiscalResult(status="processing", message=f"Sem resposta do emissor; será consultado: {exc}"[:1000])
        data = _json(resp)
        if resp.status_code in (200, 201, 202):
            return self._result(data)
        if resp.status_code == 422 and data.get("codigo") == "already_processed":
            return self.query(doc.ref)
        return FiscalResult(status="rejected", message=str(data.get("mensagem") or f"HTTP {resp.status_code}")[:1000])

    def query(self, ref: str) -> FiscalResult:
        try:
            resp = self._request("query", "GET", f"/v2/nfe/{ref}")
        except _TransportFailure as exc:
            raise ExternalServiceError(f"Emissor fiscal sem resposta: {exc}") from exc
        if resp.status_code == 404:
            return FiscalResult(status="not_found", message="Nota não encontrada no emissor")
        return self._result(_json(resp))

    def cancel(self, ref: str, justification: str) -> FiscalResult:
        try:
            resp = self._request("cancel", "DELETE", f"/v2/nfe/{ref}", json={"justificativa": justification})
        except _TransportFailure as exc:
            raise ExternalServiceError(f"Emissor fiscal sem resposta: {exc}") from exc
        data = _json(resp)
        if resp.status_code >= 400 or data.get("status") != "cancelado":
            msg = data.get("mensagem_sefaz") or data.get("mensagem") or f"HTTP {resp.status_code}"
            return FiscalResult(status="authorized", message=f"Cancelamento recusado: {msg}"[:1000])
        return self._result(data)

    def build_payload(self, doc: FiscalDocument) -> dict[str, object]:
        c = doc.customer
        is_company = len(c.document) == 14
        contributor = bool(c.state_registration and c.state_registration.upper() != "ISENTO")
        payload: dict[str, object] = {
            "natureza_operacao": doc.nature,
            "data_emissao": doc.issued_at.isoformat(timespec="seconds"),
            "tipo_documento": 1,           # saída
            "finalidade_emissao": 1,       # normal
            "consumidor_final": 0 if contributor else 1,
            "presenca_comprador": 9,       # operação não presencial (entrega)
            "modalidade_frete": 0,         # por conta do emitente
            "cnpj_emitente": self.cnpj,
            "nome_destinatario": c.name[:60],
            ("cnpj_destinatario" if is_company else "cpf_destinatario"): c.document,
            "indicador_inscricao_estadual_destinatario": 1 if contributor else 9,
            "logradouro_destinatario": c.street, "numero_destinatario": c.number,
            "bairro_destinatario": c.district, "municipio_destinatario": c.city,
            "uf_destinatario": c.uf, "cep_destinatario": c.cep, "pais_destinatario": "Brasil",
            "valor_produtos": _d(doc.total), "valor_total": _d(doc.total),
            "items": [self._item(line) for line in doc.lines],
        }
        if contributor:
            payload["inscricao_estadual_destinatario"] = c.state_registration
        if c.complement:
            payload["complemento_destinatario"] = c.complement
        if c.email:
            payload["email_destinatario"] = c.email
        if doc.notes:
            payload["informacoes_adicionais_contribuinte"] = doc.notes[:2000]
        return payload

    @staticmethod
    def _item(line) -> dict[str, object]:  # noqa: ANN001
        item: dict[str, object] = {
            "numero_item": line.number, "codigo_produto": line.code, "descricao": line.description[:120],
            "cfop": line.cfop, "codigo_ncm": line.ncm,
            "unidade_comercial": line.unit, "quantidade_comercial": _d(line.quantity, 4),
            "valor_unitario_comercial": _d(line.unit_price, 4),
            "unidade_tributavel": line.unit, "quantidade_tributavel": _d(line.quantity, 4),
            "valor_unitario_tributavel": _d(line.unit_price, 4),
            "valor_bruto": _d(line.total), "inclui_no_total": 1,
            "icms_origem": line.origin, "icms_situacao_tributaria": line.icms_cst,
            "pis_situacao_tributaria": line.pis_cst, "cofins_situacao_tributaria": line.cofins_cst,
        }
        if line.icms_cst == "00":  # tributada integralmente
            base = line.total
            item.update({"icms_modalidade_base_calculo": 3, "icms_base_calculo": _d(base),
                         "icms_aliquota": _d(line.icms_rate),
                         "icms_valor": _d((base * line.icms_rate / Decimal(100)).quantize(Decimal("0.01")))})
        return item


class _TransportFailure(Exception):
    pass


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _s(v: object) -> str | None:
    return None if v is None else str(v)


def _d(v: Decimal, places: int = 2) -> str:
    return f"{Decimal(v):.{places}f}"
