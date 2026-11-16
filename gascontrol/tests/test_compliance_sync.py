import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from app.infra.db import upgrade_schema
from tests.conftest import CHECKLIST_OK, approved_lot, new_cylinder


def _now(minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _filled_industrial(client, users, serial, gases):
    new_cylinder(client, users["OPERADOR"], serial, gases["O2-IND"])
    r = client.post("/api/movements", headers=users["OPERADOR"], json={"serial": serial, "type": "ENVASE"})
    assert r.status_code == 201, r.text


def test_medicinal_fill_requires_checklist(client, users, gases):
    lot = approved_lot(client, users, gases["O2-MED"])
    new_cylinder(client, users["OPERADOR"], "CK-1", gases["O2-MED"])
    base = {"serial": "CK-1", "type": "ENVASE", "lot_id": lot["id"]}
    r = client.post("/api/movements", headers=users["OPERADOR"], json=base)
    assert r.status_code == 422 and "checklist" in r.json()["message"]
    r = client.post("/api/movements", headers=users["OPERADOR"],
                    json={**base, "checklist": {**CHECKLIST_OK, "valvula": False}})
    assert r.status_code == 422 and "Válvula" in r.json()["message"]
    r = client.post("/api/movements", headers=users["OPERADOR"], json={**base, "checklist": {"x": True}})
    assert r.status_code == 422
    r = client.post("/api/movements", headers=users["OPERADOR"], json={**base, "checklist": CHECKLIST_OK})
    assert r.status_code == 201 and '"valvula": true' in r.json()["checklist"]


def test_offline_sync_idempotent_and_ordered(client, users, gases, customer, admin):
    _filled_industrial(client, users, "OFF-1", gases)
    deliver = {"client_uuid": str(uuid.uuid4()), "kind": "movement", "occurred_at": _now(-30),
               "payload": {"serial": "GC1:OFF-1", "type": "ENTREGA", "customer_id": customer["id"],
                           "document_ref": "NF-9"}}
    collect = {"client_uuid": str(uuid.uuid4()), "kind": "movement", "occurred_at": _now(-10),
               "payload": {"serial": "OFF-1", "type": "COLETA", "customer_id": customer["id"]}}
    # enviados fora de ordem: servidor reordena pelo horário do campo
    r = client.post("/api/sync/batch", headers=users["MOTORISTA"], json={"items": [collect, deliver]})
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()] == ["ok", "ok"]

    # reenvio (ex.: resposta perdida) não duplica
    r = client.post("/api/sync/batch", headers=users["MOTORISTA"], json={"items": [deliver, collect]})
    assert [x["status"] for x in r.json()] == ["duplicate", "duplicate"]
    hist = client.get("/api/cylinders/OFF-1/history", headers=admin).json()["movements"]
    assert [m["type"] for m in hist] == ["CADASTRO", "ENVASE", "ENTREGA", "COLETA"]
    assert hist[2]["offline"] is True and hist[2]["client_occurred_at"] is not None

    # outro usuário não pode "reaproveitar" o recibo
    r = client.post("/api/sync/batch", headers=users["OPERADOR"], json={"items": [deliver]})
    assert r.json()[0]["status"] == "rejected"


def test_offline_conflict_is_reported_not_lost(client, users, gases, customer):
    _filled_industrial(client, users, "OFF-2", gases)
    # cilindro já entregue por outra via enquanto o motorista estava offline
    client.post("/api/movements", headers=users["GESTOR"],
                json={"serial": "OFF-2", "type": "ENTREGA", "customer_id": customer["id"]})
    item = {"client_uuid": str(uuid.uuid4()), "kind": "movement", "occurred_at": _now(-5),
            "payload": {"serial": "OFF-2", "type": "ENTREGA", "customer_id": customer["id"]}}
    res = client.post("/api/sync/batch", headers=users["MOTORISTA"], json={"items": [item]}).json()[0]
    assert res["status"] == "rejected" and res["error"] == "invalid_transition" and res["retryable"] is False


def test_offline_exchange_and_time_validation(client, users, gases, customer):
    _filled_industrial(client, users, "EX-A", gases)
    _filled_industrial(client, users, "EX-B", gases)
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "EX-A", "type": "ENTREGA", "customer_id": customer["id"]})
    ex = {"client_uuid": str(uuid.uuid4()), "kind": "exchange", "occurred_at": _now(-1),
          "payload": {"full_serial": "EX-B", "empty_serial": "EX-A", "customer_id": customer["id"]}}
    future = {"client_uuid": str(uuid.uuid4()), "kind": "movement", "occurred_at": _now(60 * 24),
              "payload": {"serial": "EX-A", "type": "ENVIO_MANUTENCAO"}}
    res = client.post("/api/sync/batch", headers=users["MOTORISTA"], json={"items": [ex]}).json()
    assert res[0]["status"] == "ok" and len(res[0]["movement_ids"]) == 2
    res = client.post("/api/sync/batch", headers=users["OPERADOR"], json={"items": [future]}).json()
    assert res[0]["status"] == "rejected" and "futuro" in res[0]["message"]
    bad = client.post("/api/sync/batch", headers=users["MOTORISTA"],
                      json={"items": [{**ex, "client_uuid": "nao-e-uuid"}]})
    assert bad.status_code == 422


