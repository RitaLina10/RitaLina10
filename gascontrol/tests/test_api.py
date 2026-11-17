from datetime import date, timedelta

from sqlalchemy import text

from tests.conftest import CHECKLIST_OK, PWD, approved_lot, new_cylinder


def test_health_ready_metrics(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    m = client.get("/metrics")
    assert m.status_code == 200 and "gascontrol_http_requests_total" in m.text
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Request-ID"]


def test_auth_required_and_bad_token(client):
    assert client.get("/api/cylinders").status_code == 401
    assert client.get("/api/cylinders", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_login_lockout(client):
    for _ in range(3):
        assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Admin-Pass-123!"})
    assert r.status_code == 429


def test_weak_password_rejected(client, admin):
    r = client.post("/api/users", headers=admin, json={"email": "x@example.com", "name": "X",
                                                       "password": "aaaaaaaaaa", "role": "MOTORISTA"})
    assert r.status_code == 422


def test_role_enforcement(client, users, gases):
    r = client.post("/api/cylinders", headers=users["MOTORISTA"], json={
        "serial": "X-1", "gas_type_id": gases["O2-IND"], "capacity_liters": 10, "last_hydro_test": "2025-01-01"})
    assert r.status_code == 403
    assert client.get("/api/users", headers=users["GESTOR"]).status_code == 403
    assert client.get("/api/dashboard", headers=users["MOTORISTA"]).status_code == 403


def test_medicinal_full_cycle_with_traceability(client, users, gases, customer):
    gid = gases["O2-MED"]
    new_cylinder(client, users["OPERADOR"], "med-001", gid)

    # envase medicinal sem lote é bloqueado
    r = client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "MED-001", "type": "ENVASE"})
    assert r.status_code == 422 and r.json()["error"] == "compliance_violation"

    # lote em quarentena: envase permitido, entrega bloqueada até aprovação
    today = date.today()
    lot = client.post("/api/lots", headers=users["OPERADOR"], json={
        "code": "Q-1", "gas_type_id": gid, "production_date": today.isoformat(),
        "expiry_date": (today + timedelta(days=365)).isoformat(), "analysis_report": "LA-1"}).json()
    assert lot["status"] == "QUARENTENA"
    r = client.post("/api/movements", headers=users["OPERADOR"],
                    json={"serial": "GC1:MED-001", "type": "ENVASE", "lot_id": lot["id"],
                          "checklist": CHECKLIST_OK})
    assert r.status_code == 201, r.text
    r = client.post("/api/movements", headers=users["MOTORISTA"],
                    json={"serial": "MED-001", "type": "ENTREGA", "customer_id": customer["id"]})
    assert r.status_code == 422 and "Lote" in r.json()["message"]

    # operador não pode liberar lote; gestor pode
    sign = {"approve": True, "signature_password": PWD}
    assert client.post(f"/api/lots/{lot['id']}/decision", headers=users["OPERADOR"], json=sign).status_code == 403
    assert client.post(f"/api/lots/{lot['id']}/decision", headers=users["GESTOR"],
                       json={**sign, "signature_password": "errada"}).status_code == 403
    r = client.post(f"/api/lots/{lot['id']}/decision", headers=users["GESTOR"], json=sign)
    assert r.status_code == 200 and len(r.json()["signature_hash"]) == 64

    r = client.post("/api/movements", headers=users["MOTORISTA"], json={
        "serial": "MED-001", "type": "ENTREGA", "customer_id": customer["id"], "is_loan": True,
        "document_ref": "NFE-123", "latitude": -23.55, "longitude": -46.63})
    assert r.status_code == 201, r.text
    assert r.json()["to_status"] == "EM_CLIENTE"

    # motorista não envasa
    assert client.post("/api/movements", headers=users["MOTORISTA"],
                       json={"serial": "MED-001", "type": "ENVASE", "lot_id": lot["id"]}).status_code == 403

    # saldo do cliente / dashboard
    dash = client.get("/api/dashboard", headers=users["GESTOR"]).json()
    assert dash["by_status"]["EM_CLIENTE"] == 1
    assert dash["customer_balance"][0] == {"customer_id": customer["id"], "customer": "Hospital Teste",
                                           "cylinders": 1, "loans": 1}

    # recall do lote encontra o cliente
    trace = client.get(f"/api/lots/{lot['id']}/trace", headers=users["GESTOR"]).json()
    assert [m["type"] for m in trace["movements"]] == ["ENVASE", "ENTREGA"]
    assert trace["movements"][1]["customer"]["id"] == customer["id"]

    # coleta
    r = client.post("/api/movements", headers=users["MOTORISTA"],
                    json={"serial": "MED-001", "type": "COLETA", "customer_id": customer["id"]})
    assert r.status_code == 201
    hist = client.get("/api/cylinders/MED-001/history", headers=users["GESTOR"]).json()
    assert [m["type"] for m in hist["movements"]] == ["CADASTRO", "ENVASE", "ENTREGA", "COLETA"]
    assert hist["cylinder"]["current_customer"] is None

    # motorista só vê as próprias movimentações
    mine = client.get("/api/movements", headers=users["MOTORISTA"]).json()
    assert {m["user"]["name"] for m in mine} == {"Motorista"}


