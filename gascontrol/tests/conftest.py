from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ADMIN = ("admin@example.com", "Admin-Pass-123!")
PWD = "Strong-Pass-123!"


@pytest.fixture()
def client(tmp_path):
    settings = Settings(env="test", database_url=f"sqlite:///{tmp_path}/t.db", jwt_secret="x" * 48,
                        admin_email=ADMIN[0], admin_password=ADMIN[1], log_level="WARNING",
                        login_max_attempts=3, login_lockout_seconds=60)
    with TestClient(create_app(settings)) as c:
        yield c


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client, *ADMIN)


@pytest.fixture()
def users(client, admin):
    out = {}
    for role in ("GESTOR", "OPERADOR", "MOTORISTA"):
        email = f"{role.lower()}@example.com"
        r = client.post("/api/users", headers=admin, json={"email": email, "name": role.title(),
                                                            "password": PWD, "role": role})
        assert r.status_code == 201, r.text
        out[role] = login(client, email, PWD)
    out["ADMIN"] = admin
    return out


@pytest.fixture()
def gases(client, admin):
    return {g["code"]: g["id"] for g in client.get("/api/gas-types", headers=admin).json()}


@pytest.fixture()
def customer(client, admin):
    r = client.post("/api/customers", headers=admin,
                    json={"name": "Hospital Teste", "document": "11.222.333/0001-81", "is_health_facility": True})
    assert r.status_code == 201, r.text
    return r.json()


def recent_test_date() -> str:
    return (date.today() - timedelta(days=365)).isoformat()


def new_cylinder(client, headers, serial, gas_id, last_test=None):
    r = client.post("/api/cylinders", headers=headers, json={
        "serial": serial, "gas_type_id": gas_id, "capacity_liters": 50,
        "last_hydro_test": last_test or recent_test_date()})
    assert r.status_code == 201, r.text
    return r.json()


def approved_lot(client, users, gas_id, code="L-001"):
    today = date.today()
    r = client.post("/api/lots", headers=users["OPERADOR"], json={
        "code": code, "gas_type_id": gas_id, "production_date": today.isoformat(),
        "expiry_date": (today + timedelta(days=730)).isoformat(), "purity_percent": 99.5,
        "analysis_report": "LA-2026-001"})
    assert r.status_code == 201, r.text
    lot = r.json()
    r = client.post(f"/api/lots/{lot['id']}/decision", headers=users["GESTOR"],
                    json={"approve": True, "signature_password": PWD})
    assert r.status_code == 200, r.text
    return r.json()


CHECKLIST_OK = {"inspecao_visual": True, "valvula": True, "identificacao": True, "cor_padrao": True,
                "purga_vacuo": True}