def test_snapshot_for_offline(client, users, gases, customer):
    _filled_industrial(client, users, "SN-1", gases)
    snap = client.get("/api/sync/snapshot", headers=users["MOTORISTA"]).json()
    assert snap["cylinders"][0]["serial"] == "SN-1" and snap["cylinders"][0]["status"] == "CHEIO"
    assert snap["customers"][0]["id"] == customer["id"]
    assert "valvula" in snap["checklist"]


def test_audit_trail_of_registrations(client, users, gases, customer, admin):
    client.patch(f"/api/customers/{customer['id']}", headers=users["GESTOR"], json={"phone": "11 9999-0000"})
    approved_lot(client, users, gases["O2-MED"], code="AUD-L")
    events = client.get("/api/audit/events", headers=users["GESTOR"]).json()
    actions = {(e["action"], e["entity"]) for e in events}
    assert {("CRIAR", "cliente"), ("ALTERAR", "cliente"), ("CRIAR", "lote"), ("ASSINAR_APROVADO", "lote"),
            ("CRIAR", "usuario")} <= actions
    assert client.get("/api/audit/events", headers=users["OPERADOR"]).status_code == 403
    v = client.get("/api/audit/verify", headers=users["GESTOR"]).json()
    assert v["ok"] and v["audit_events_checked"] == len(events)

    engine = client.app.state.container.auth._uow().__enter__().session.get_bind()
    with engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET data = '{}' WHERE action = 'ALTERAR'"))
    v = client.get("/api/audit/verify", headers=users["GESTOR"]).json()
    assert v["ok"] is False and v["audit_broken_event_id"] is not None


def test_lot_dossier_csv_is_injection_safe(client, users, gases, customer, admin):
    lot = approved_lot(client, users, gases["O2-MED"], code="CSV-1")
    new_cylinder(client, users["OPERADOR"], "CSV-C", gases["O2-MED"])
    client.post("/api/movements", headers=users["OPERADOR"], json={
        "serial": "CSV-C", "type": "ENVASE", "lot_id": lot["id"], "checklist": CHECKLIST_OK,
        "notes": "=HYPERLINK(\"http://evil\")"})
    r = client.get(f"/api/lots/{lot['id']}/dossier.csv", headers=users["GESTOR"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body and "CSV-C" in body and "dossie-lote-CSV-1" in r.headers["content-disposition"]
    assert client.get(f"/api/lots/{lot['id']}/dossier.csv", headers=users["MOTORISTA"]).status_code == 403


def test_signature_lockout(client, users, gases):
    today = date.today()
    lot = client.post("/api/lots", headers=users["OPERADOR"], json={
        "code": "LCK", "gas_type_id": gases["O2-IND"], "production_date": today.isoformat(),
        "expiry_date": (today + timedelta(days=30)).isoformat()}).json()
    for _ in range(3):
        r = client.post(f"/api/lots/{lot['id']}/decision", headers=users["GESTOR"],
                        json={"approve": True, "signature_password": "x"})
        assert r.status_code == 403
    r = client.post(f"/api/lots/{lot['id']}/decision", headers=users["GESTOR"],
                    json={"approve": True, "signature_password": "x"})
    assert r.status_code == 429


def test_upgrade_schema_adds_columns_to_old_db(tmp_path):
    url = f"sqlite:///{tmp_path}/old.db"
    eng = create_engine(url)
    upgrade_schema(eng)
    with eng.begin() as conn:  # simula banco criado pela v1 (sem as colunas novas)
        conn.execute(text("ALTER TABLE lots DROP COLUMN signature_hash"))
        conn.execute(text("ALTER TABLE movements DROP COLUMN checklist"))
    added = upgrade_schema(eng)
    assert set(added) == {"lots.signature_hash", "movements.checklist"}
    assert upgrade_schema(eng) == []


def test_backup_tool(tmp_path):
    import sqlite3

    from app.tools.backup import run_backup
    db = tmp_path / "src.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    for _ in range(3):
        out = run_backup(db, tmp_path / "bk", keep=2)
    assert sqlite3.connect(out).execute("SELECT x FROM t").fetchone() == (1,)
    assert len(list((tmp_path / "bk").glob("*.db"))) <= 2
