from datetime import date, timedelta

from tests.conftest import CHECKLIST_OK, PWD, approved_lot, new_cylinder

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def _setup_medicinal(client, users, gases, customer):
    lot = approved_lot(client, users, gases["O2-MED"], code="REC-1")
    new_cylinder(client, users["OPERADOR"], "Q-1", gases["O2-MED"])
    new_cylinder(client, users["OPERADOR"], "Q-2", gases["O2-MED"])
    for s in ("Q-1", "Q-2"):
        r = client.post("/api/movements", headers=users["OPERADOR"],
                        json={"serial": s, "type": "ENVASE", "lot_id": lot["id"], "checklist": CHECKLIST_OK})
        assert r.status_code == 201, r.text
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "Q-1", "type": "ENTREGA", "customer_id": customer["id"]})
    return lot


def test_full_capa_cycle_with_recall(client, users, gases, customer):
    lot = _setup_medicinal(client, users, gases, customer)
    me = {r: client.get("/api/auth/me", headers=users[r]).json() for r in ("GESTOR", "OPERADOR", "MOTORISTA")}

    # motorista registra reclamação vinda do cliente; NC exige lote/cilindro
    bad = client.post("/api/quality/occurrences", headers=users["MOTORISTA"], json={
        "kind": "NAO_CONFORMIDADE", "severity": "MEDIA", "title": "Sem lote", "description": "Descrição suficiente aqui"})
    assert bad.status_code == 422
    r = client.post("/api/quality/occurrences", headers=users["MOTORISTA"], json={
        "kind": "EVENTO_ADVERSO", "severity": "BAIXA", "title": "Odor no oxigênio",
        "description": "Cliente relatou odor estranho ao abrir a válvula do cilindro.",
        "customer_id": customer["id"], "serial": "GC1:Q-1"})
    assert r.status_code == 201, r.text
    occ = r.json()
    assert occ["severity"] == "ALTA"                      # evento adverso nunca abaixo de ALTA
    assert occ["lot"]["id"] == lot["id"]                  # lote herdado do cilindro
    assert occ["code"].startswith("OC-") and occ["due_date"] == (date.today() + timedelta(days=7)).isoformat()
    oid = occ["id"]

    # outro motorista não vê; operador não bloqueia lote
    assert client.get(f"/api/quality/occurrences/{oid}", headers=users["MOTORISTA"]).status_code == 200
    assert client.post(f"/api/quality/occurrences/{oid}/block-lot", headers=users["OPERADOR"],
                       json={"signature_password": PWD}).status_code == 403

    # recall: gestor bloqueia o lote com assinatura -> entrega e envase do lote bloqueados
    r = client.post(f"/api/quality/occurrences/{oid}/block-lot", headers=users["GESTOR"], json={"signature_password": PWD})
    assert r.status_code == 200 and r.json()["lot_blocked"] is True
    r = client.post("/api/movements", headers=users["MOTORISTA"],
                    json={"serial": "Q-2", "type": "ENTREGA", "customer_id": customer["id"]})
    assert r.status_code == 422 and "bloqueado" in r.json()["message"]

    # investigação
    client.post(f"/api/quality/occurrences/{oid}/investigate", headers=users["GESTOR"],
                json={"owner_id": me["OPERADOR"]["id"]})
    assert client.post(f"/api/quality/occurrences/{oid}/effectiveness", headers=users["GESTOR"]).status_code == 422
    r = client.put(f"/api/quality/occurrences/{oid}/root-cause", headers=users["OPERADOR"],
                   json={"root_cause": "Purga insuficiente após manutenção da válvula."})
    assert r.status_code == 200
    r = client.post(f"/api/quality/occurrences/{oid}/actions", headers=users["GESTOR"], json={
        "kind": "CORRETIVA", "description": "Revisar POP de purga e retreinar operadores.",
        "responsible_id": me["OPERADOR"]["id"], "due_date": TOMORROW})
    action_id = r.json()["actions"][0]["id"]
    # motorista não conclui ação de outro
    assert client.post(f"/api/quality/actions/{action_id}/complete", headers=users["MOTORISTA"],
                       json={"evidence": "Feito conforme combinado."}).status_code == 403
    assert client.post(f"/api/quality/occurrences/{oid}/effectiveness", headers=users["GESTOR"]).status_code == 422
    r = client.post(f"/api/quality/actions/{action_id}/complete", headers=users["OPERADOR"],
                    json={"evidence": "POP-07 rev.3 publicado; 4 operadores treinados (lista anexa)."})
    assert r.json()["actions"][0]["status"] == "CONCLUIDA"
    r = client.post(f"/api/quality/occurrences/{oid}/effectiveness", headers=users["GESTOR"])
    assert r.json()["status"] == "AGUARDANDO_EFICACIA"

    # não encerra com lote bloqueado; liberação devolve à quarentena (exige nova decisão do RT)
    close = {"text": "30 dias sem recorrência em 120 envases auditados.", "signature_password": PWD}
    r = client.post(f"/api/quality/occurrences/{oid}/close", headers=users["GESTOR"], json=close)
    assert r.status_code == 422 and "bloqueado" in r.json()["message"]
    r = client.post(f"/api/quality/occurrences/{oid}/release-lot", headers=users["GESTOR"],
                    json={"text": "Análise de contraprova conforme.", "signature_password": PWD})
    assert r.status_code == 200
    lots = {l["id"]: l for l in client.get("/api/lots", headers=users["GESTOR"]).json()}
    assert lots[lot["id"]]["status"] == "QUARENTENA" and lots[lot["id"]]["signature_hash"] is None

    assert client.post(f"/api/quality/occurrences/{oid}/close", headers=users["GESTOR"],
                       json={**close, "signature_password": "errada"}).status_code == 403
    r = client.post(f"/api/quality/occurrences/{oid}/close", headers=users["GESTOR"], json=close)
    assert r.status_code == 200 and r.json()["status"] == "ENCERRADA" and len(r.json()["closing_signature_hash"]) == 64

    events = client.get("/api/audit/events?entity=ocorrencia", headers=users["GESTOR"]).json()
    assert {"ABRIR", "INVESTIGAR", "CAUSA_RAIZ", "ACAO_CRIAR", "ACAO_CONCLUIR", "AGUARDAR_EFICACIA",
            "ENCERRAR_ASSINADO"} <= {e["action"] for e in events}
    assert client.get("/api/audit/verify", headers=users["GESTOR"]).json()["ok"] is True


