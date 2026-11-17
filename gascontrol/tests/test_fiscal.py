import json
from decimal import Decimal

import httpx

from app.application.ports import FiscalResult
from app.infra.fiscal_gateway import CircuitBreaker, FocusNFeGateway
from tests.conftest import PWD, new_cylinder

PROFILE = {"description": "Oxigênio industrial - carga", "ncm": "2804.40.00", "cfop_internal": "5102",
           "cfop_interstate": "6102", "unit": "UN", "icms_cst": "00", "icms_rate": "18.00", "pis_cst": "01",
           "cofins_cst": "01", "origin": 0, "default_price": "150.00"}
ADDRESS = {"street": "Rua das Indústrias", "street_number": "100", "district": "Distrito Industrial",
           "city": "Campinas", "uf": "sp", "cep": "13000-000", "state_registration": "123.456.789.110",
           "email": "Compras@Cliente.com.br"}


def _ready(client, users, gases, customer):
    r = client.put(f"/api/fiscal/profiles/{gases['O2-IND']}", headers=users["GESTOR"], json=PROFILE)
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/customers/{customer['id']}", headers=users["GESTOR"], json=ADDRESS)
    assert r.status_code == 200 and r.json()["uf"] == "SP" and r.json()["cep"] == "13000000"


def test_profile_validation(client, users, gases):
    bad = {**PROFILE, "cfop_internal": "6102"}
    assert client.put(f"/api/fiscal/profiles/{gases['O2-IND']}", headers=users["GESTOR"], json=bad).status_code == 422
    assert client.put(f"/api/fiscal/profiles/{gases['O2-IND']}", headers=users["GESTOR"],
                      json={**PROFILE, "ncm": "123"}).status_code == 422
    assert client.put(f"/api/fiscal/profiles/{gases['O2-IND']}", headers=users["OPERADOR"], json=PROFILE).status_code == 403
    assert client.get("/api/fiscal/profiles", headers=users["MOTORISTA"]).status_code == 403


def test_invoice_from_delivery_emit_authorize_cancel(client, users, gases, customer, fake_gw):
    _ready(client, users, gases, customer)
    for s in ("NF-1", "NF-2"):
        new_cylinder(client, users["OPERADOR"], s, gases["O2-IND"])
        client.post("/api/movements", headers=users["OPERADOR"], json={"serial": s, "type": "ENVASE"})
    new_cylinder(client, users["OPERADOR"], "NF-3", gases["O2-IND"])
    client.post("/api/movements", headers=users["OPERADOR"], json={"serial": "NF-3", "type": "ENVASE"})
    client.post("/api/movements", headers=users["MOTORISTA"],
                json={"serial": "NF-3", "type": "ENTREGA", "customer_id": customer["id"]})
    ex = client.post("/api/movements/exchange", headers=users["MOTORISTA"], json={
        "full_serial": "NF-1", "empty_serial": "NF-3", "customer_id": customer["id"], "document_ref": "ROM-9"}).json()
    op = ex[0]["operation_id"]

    r = client.post("/api/fiscal/invoices/from-operation", headers=users["OPERADOR"], json={"operation_id": op})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "RASCUNHO" and Decimal(inv["total"]) == Decimal("150.00")
    assert "NF-1" in inv["notes"] and "ROM-9" in inv["notes"]
    assert client.post("/api/fiscal/invoices/from-operation", headers=users["OPERADOR"],
                       json={"operation_id": op}).status_code == 409

    # edita: 2 unidades a 155,50 -> 311,00
    r = client.put(f"/api/fiscal/invoices/{inv['id']}", headers=users["GESTOR"], json={
        "nature": "Venda de mercadoria", "notes": inv["notes"],
        "items": [{"gas_type_id": gases["O2-IND"], "quantity": "2", "unit_price": "155.50"}]})
    assert Decimal(r.json()["total"]) == Decimal("311.00")

    # operador não emite
    assert client.post(f"/api/fiscal/invoices/{inv['id']}/emit", headers=users["OPERADOR"]).status_code == 403
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/emit", headers=users["GESTOR"])
    assert r.status_code == 200 and r.json()["status"] == "PROCESSANDO"
    doc = fake_gw.emitted[0]
    assert doc.lines[0].cfop == "5102" and doc.lines[0].ncm == "28044000" and doc.customer.cep == "13000000"
    # não edita em processamento
    assert client.put(f"/api/fiscal/invoices/{inv['id']}", headers=users["GESTOR"], json={
        "nature": "X Y Z", "items": [{"gas_type_id": gases["O2-IND"], "quantity": "1"}]}).status_code == 422

    r = client.post(f"/api/fiscal/invoices/{inv['id']}/refresh", headers=users["GESTOR"])
    body = r.json()
    assert body["status"] == "AUTORIZADA" and body["number"] == "101" and len(body["access_key"]) == 44

    # cancelamento: justificativa >= 15, assinatura
    assert client.post(f"/api/fiscal/invoices/{inv['id']}/cancel", headers=users["GESTOR"],
                       json={"justification": "curta", "signature_password": PWD}).status_code == 422
    assert client.post(f"/api/fiscal/invoices/{inv['id']}/cancel", headers=users["GESTOR"],
                       json={"justification": "Erro no preço unitário informado", "signature_password": "x"}).status_code == 403
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/cancel", headers=users["GESTOR"],
                    json={"justification": "Erro no preço unitário informado", "signature_password": PWD})
    assert r.json()["status"] == "CANCELADA"
    actions = [e["action"] for e in client.get("/api/audit/events?entity=nota", headers=users["GESTOR"]).json()]
    assert {"RASCUNHO", "EMITIR", "STATUS_AUTORIZADA", "CANCELAR_SOLICITADO", "STATUS_CANCELADA"} <= set(actions)


