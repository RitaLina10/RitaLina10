"""Relatórios para fiscalização: dossiê de lote, histórico de cilindro e trilha de auditoria."""
from __future__ import annotations

import csv
import io
from typing import Iterable, Sequence

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import Container, get_container, require
from app.api.routers.cylinders import QR_PREFIX
from app.api.schemas import AuditEventOut
from app.application.services import Actor
from app.domain.rules import Role, csv_safe
from app.infra.orm import Movement

router = APIRouter(prefix="/api", tags=["relatórios"])

MOVEMENT_HEADER = ["data_servidor_utc", "data_campo_utc", "offline", "operacao", "cilindro", "de", "para",
                   "cliente", "documento_cliente", "lote", "usuario", "nf_romaneio", "latitude", "longitude",
                   "checklist", "observacoes", "hash"]


def _rows(movements: Sequence[Movement]) -> Iterable[list[object]]:
    for m in movements:
        yield [m.occurred_at.isoformat(), m.client_occurred_at.isoformat() if m.client_occurred_at else "",
               "sim" if m.offline else "nao", m.type, m.cylinder.serial, m.from_status or "", m.to_status,
               m.customer.name if m.customer else "", m.customer.document if m.customer else "",
               m.lot.code if m.lot else "", m.user.name, m.document_ref, m.latitude, m.longitude,
               m.checklist, m.notes, m.hash]


def _csv(filename: str, preamble: list[list[object]], header: list[str], rows: Iterable[list[object]]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    for line in preamble:
        w.writerow([csv_safe(v) for v in line])
    w.writerow(header)
    for r in rows:
        w.writerow([csv_safe(v) for v in r])
    data = "﻿" + buf.getvalue()  # BOM: Excel abre acentuação corretamente
    return Response(data.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/lots/{lot_id}/dossier.csv")
def lot_dossier(lot_id: int, _: Actor = Depends(require(Role.GESTOR)), c: Container = Depends(get_container)):
    lot, movements = c.lots.trace(lot_id)
    preamble = [["DOSSIÊ DE LOTE — rastreabilidade e recall"], ["lote", lot.code], ["gas", lot.gas_type.name],
                ["fabricacao", lot.production_date], ["validade", lot.expiry_date], ["pureza_%", lot.purity_percent],
                ["laudo", lot.analysis_report], ["status", lot.status], ["liberado_em", lot.released_at],
                ["assinatura", lot.signature_meaning], ["hash_assinatura", lot.signature_hash], []]
    return _csv(f"dossie-lote-{lot.code}.csv", preamble, MOVEMENT_HEADER, _rows(movements))


@router.get("/cylinders/{serial}/history.csv")
def cylinder_csv(serial: str, _: Actor = Depends(require(Role.GESTOR, Role.OPERADOR)),
                 c: Container = Depends(get_container)):
    cyl, movements = c.cylinders.history(serial.removeprefix(QR_PREFIX))
    preamble = [["HISTÓRICO DO CILINDRO"], ["serie", cyl.serial], ["gas", cyl.gas_type.name],
                ["capacidade_l", cyl.capacity_liters], ["ultimo_teste_hidrostatico", cyl.last_hydro_test],
                ["status_atual", cyl.status], []]
    return _csv(f"cilindro-{cyl.serial}.csv", preamble, MOVEMENT_HEADER, _rows(movements))


@router.get("/audit/events", response_model=list[AuditEventOut])
def audit_events(entity: str | None = Query(default=None, max_length=40), limit: int = Query(100, ge=1, le=500),
                 offset: int = Query(0, ge=0), _: Actor = Depends(require(Role.GESTOR)),
                 c: Container = Depends(get_container)):
    return c.reports.audit_events(entity, limit, offset)
