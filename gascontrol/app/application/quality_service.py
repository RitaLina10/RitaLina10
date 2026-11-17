"""Casos de uso de qualidade: ocorrências (reclamação/desvio/NC/evento adverso) e CAPA."""
from __future__ import annotations

import logging
from datetime import date
from typing import Sequence

from app.application.services import (
    Actor, Clock, UowFactory, _audit, _naive_utc, _require_role, _signature_hash, _verify_signer, utcnow,
)
from app.domain import quality as q
from app.domain import rules
from app.domain.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.domain.quality import ActionStatus, ActionType, OccurrenceStatus, OccurrenceType, Severity
from app.domain.rules import LotStatus, Role
from app.infra.orm import CapaAction, Occurrence

log = logging.getLogger("gascontrol.quality")


class QualityService:
    def __init__(self, uow: UowFactory, clock: Clock = utcnow) -> None:
        self._uow = uow
        self._clock = clock

    # ---------- abertura (qualquer perfil, inclusive motorista em campo) ----------
    def open(self, actor: Actor, kind: OccurrenceType, severity: Severity, title: str, description: str,
             customer_id: int | None, lot_id: int | None, serial: str | None) -> Occurrence:
        if len(title.strip()) < 5 or len(description.strip()) < 10:
            raise ValidationFailed("Título (mín. 5) e descrição (mín. 10) são obrigatórios")
        severity = q.effective_severity(kind, severity)
        now = self._clock()
        with self._uow() as uow:
            cylinder_id = None
            if serial:
                cyl = uow.cylinders.get_by_serial(rules.normalize_serial(serial))
                if not cyl:
                    raise NotFound("Cilindro não encontrado")
                cylinder_id = cyl.id
                lot_id = lot_id or cyl.current_lot_id
            if lot_id and not uow.lots.get(lot_id):
                raise NotFound("Lote não encontrado")
            if customer_id and not uow.customers.get(customer_id):
                raise NotFound("Cliente não encontrado")
            if q.requires_lot_or_cylinder(kind) and not (lot_id or cylinder_id):
                raise ValidationFailed("Não conformidade/evento adverso exige lote ou cilindro identificado")
            code = f"OC-{now.year}-{uow.quality.next_sequence(now.year):04d}"
            occ = Occurrence(code=code, kind=kind, severity=severity, status=OccurrenceStatus.ABERTA,
                             title=title.strip(), description=description.strip(), customer_id=customer_id,
                             lot_id=lot_id, cylinder_id=cylinder_id, reported_by_id=actor.user_id,
                             opened_at=now, due_date=q.investigation_due(now.date(), severity), lot_blocked=False)
            uow.quality.add(occ)
            uow.flush()
            _audit(uow, actor.user_id, "ABRIR", "ocorrencia", occ.id,
                   {"code": code, "kind": str(kind), "severity": str(severity), "lot_id": lot_id,
                    "cylinder_id": cylinder_id}, now)
            uow.commit()
            uow.refresh(occ)
        level = logging.ERROR if severity == Severity.CRITICA else logging.INFO
        log.log(level, "occurrence_opened", extra={"code": code, "severity": str(severity), "kind": str(kind)})
        return occ

    # ---------- consulta (motorista só vê as que ele abriu) ----------
    def _visible(self, actor: Actor, occ: Occurrence | None) -> Occurrence:
        if occ is None or (actor.role == Role.MOTORISTA and occ.reported_by_id != actor.user_id):
            raise NotFound("Ocorrência não encontrada")
        return occ

    def get(self, actor: Actor, occurrence_id: int) -> Occurrence:
        with self._uow() as uow:
            return self._visible(actor, uow.quality.get(occurrence_id))

    def search(self, actor: Actor, status: str | None, lot_id: int | None, limit: int, offset: int) -> Sequence[Occurrence]:
        mine = actor.user_id if actor.role == Role.MOTORISTA else None
        with self._uow() as uow:
            return uow.quality.search(status, mine, lot_id, limit, offset)

    # ---------- investigação ----------
    def start_investigation(self, actor: Actor, occurrence_id: int, owner_id: int | None) -> Occurrence:
        _require_role(actor, Role.GESTOR)
        with self._uow() as uow:
            occ = self._get(uow, occurrence_id)
            q.ensure_can_start_investigation(OccurrenceStatus(occ.status))
            owner = uow.users.get(owner_id or actor.user_id)
            if not owner or not owner.active or owner.role == Role.MOTORISTA:
                raise ValidationFailed("Responsável inválido (usuário ativo, perfil gestor/operador)")
            occ.owner_id = owner.id
            occ.status = OccurrenceStatus.EM_INVESTIGACAO
            _audit(uow, actor.user_id, "INVESTIGAR", "ocorrencia", occ.id, {"owner_id": owner.id}, self._clock())
            uow.commit()
            uow.refresh(occ)
            return occ

    def set_root_cause(self, actor: Actor, occurrence_id: int, root_cause: str) -> Occurrence:
        _require_role(actor, Role.GESTOR, Role.OPERADOR)
        with self._uow() as uow:
            occ = self._get(uow, occurrence_id)
            if occ.status != OccurrenceStatus.EM_INVESTIGACAO:
                raise InvalidTransition("Causa raiz só pode ser registrada durante a investigação")
            self._ensure_owner_or_manager(actor, occ)
            _audit(uow, actor.user_id, "CAUSA_RAIZ", "ocorrencia", occ.id,
                   {"de": occ.root_cause, "para": root_cause.strip()}, self._clock())
            occ.root_cause = root_cause.strip()
            uow.commit()
            uow.refresh(occ)
            return occ

    def add_action(self, actor: Actor, occurrence_id: int, kind: ActionType, description: str,
                   responsible_id: int, due_date: date) -> Occurrence:
        _require_role(actor, Role.GESTOR)
        if len(description.strip()) < 10:
            raise ValidationFailed("Descrição da ação: mínimo 10 caracteres")
        now = self._clock()
        if due_date < now.date():
            raise ValidationFailed("Prazo da ação no passado")
        with self._uow() as uow:
            occ = self._get(uow, occurrence_id)
            q.ensure_action_editable(OccurrenceStatus(occ.status))
            resp = uow.users.get(responsible_id)
            if not resp or not resp.active:
                raise ValidationFailed("Responsável pela ação inválido")
            action = CapaAction(occurrence_id=occ.id, kind=kind, description=description.strip(),
                                responsible_id=resp.id, due_date=due_date, status=ActionStatus.PENDENTE,
                                created_at=now)
            uow.quality.add_action(action)
            uow.flush()
            _audit(uow, actor.user_id, "ACAO_CRIAR", "ocorrencia", occ.id,
                   {"action_id": action.id, "kind": str(kind), "responsible_id": resp.id,
                    "due": due_date.isoformat()}, now)
            uow.commit()
            uow.refresh(occ)
            return occ

    def complete_action(self, actor: Actor, action_id: int, evidence: str) -> Occurrence:
        if len((evidence or "").strip()) < 10:
            raise ValidationFailed("Evidência da execução: mínimo 10 caracteres")
        now = self._clock()
        with self._uow() as uow:
            action = uow.quality.get_action(action_id)
            if not action:
                raise NotFound("Ação não encontrada")
            if actor.role not in (Role.ADMIN, Role.GESTOR) and action.responsible_id != actor.user_id:
                raise Forbidden("Somente o responsável ou o gestor conclui a ação")
            occ = action.occurrence
            q.ensure_action_editable(OccurrenceStatus(occ.status))
            if action.status == ActionStatus.CONCLUIDA:
                raise Conflict("Ação já concluída")
            action.status = ActionStatus.CONCLUIDA
            action.evidence = evidence.strip()
            action.completed_at = now
            _audit(uow, actor.user_id, "ACAO_CONCLUIR", "ocorrencia", occ.id,
                   {"action_id": action.id, "evidence": action.evidence}, now)
            uow.commit()
            uow.refresh(occ)
            return occ

    def submit_for_effectiveness(self, actor: Actor, occurrence_id: int) -> Occurrence:
        _require_role(actor, Role.GESTOR)
        with self._uow() as uow:
            occ = self._get(uow, occurrence_id)
            q.ensure_can_submit_for_effectiveness(
                OccurrenceStatus(occ.status), occ.root_cause,
                [ActionStatus(a.status) for a in occ.actions], [ActionType(a.kind) for a in occ.actions])
            occ.status = OccurrenceStatus.AGUARDANDO_EFICACIA
            _audit(uow, actor.user_id, "AGUARDAR_EFICACIA", "ocorrencia", occ.id, {}, self._clock())
            uow.commit()
            uow.refresh(occ)
            return occ

    def reopen(self, actor: Actor, occurrence_id: int, reason: str) -> Occurrence:
        """Eficácia não comprovada: volta para investigação com o motivo registrado."""
        _require_role(actor, Role.GESTOR)
        if len((reason or "").strip()) < 10:
            raise ValidationFailed("Motivo da reabertura: mínimo 10 caracteres")
        with self._uow() as uow:
            occ = self._get(uow, occurrence_id)
            if occ.status != OccurrenceStatus.AGUARDANDO_EFICACIA:
                raise InvalidTransition("Só é possível reabrir na verificação de eficácia")
            occ.status = OccurrenceStatus.EM_INVESTIGACAO
            _audit(uow, actor.user_id, "INEFICAZ_REABRIR", "ocorrencia", occ.id, {"motivo": reason.strip()},
                   self._clock())
            uow.commit()
            uow.refresh(occ)
            return occ

    # ---------- encerramento e cancelamento (assinatura eletrônica) ----------
    def close(self, actor: Actor, occurrence_id: int, effectiveness: str, password: str) -> Occurrence:
        _require_role(actor, Role.GESTOR)
        now = self._clock()
        with self._uow() as uow:
            signer = _verify_signer(uow, actor, password)
            occ = self._get(uow, occurrence_id)
            q.ensure_can_close(OccurrenceStatus(occ.status), effectiveness)
            if occ.lot_blocked:
                raise InvalidTransition("Lote ainda bloqueado: libere-o para reavaliação (quarentena) antes de encerrar")
            occ.status = OccurrenceStatus.ENCERRADA
            occ.effectiveness_check = effectiveness.strip()
            occ.closed_at = now
            occ.closed_by_id = signer.id
            occ.closing_signature_hash = _signature_hash({
                "code": occ.code, "root_cause": occ.root_cause, "effectiveness": occ.effectiveness_check,
                "actions": [(a.id, str(a.status), a.evidence) for a in occ.actions],
                "signer": signer.id, "at": _naive_utc(now).isoformat()})
            _audit(uow, actor.user_id, "ENCERRAR_ASSINADO", "ocorrencia", occ.id,
                   {"signature_hash": occ.closing_signature_hash}, now)
            uow.commit()
            uow.refresh(occ)
            return occ

    def cancel(self, actor: Actor, occurrence_id: int, justification: str, password: str) -> Occurrence:
        _require_role(actor, Role.GESTOR)
        now = self._clock()
        with self._uow() as uow:
            signer = _verify_signer(uow, actor, password)
            occ = self._get(uow, occurrence_id)
            q.ensure_can_cancel(OccurrenceStatus(occ.status), justification)
            if occ.lot_blocked:
                raise InvalidTransition("Lote ainda bloqueado por esta ocorrência")
            occ.status = OccurrenceStatus.CANCELADA
            occ.closed_at = now
            occ.closed_by_id = signer.id
            occ.closing_signature_hash = _signature_hash({"code": occ.code, "cancel": justification.strip(),
                                                          "signer": signer.id, "at": _naive_utc(now).isoformat()})
            _audit(uow, actor.user_id, "CANCELAR_ASSINADO", "ocorrencia", occ.id,
                   {"justificativa": justification.strip()}, now)
            uow.commit()
            uow.refresh(occ)
            return occ

    # ---------- recall: bloqueio e liberação do lote ----------
    def block_lot(self, actor: Actor, occurrence_id: int, password: str) -> Occurrence:
        """Bloqueia o lote envolvido: nenhum envase ou entrega até reavaliação do RT."""
        _require_role(actor, Role.GESTOR)
        now = self._clock()
        with self._uow() as uow:
            _verify_signer(uow, actor, password)
            occ = self._get(uow, occurrence_id)
            if occ.status not in q.OPEN_STATUSES:
                raise InvalidTransition("Ocorrência não está aberta")
            if not occ.lot_id:
                raise ValidationFailed("Ocorrência sem lote vinculado")
            lot = uow.lots.get(occ.lot_id)
            if lot.status == LotStatus.REPROVADO:
                raise InvalidTransition("Lote já reprovado")
            previous = str(lot.status)
            lot.status = LotStatus.BLOQUEADO
            occ.lot_blocked = True
            _audit(uow, actor.user_id, "BLOQUEAR_LOTE", "lote", lot.id,
                   {"occurrence": occ.code, "status_anterior": previous}, now)
            uow.commit()
            uow.refresh(occ)
        log.error("lot_blocked", extra={"lot_id": occ.lot_id, "occurrence": occ.code})
        return occ

    def release_lot_to_quarantine(self, actor: Actor, occurrence_id: int, password: str, notes: str) -> Occurrence:
        """Fim do bloqueio: o lote volta à QUARENTENA e exige nova decisão assinada do RT."""
        _require_role(actor, Role.GESTOR)
        if len((notes or "").strip()) < 10:
            raise ValidationFailed("Justificativa: mínimo 10 caracteres")
        now = self._clock()
        with self._uow() as uow:
            _verify_signer(uow, actor, password)
            occ = self._get(uow, occurrence_id)
            if not occ.lot_blocked:
                raise InvalidTransition("Esta ocorrência não bloqueou lote")
            occ.lot_blocked = False
            lot = uow.lots.get(occ.lot_id)
            if uow.quality.open_blocking_lot(lot.id, occ.id) == 0:
                lot.status = LotStatus.QUARENTENA
                lot.signature_hash = None
                lot.signature_meaning = None
                lot.released_at = None
                lot.released_by_id = None
            _audit(uow, actor.user_id, "LOTE_PARA_QUARENTENA", "lote", lot.id,
                   {"occurrence": occ.code, "notes": notes.strip(), "status": str(lot.status)}, now)
            uow.commit()
            uow.refresh(occ)
            return occ

    # ---------- painel ----------
    def summary(self) -> dict[str, object]:
        today = self._clock().date()
        with self._uow() as uow:
            return {
                "open_by_severity": uow.quality.open_summary(),
                "overdue_occurrences": [{"id": o.id, "code": o.code, "title": o.title, "severity": str(o.severity),
                                         "due_date": o.due_date.isoformat()}
                                        for o in uow.quality.overdue_occurrences(today)],
                "overdue_actions": [{"id": a.id, "occurrence_id": a.occurrence_id, "description": a.description,
                                     "responsible": a.responsible.name, "due_date": a.due_date.isoformat()}
                                    for a in uow.quality.overdue_actions(today)],
            }

    # ---------- util ----------
    @staticmethod
    def _get(uow, occurrence_id: int) -> Occurrence:  # noqa: ANN001
        occ = uow.quality.get(occurrence_id)
        if not occ:
            raise NotFound("Ocorrência não encontrada")
        return occ

    @staticmethod
    def _ensure_owner_or_manager(actor: Actor, occ: Occurrence) -> None:
        if actor.role not in (Role.ADMIN, Role.GESTOR) and occ.owner_id != actor.user_id:
            raise Forbidden("Somente o responsável pela investigação ou o gestor")