def test_emit_requires_complete_customer_and_handles_outage(client, users, gases, customer, fake_gw):
    client.put(f"/api/fiscal/profiles/{gases['O2-IND']}", headers=users["GESTOR"], json=PROFILE)
    inv = client.post("/api/fiscal/invoices", headers=users["GESTOR"], json={
        "customer_id": customer["id"], "items": [{"gas_type_id": gases["O2-IND"], "quantity": "1"}]}).json()
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/emit", headers=users["GESTOR"])
    assert r.status_code == 422 and "incompleto" in r.json()["message"]

    client.patch(f"/api/customers/{customer['id']}", headers=users["GESTOR"], json={**ADDRESS, "uf": "RJ"})
    fake_gw.down = True
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/emit", headers=users["GESTOR"])
    assert r.status_code == 503
    assert client.get(f"/api/fiscal/invoices/{inv['id']}", headers=users["GESTOR"]).json()["status"] == "RASCUNHO"

    fake_gw.down = False
    fake_gw.next_emit = FiscalResult(status="rejected", message="Rejeição 225: Falha no Schema")
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/emit", headers=users["GESTOR"]).json()
    assert r["status"] == "REJEITADA" and "225" in r["provider_message"]
    assert fake_gw.emitted[-1].lines[0].cfop == "6102"   # interestadual SP -> RJ
    first_ref = r["ref"]
    fake_gw.next_emit = FiscalResult(status="processing")
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/emit", headers=users["GESTOR"]).json()
    assert r["status"] == "PROCESSANDO" and r["ref"] != first_ref   # nova ref após rejeição

    # nunca chegou ao emissor -> volta a rascunho para reenvio
    fake_gw.next_query = FiscalResult(status="not_found")
    r = client.post(f"/api/fiscal/invoices/{inv['id']}/refresh", headers=users["GESTOR"]).json()
    assert r["status"] == "RASCUNHO"


