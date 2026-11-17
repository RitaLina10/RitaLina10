"""Segurança e LGPD: revogação de sessão, limites, CORS, métricas e direitos do titular."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ADMIN, PWD, login

CUSTOMER = {"name": "Maria Titular", "document": "52998224725", "phone": "11999990000",
            "email": "maria@example.com", "city": "Santos", "uf": "SP"}


def test_password_change_revokes_old_sessions(client, admin):
    other_device = login(client, *ADMIN)
    r = client.post("/api/auth/password", headers=admin,
                    json={"current_password": ADMIN[1], "new_password": "Outra-Senha-789"})
    assert r.status_code == 200, r.text
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=fresh).status_code == 200
    assert client.get("/api/auth/me", headers=other_device).status_code == 401
    assert client.get("/api/auth/me", headers=admin).status_code == 401
    assert client.post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}).status_code == 401


def test_password_change_rules(client, admin):
    bad = client.post("/api/auth/password", headers=admin,
                      json={"current_password": "errada", "new_password": "Outra-Senha-789"})
    assert bad.status_code == 403
    weak = client.post("/api/auth/password", headers=admin,
                       json={"current_password": ADMIN[1], "new_password": "aaaaaaaaaaaa"})
    assert weak.status_code == 422
    for _ in range(3):
        client.post("/api/auth/password", headers=admin, json={"current_password": "x", "new_password": "Outra-Senha-789"})
    locked = client.post("/api/auth/password", headers=admin,
                         json={"current_password": ADMIN[1], "new_password": "Outra-Senha-789"})
    assert locked.status_code == 429


def test_forged_and_alg_none_tokens_rejected(client, admin):
    now = datetime.now(timezone.utc)
    claims = {"sub": "1", "role": "ADMIN", "iat": now, "exp": now + timedelta(hours=1), "iss": "gascontrol"}
    forged = jwt.encode(claims, "chave-errada" * 4, algorithm="HS256")
    none_tok = jwt.encode(claims, key=None, algorithm="none")
    for tok in (forged, none_tok, "abc.def.ghi", ""):
        assert client.get("/api/users", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_body_size_limit(client, admin):
    big = "x" * (2 * 1024 * 1024 + 10)
    r = client.post("/api/customers", headers={**admin, "Content-Type": "application/json"},
                    content=('{"name":"' + big + '"}').encode())
    assert r.status_code == 413


def test_cors_closed_list(client):
    ok = client.options("/api/auth/login", headers={"Origin": "https://appassets.androidplatform.net",
                                                    "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://appassets.androidplatform.net"
    evil = client.options("/api/auth/login", headers={"Origin": "https://evil.example",
                                                      "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers
    simple = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_metrics_local_only_in_production(tmp_path):
    settings = Settings(env="production", database_url=f"sqlite:///{tmp_path}/p.db", jwt_secret="y" * 48,
                        log_level="WARNING", fiscal_poll_seconds=0)
    with TestClient(create_app(settings)) as c:  # cliente de teste = host "testclient" (não loopback)
        assert c.get("/metrics").status_code == 404
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        h = c.get("/health").headers
        assert "max-age" in h["strict-transport-security"]
        assert h["x-frame-options"] == "DENY" and "default-src 'self'" in h["content-security-policy"]


def test_static_path_traversal(client):
    for path in ("/static/../config.py", "/static/%2e%2e/config.py", "/static/..%2fmain.py"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "JWT_SECRET" not in r.text


def test_lgpd_export_admin_only_and_audited(client, users):
    cid = client.post("/api/customers", headers=users["GESTOR"], json=CUSTOMER).json()["id"]
    for role in ("GESTOR", "OPERADOR", "MOTORISTA"):
        assert client.get(f"/api/privacy/customers/{cid}/export", headers=users[role]).status_code == 403
    r = client.get(f"/api/privacy/customers/{cid}/export", headers=users["ADMIN"])
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["titular"]["documento"] == "52998224725" and data["titular"]["email"] == "maria@example.com"
    events = client.get("/api/audit/events?limit=50", headers=users["ADMIN"]).json()
    assert any(e["action"] == "EXPORTAR_DADOS_TITULAR" for e in events)


def test_lgpd_anonymize_requires_signature_and_respects_retention(client, users, fake_gw):
    admin = users["ADMIN"]
    cid = client.post("/api/customers", headers=users["GESTOR"], json=CUSTOMER).json()["id"]
    assert client.post(f"/api/privacy/customers/{cid}/anonymize", headers=admin,
                       json={"password": "errada"}).status_code == 403
    assert client.post(f"/api/privacy/customers/{cid}/anonymize", headers=users["GESTOR"],
                       json={"password": PWD}).status_code == 403
    r = client.post(f"/api/privacy/customers/{cid}/anonymize", headers=admin, json={"password": ADMIN[1]})
    assert r.status_code == 204, r.text
    c = client.get(f"/api/customers/{cid}", headers=admin).json()
    assert c["document"].startswith("ANON") and c["email"] is None and c["phone"] is None and not c["active"]
    assert "Maria" not in c["name"]
    again = client.post(f"/api/privacy/customers/{cid}/anonymize", headers=admin, json={"password": ADMIN[1]})
    assert again.status_code == 409


def test_lgpd_anonymize_blocked_by_legal_retention(client, users):
    admin = users["ADMIN"]
    cid = client.post("/api/customers", headers=users["GESTOR"], json=CUSTOMER).json()["id"]
    gas = client.get("/api/gas-types", headers=admin).json()
    ind = next(g for g in gas if g["code"] == "CO2-IND")
    serial = "LGPD-1"
    assert client.post("/api/cylinders", headers=admin, json={
        "serial": serial, "gas_type_id": ind["id"], "capacity_liters": 40,
        "last_hydro_test": datetime.now().date().isoformat()}).status_code == 201
    from tests.conftest import CHECKLIST_OK
    client.post("/api/movements", headers=admin, json={"serial": serial, "type": "ENVASE", "checklist": CHECKLIST_OK})
    d = client.post("/api/movements", headers=admin, json={"serial": serial, "type": "ENTREGA", "customer_id": cid})
    assert d.status_code == 201, d.text
    held = client.post(f"/api/privacy/customers/{cid}/anonymize", headers=admin, json={"password": ADMIN[1]})
    assert held.status_code == 409 and "cilindros" in held.json()["message"]
    client.post("/api/movements", headers=admin, json={"serial": serial, "type": "COLETA", "customer_id": cid})
    kept = client.post(f"/api/privacy/customers/{cid}/anonymize", headers=admin, json={"password": ADMIN[1]})
    assert kept.status_code == 409 and "art. 16" in kept.json()["message"]


def test_huge_ids_rejected_without_500(client, admin):
    huge = "99999999999999999999999"
    for path in (f"/api/customers/{huge}", f"/api/lots/{huge}/trace", f"/api/fiscal/invoices/{huge}",
                 f"/api/quality/occurrences/{huge}", f"/api/cylinders?customer_id={huge}", f"/api/movements?offset={huge}"):
        r = client.get(path, headers=admin)
        assert r.status_code == 422, (path, r.status_code)
    r = client.post("/api/lots", headers=admin, json={"code": "L-OVF", "gas_type_id": int(huge)})
    assert r.status_code == 422