def test_exchange_is_atomic(client, users, gases, customer, admin):
    gid = gases["O2-IND"]
    for s in ("IND-1", "IND-2"):
        new_cylinder(client, users["OPERADOR"], s, gid)
        client.post("/api/movements", headers=users["OPERADOR"], json={"serial": s, "type": "ENVASE"})
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "IND-1", "type": "ENTREGA", "customer_id": customer["id"]})
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "IND-1", "type": "COLETA", "customer_id": customer["id"]})

    # IND-1 já está vazio na base -> a troca falha e IND-2 NÃO pode sair
    r = client.post("/api/movements/exchange", headers=users["MOTORISTA"], json={
        "full_serial": "IND-2", "empty_serial": "IND-1", "customer_id": customer["id"]})
    assert r.status_code == 422
    assert client.get("/api/cylinders/IND-2", headers=admin).json()["status"] == "CHEIO"

    client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "IND-1", "type": "ENVASE"})
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "IND-1", "type": "ENTREGA", "customer_id": customer["id"]})
    r = client.post("/api/movements/exchange", headers=users["MOTORISTA"], json={
        "full_serial": "IND-2", "empty_serial": "IND-1", "customer_id": customer["id"], "is_loan": True})
    assert r.status_code == 201, r.text
    d, c = r.json()
    assert d["operation_id"] == c["operation_id"]
    assert client.get("/api/cylinders/IND-1", headers=admin).json()["status"] == "VAZIO"
    assert client.get("/api/cylinders/IND-2", headers=admin).json()["current_customer"]["id"] == customer["id"]


def test_collect_from_wrong_customer_rejected(client, users, gases, customer, admin):
    other = client.post("/api/customers", headers=admin, json={"name": "Outro", "document": "529.982.247-25"}).json()
    new_cylinder(client, users["OPERADOR"], "IND-9", gases["N2-IND"])
    client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "IND-9", "type": "ENVASE"})
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "IND-9", "type": "ENTREGA", "customer_id": customer["id"]})
    r = client.post("/api/movements", headers=users["MOTORISTA"],
                    json={"serial": "IND-9", "type": "COLETA", "customer_id": other["id"]})
    assert r.status_code == 409


def test_hydro_expired_blocks_fill_and_alerts(client, users, gases):
    old = (date.today() - timedelta(days=5 * 366 + 2)).isoformat()
    new_cylinder(client, users["OPERADOR"], "OLD-1", gases["AR-IND"], last_test=old)
    r = client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "OLD-1", "type": "ENVASE"})
    assert r.status_code == 422 and "hidrostático" in r.json()["message"]
    alerts = client.get("/api/dashboard", headers=users["GESTOR"]).json()["hydro_alerts"]
    assert alerts[0]["serial"] == "OLD-1" and alerts[0]["expired"] is True

    # manutenção com novo teste libera o cilindro
    client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "OLD-1", "type": "ENVIO_MANUTENCAO"})
    r = client.post("/api/movements", headers=users["OPERADOR"], json={
        "serial": "OLD-1", "type": "RETORNO_MANUTENCAO", "new_hydro_test": date.today().isoformat()})
    assert r.status_code == 201
    assert client.post("/api/movements", headers=users["OPERADOR"],
                       json={"serial": "OLD-1", "type": "ENVASE"}).status_code == 201


def test_lot_gas_mismatch(client, users, gases):
    lot = approved_lot(client, users, gases["O2-MED"])
    new_cylinder(client, users["OPERADOR"], "AR-1", gases["AR-MED"])
    r = client.post("/api/movements", headers=users["OPERADOR"],
                    json={"serial": "AR-1", "type": "ENVASE", "lot_id": lot["id"], "checklist": CHECKLIST_OK})
    assert r.status_code == 422


def test_audit_chain_detects_tampering(client, users, gases, customer):
    new_cylinder(client, users["OPERADOR"], "AUD-1", gases["O2-IND"])
    client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "AUD-1", "type": "ENVASE"})
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "AUD-1", "type": "ENTREGA", "customer_id": customer["id"], "document_ref": "NF-1"})
    ok = client.get("/api/audit/verify", headers=users["GESTOR"]).json()
    assert ok["ok"] is True and ok["movements_checked"] == 3

    engine = client.app.state.container.auth._uow().__enter__().session.get_bind()
    with engine.begin() as conn:
        conn.execute(text("UPDATE movements SET document_ref = 'NF-FAKE' WHERE document_ref = 'NF-1'"))
    bad = client.get("/api/audit/verify", headers=users["GESTOR"]).json()
    assert bad["ok"] is False and bad["broken"][0]["movement_id"] is not None


def test_input_validation(client, admin, gases):
    assert client.post("/api/customers", headers=admin, json={"name": "X Y", "document": "123"}).status_code == 422
    assert client.post("/api/cylinders", headers=admin, json={
        "serial": "<script>", "gas_type_id": gases["O2-IND"], "capacity_liters": 1,
        "last_hydro_test": "2025-01-01"}).status_code == 422
    assert client.post("/api/movements", headers=admin, json={"serial": "A-1", "type": "CADASTRO"}).status_code == 422
    assert client.post("/api/customers", headers=admin, json={
        "name": "X Y", "document": "529.982.247-25", "extra": 1}).status_code == 422
    r = client.get("/api/customers?q=%25_", headers=admin)
    assert r.status_code == 200 and r.json() == []


def test_qr_and_duplicate_serial(client, users, gases):
    new_cylinder(client, users["OPERADOR"], "QR-1", gases["O2-IND"])
    r = client.get("/api/cylinders/QR-1/qr.png", headers=users["MOTORISTA"])
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    r = client.post("/api/cylinders", headers=users["OPERADOR"], json={
        "serial": "qr-1", "gas_type_id": gases["O2-IND"], "capacity_liters": 10, "last_hydro_test": "2025-01-01"})
    assert r.status_code == 409


def test_deactivated_user_loses_access(client, users, admin):
    me = client.get("/api/auth/me", headers=users["MOTORISTA"]).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"active": False}).status_code == 200
    assert client.get("/api/cylinders", headers=users["MOTORISTA"]).status_code == 401


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "PB Gas Control" in r.text