def test_price_required_without_profile_default(client, users, gases, customer):
    client.put(f"/api/fiscal/profiles/{gases['N2-IND']}", headers=users["GESTOR"],
               json={**PROFILE, "description": "Nitrogênio", "ncm": "28043000", "default_price": None})
    r = client.post("/api/fiscal/invoices", headers=users["GESTOR"], json={
        "customer_id": customer["id"], "items": [{"gas_type_id": gases["N2-IND"], "quantity": "1"}]})
    assert r.status_code == 422 and "preço" in r.json()["message"]
    r = client.post("/api/fiscal/invoices", headers=users["GESTOR"], json={
        "customer_id": customer["id"], "items": [{"gas_type_id": gases["AR-IND"], "quantity": "1", "unit_price": "1"}]})
    assert r.status_code == 422 and "perfil fiscal" in r.json()["message"]


# ---------------- adaptador Focus NFe (transporte simulado) ----------------

def _gw(handler, **kw):
    client = httpx.Client(base_url=FocusNFeGateway.URLS["homologacao"], transport=httpx.MockTransport(handler))
    return FocusNFeGateway("tok", "homologacao", "11222333000181", client=client, sleep=lambda s: None, **kw)


def test_focus_gateway_mapping_and_urls():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            seen["body"] = json.loads(req.content)
            seen["url"] = str(req.url)
            return httpx.Response(202, json={"status": "processando_autorizacao", "ref": "r1"})
        return httpx.Response(200, json={"status": "autorizado", "chave_nfe": "NFe" + "1" * 44, "numero": "7",
                                         "serie": "1", "caminho_danfe": "/arquivos/x.pdf",
                                         "caminho_xml_nota_fiscal": "https://evil.example/x.xml"})
    from datetime import datetime, timezone

    from app.application.ports import FiscalDocument, FiscalLine, FiscalParty
    doc = FiscalDocument(ref="r1", nature="Venda", issued_at=datetime.now(timezone.utc),
                         customer=FiscalParty("52998224725", "Fulano", None, None, "Rua", "1", None, "B", "C", "SP",
                                              "13000000"),
                         lines=(FiscalLine(1, "O2-IND", "Oxigênio", "28044000", "5102", "UN", Decimal("2"),
                                           Decimal("100"), Decimal("200.00"), "00", Decimal("18"), "01", "01", 0),),
                         total=Decimal("200.00"), notes=None)
    gw = _gw(handler)
    assert gw.emit(doc).status == "processing"
    b = seen["body"]
    assert "ref=r1" in seen["url"] and b["cpf_destinatario"] == "52998224725"
    assert b["indicador_inscricao_estadual_destinatario"] == 9 and b["consumidor_final"] == 1
    assert b["items"][0]["icms_valor"] == "36.00" and b["valor_total"] == "200.00"
    r = gw.query("r1")
    assert r.status == "authorized" and r.access_key == "1" * 44
    assert r.danfe_url == "https://homologacao.focusnfe.com.br/arquivos/x.pdf"
    assert r.xml_url is None   # host fora da allowlist é descartado


def test_focus_gateway_resilience():
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if req.method == "POST":
            raise httpx.ConnectTimeout("timeout")
        return httpx.Response(503)
    breaker = CircuitBreaker(threshold=3, reset_seconds=60)
    gw = _gw(flaky, breaker=breaker)
    from datetime import datetime, timezone

    from app.application.ports import FiscalDocument, FiscalParty
    doc = FiscalDocument("r2", "Venda", datetime.now(timezone.utc),
                         FiscalParty("52998224725", "F", None, None, "R", "1", None, "B", "C", "SP", "1"), (), Decimal(0), None)
    # POST não é repetido; vira "processing" (resolver por consulta)
    assert gw.emit(doc).status == "processing" and calls["n"] == 1
    # GET com 503 é repetido 3x e abre o circuito
    import pytest

    from app.domain.errors import ExternalServiceError
    with pytest.raises(ExternalServiceError):
        gw.query("r2")
    assert calls["n"] == 3
    with pytest.raises(ExternalServiceError):
        gw.query("r2")
    assert calls["n"] == 3   # circuito aberto: nem tentou
