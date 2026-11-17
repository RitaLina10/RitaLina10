"""Regras fiscais independentes de provedor (NF-e modelo 55)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.domain.errors import InvalidTransition, ValidationFailed


class InvoiceStatus(StrEnum):
    RASCUNHO = "RASCUNHO"
    PROCESSANDO = "PROCESSANDO"      # enviada ao emissor, aguardando SEFAZ (ou resposta perdida)
    AUTORIZADA = "AUTORIZADA"
    REJEITADA = "REJEITADA"          # SEFAZ recusou; corrigir e reenviar
    CANCELADA = "CANCELADA"


UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
UNITS = frozenset({"UN", "M3", "KG", "L", "CIL"})
_NCM = re.compile(r"^\d{8}$")
_CFOP_OUT = re.compile(r"^[567]\d{3}$")       # saídas: 5 (interna), 6 (interestadual), 7 (exterior)
_CST_ICMS = re.compile(r"^(\d{2}|\d{3})$")   # CST (2 dígitos) ou CSOSN (3 dígitos, Simples)
_CST_PIS_COFINS = re.compile(r"^\d{2}$")
_CEP = re.compile(r"^\d{8}$")
CENT = Decimal("0.01")


def money(v: Decimal | float | str) -> Decimal:
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def digits(raw: str | None) -> str:
    return re.sub(r"\D", "", raw or "")


def validate_fiscal_profile(ncm: str, cfop_internal: str, cfop_interstate: str, unit: str,
                            icms_cst: str, pis_cst: str, cofins_cst: str, origin: int) -> dict[str, object]:
    ncm_d = digits(ncm)
    if not _NCM.fullmatch(ncm_d):
        raise ValidationFailed("NCM deve ter 8 dígitos")
    for label, cfop in (("CFOP interno", cfop_internal), ("CFOP interestadual", cfop_interstate)):
        if not _CFOP_OUT.fullmatch(cfop or ""):
            raise ValidationFailed(f"{label} inválido para saída (4 dígitos iniciando em 5, 6 ou 7)")
    if not cfop_internal.startswith("5") or not cfop_interstate.startswith("6"):
        raise ValidationFailed("CFOP interno deve iniciar com 5 e interestadual com 6")
    if unit not in UNITS:
        raise ValidationFailed(f"Unidade deve ser uma de: {', '.join(sorted(UNITS))}")
    if not _CST_ICMS.fullmatch(icms_cst or ""):
        raise ValidationFailed("CST/CSOSN de ICMS inválido")
    if not _CST_PIS_COFINS.fullmatch(pis_cst or "") or not _CST_PIS_COFINS.fullmatch(cofins_cst or ""):
        raise ValidationFailed("CST de PIS/COFINS deve ter 2 dígitos")
    if origin not in range(0, 9):
        raise ValidationFailed("Origem da mercadoria deve ser 0 a 8")
    return {"ncm": ncm_d}


def ensure_customer_ready(street: str | None, number: str | None, district: str | None, city: str | None,
                          uf: str | None, cep: str | None) -> None:
    missing = [n for n, v in (("logradouro", street), ("número", number), ("bairro", district),
                              ("município", city), ("UF", uf), ("CEP", cep)) if not v]
    if missing:
        raise ValidationFailed("Cadastro do cliente incompleto para NF-e: " + ", ".join(missing))
    if uf not in UFS:
        raise ValidationFailed("UF do cliente inválida")
    if not _CEP.fullmatch(digits(cep)):
        raise ValidationFailed("CEP do cliente inválido")


def cfop_for(emitter_uf: str, customer_uf: str, internal: str, interstate: str) -> str:
    return internal if emitter_uf == customer_uf else interstate


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    if quantity <= 0:
        raise ValidationFailed("Quantidade deve ser maior que zero")
    if unit_price <= 0:
        raise ValidationFailed("Preço unitário deve ser maior que zero")
    return money(quantity * unit_price)


def ensure_editable(status: InvoiceStatus) -> None:
    if status not in (InvoiceStatus.RASCUNHO, InvoiceStatus.REJEITADA):
        raise InvalidTransition(f"Nota em {status} não pode ser alterada")


def ensure_can_emit(status: InvoiceStatus, item_count: int) -> None:
    if status not in (InvoiceStatus.RASCUNHO, InvoiceStatus.REJEITADA):
        raise InvalidTransition(f"Nota em {status} não pode ser emitida")
    if item_count == 0:
        raise ValidationFailed("Nota sem itens")


def ensure_can_cancel(status: InvoiceStatus, authorized_at: datetime | None, now: datetime,
                      justification: str, window_hours: int) -> None:
    if status != InvoiceStatus.AUTORIZADA:
        raise InvalidTransition("Só notas autorizadas podem ser canceladas")
    just = (justification or "").strip()
    if not 15 <= len(just) <= 255:
        raise ValidationFailed("Justificativa do cancelamento deve ter entre 15 e 255 caracteres")
    if authorized_at is not None and now - authorized_at > timedelta(hours=window_hours):
        raise InvalidTransition(f"Prazo de cancelamento ({window_hours} h) expirado; use nota de devolução/estorno")