def test_motorista_only_sees_own_occurrences(client, users, admin, customer):
    body = {"kind": "RECLAMACAO", "severity": "BAIXA", "title": "Atraso na entrega",
            "description": "Cliente reclamou de atraso de 3 horas.", "customer_id": customer["id"]}
    oid = client.post("/api/quality/occurrences", headers=users["GESTOR"], json=body).json()["id"]
    client.post("/api/quality/occurrences", headers=users["MOTORISTA"], json=body)
    assert client.get(f"/api/quality/occurrences/{oid}", headers=users["MOTORISTA"]).status_code == 404
    assert len(client.get("/api/quality/occurrences", headers=users["MOTORISTA"]).json()) == 1
    assert len(client.get("/api/quality/occurrences", headers=users["GESTOR"]).json()) == 2


def test_cancel_and_reopen_rules(client, users, customer):
    me = client.get("/api/auth/me", headers=users["OPERADOR"]).json()
    body = {"kind": "DESVIO", "severity": "CRITICA", "title": "Envase sem checklist",
            "description": "Lote envasado sem registro de inspeção."}
    oid = client.post("/api/quality/occurrences", headers=users["OPERADOR"], json=body).json()["id"]
    assert client.post(f"/api/quality/occurrences/{oid}/cancel", headers=users["GESTOR"],
                       json={"text": "curto", "signature_password": PWD}).status_code == 422
    client.post(f"/api/quality/occurrences/{oid}/investigate", headers=users["GESTOR"], json={})
    client.put(f"/api/quality/occurrences/{oid}/root-cause", headers=users["GESTOR"],
               json={"root_cause": "Sistema antigo permitia envase sem checklist."})
    a = client.post(f"/api/quality/occurrences/{oid}/actions", headers=users["GESTOR"], json={
        "kind": "PREVENTIVA", "description": "Tornar checklist obrigatório no sistema.",
        "responsible_id": me["id"], "due_date": TOMORROW}).json()["actions"][0]["id"]
    client.post(f"/api/quality/actions/{a}/complete", headers=users["OPERADOR"],
                json={"evidence": "GasControl v2 bloqueia envase sem checklist."})
    client.post(f"/api/quality/occurrences/{oid}/effectiveness", headers=users["GESTOR"])
    # na verificação de eficácia não se cancela; pode reabrir
    assert client.post(f"/api/quality/occurrences/{oid}/cancel", headers=users["GESTOR"],
                       json={"text": "Registro duplicado por engano.", "signature_password": PWD}).status_code == 422
    r = client.post(f"/api/quality/occurrences/{oid}/reopen", headers=users["GESTOR"],
                    json={"reason": "Recorrência observada na semana seguinte."})
    assert r.json()["status"] == "EM_INVESTIGACAO"
    # ação concluída é imutável
    assert client.post(f"/api/quality/actions/{a}/complete", headers=users["OPERADOR"],
                       json={"evidence": "Tentando concluir de novo."}).status_code == 409
    dash = client.get("/api/dashboard", headers=users["GESTOR"]).json()
    assert dash["quality"]["open_by_severity"] == {"CRITICA": 1}
