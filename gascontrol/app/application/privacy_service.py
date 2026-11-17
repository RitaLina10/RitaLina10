"""LGPD — direitos do titular (art. 18) com respeito às obrigações legais de guarda (art. 16, I).

* Exportação (acesso/portabilidade, art. 18 II e V): dados cadastrais + histórico de operações e notas.
* Anonimização (art. 18 IV/VI): substitui dados pessoais por marcadores irreversíveis, mantendo o
  vínculo técnico com movimentações (rastreabilidade sanitária) e notas fiscais.
  Recusada enquanto houver obrigação legal de guarda: movimentações ou NF-e dentro do prazo de
  retenção, cilindros ainda com o cliente ou nota em andamento.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.application.services import Actor, Clock, UowFactory, _audit, _require_role, _verify_signer, utcnow
from app.domain.errors import Conflict, NotFound
from app.domain.fiscal import InvoiceStatus
from app.domain.rules import Role

log = logging.getLogger("gascontrol.privacy")

EXPORT_LIMIT = 100_000
PERSONAL_FIELDS = ("phone", "address", "email", "state_registration", "street", "street_number",
                   "complement", "district", "city", "uf", "cep")


def _iso(d: Any) -> str | None:
    return d.isoformat() if d is not None else None


class PrivacyService:
    def __init__(self, uow: UowFactory, retention_years: int, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._retention = timedelta(days=365 * retention_years + retention_years // 4)
        self._years = retention_years
        self._clock = clock

    def export_customer(self, actor: Actor, customer_id: int) -> dict[str, Any]:
        _require_role(actor, Role.ADMIN)
        with self._uow() as uow:
            c = uow.customers.get(customer_id)
            if not c:
                raise NotFound("Cliente não encontrado")
            movements = uow.movements.recent(EXPORT_LIMIT, 0, customer_id, None)
            invoices = uow.fiscal.search(None, customer_id, EXPORT_LIMIT, 0)
            data = {
                "gerado_em": self._clock().isoformat(),
                "controlador": "Empresa usuária do PB Gas Control",
                "base_legal": ["execução de contrato (art. 7º, V)", "obrigação legal/regulatória (art. 7º, II)"],
                "titular": {
                    "id": c.id, "nome": c.name, "documento": c.document, "telefone": c.phone,
                    "email": c.email, "endereco": c.address, "logradouro": c.street, "numero": c.street_number,
                    "complemento": c.complement, "bairro": c.district, "municipio": c.city, "uf": c.uf,
                    "cep": c.cep, "inscricao_estadual": c.state_registration,
                    "estabelecimento_saude": c.is_health_facility, "ativo": c.active,
                    "cadastrado_em": _iso(c.created_at),
                },
                "movimentacoes": [
                    {"data": _iso(m.occurred_at), "tipo": str(m.type), "cilindro": m.cylinder.serial,
                     "lote": m.lot.code if m.lot else None, "comodato": m.is_loan, "documento": m.document_ref}
                    for m in movements
                ],
                "notas_fiscais": [
                    {"numero": i.number, "serie": i.series, "status": str(i.status), "total": float(i.total or 0),
                     "chave": i.access_key, "autorizada_em": _iso(i.authorized_at)}
                    for i in invoices
                ],
            }
            _audit(uow, actor.user_id, "EXPORTAR_DADOS_TITULAR", "cliente", c.id,
                   {"movimentacoes": len(data["movimentacoes"]), "notas": len(data["notas_fiscais"])}, self._clock())
            uow.commit()
            log.info("lgpd_export", extra={"customer_id": c.id})
            return data

    def anonymize_customer(self, actor: Actor, customer_id: int, password: str) -> None:
        _require_role(actor, Role.ADMIN)
        now = self._clock()
        cutoff = now - self._retention
        with self._uow() as uow:
            _verify_signer(uow, actor, password)
            c = uow.customers.get(customer_id)
            if not c:
                raise NotFound("Cliente não encontrado")
            if c.document.startswith("ANON"):
                raise Conflict("Cliente já anonimizado")
            if uow.cylinders.search(None, None, customer_id, None, 1, 0):
                raise Conflict("Há cilindros com este cliente. Recolha-os antes de anonimizar.")
            invoices = uow.fiscal.search(None, customer_id, EXPORT_LIMIT, 0)
            if any(i.status in (InvoiceStatus.RASCUNHO, InvoiceStatus.PROCESSANDO) for i in invoices):
                raise Conflict("Há nota fiscal em rascunho ou em processamento para este cliente.")
            last_mov = uow.movements.recent(1, 0, customer_id, None)
            recent_fiscal = [i for i in invoices if _aware(i.authorized_at or i.created_at) >= cutoff]
            if (last_mov and _aware(last_mov[0].occurred_at) >= cutoff) or recent_fiscal:
                raise Conflict(
                    f"Retenção legal em vigor (LGPD art. 16, I): há movimentações ou notas fiscais dos últimos "
                    f"{self._years} anos, exigidas pela rastreabilidade sanitária e pela legislação fiscal. "
                    "O cliente pode ser desativado; a anonimização fica disponível após o prazo.")
            c.name = f"Titular anonimizado #{c.id}"
            c.document = f"ANON{c.id:010d}"[:14]
            for field in PERSONAL_FIELDS:
                setattr(c, field, None)
            c.active = False
            _audit(uow, actor.user_id, "ANONIMIZAR_TITULAR", "cliente", c.id, {}, now)
            uow.commit()
            log.info("lgpd_anonymized", extra={"customer_id": c.id})


def _aware(d):  # noqa: ANN001, ANN202
    from datetime import timezone

    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d
