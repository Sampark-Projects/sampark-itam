"""External API: the applications with their details (tenant scoping, paging, include, VAPT frequency)."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Application, ApplicationAsset, ApplicationFinding, ApplicationIntegration, ApplicationVapt
from app.routers import external_api
from app.services import application_security_logic as sl
from app.services.api_auth import require_read_scope, require_write_scope
from app.services.local_time import local_today

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def _client(db, w, scopes=("read",)):
    key = SimpleNamespace(id=uuid.uuid4(), tenant_id=w.tenant.id, created_by=w.user({"assets": 1}).id,
                          name="itsm", scopes=list(scopes), rate_limit="100000/hour")
    api = FastAPI()
    api.include_router(external_api.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[require_read_scope] = lambda: key
    api.dependency_overrides[require_write_scope] = lambda: key
    return TestClient(api)


def _application(db, w, name, number, **extra):
    app = Application(id=uuid.uuid4(), tenant_id=w.tenant.id, number=number, name=name, **extra)
    db.add(app)
    db.commit()
    return app


def _full(db, w):
    today = local_today()
    app = _application(db, w, "Billing", 1, tier="tier1", primary_url="https://billing.example", site_id=w.site.id,
                       business_owner="Finance", ssl_expiry_date=today + timedelta(days=10),
                       vapt_frequency_value=6, vapt_frequency_unit="month")
    db.add(ApplicationAsset(tenant_id=w.tenant.id, application_id=app.id, asset_id=w.asset.id, role="database", environment="production"))
    db.add(ApplicationIntegration(tenant_id=w.tenant.id, application_id=app.id, name="Payment gateway", direction="outbound",
                                  peer_asset_id=w.asset.id))
    vapt = ApplicationVapt(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=app.id, number=1, test_date=today - timedelta(days=30),
                           assessor="CERT-In")
    db.add(vapt)
    db.flush()
    for number, (severity, status) in enumerate((("high", "open"), ("low", "verified_fixed")), start=1):
        db.add(ApplicationFinding(tenant_id=w.tenant.id, application_id=app.id, vapt_id=vapt.id, number=number, title=f"{severity} issue",
                                  severity=severity, remediation_status=status, discovered_on=today, sla_due_date=today + timedelta(days=30),
                                  affected_asset_id=w.asset.id))
    db.commit()
    return app


def test_list_returns_all_the_details(db):
    w = World(db, "A")
    app = _full(db, w)
    r = _client(db, w).get("/external/v1/applications", params={"skip": 0, "limit": 50})
    assert r.status_code == 200
    data = r.json()
    assert (data["total"], data["skip"], data["has_more"]) == (1, 0, False) and data["limit"] == 50
    item = data["items"][0]
    detail = _client(db, w).get(f"/external/v1/applications/{app.id}").json()
    assert item == detail  # the list and the single application carry the same data
    _check_details(item, w, app)


def test_application_with_details(db):
    w = World(db, "A")
    app = _full(db, w)
    r = _client(db, w).get(f"/external/v1/applications/{app.id}")
    assert r.status_code == 200
    _check_details(r.json(), w, app)


def _check_details(item, w, app):
    assert item["id"] == str(app.id) and item["code"] == "APP-0001" and item["tier"] == "tier1"
    assert item["site"] == {"id": str(w.site.id), "name": w.site.name} and item["ssl_state"] == "expiring"
    assert item["assets"][0]["name"] == w.asset.name and item["assets"][0]["asset_type"] == "PLC" and item["assets"][0]["role"] == "database"
    assert item["integrations"][0]["name"] == "Payment gateway" and item["integrations"][0]["peer_asset_name"] == w.asset.name
    vapt = item["vapt_assessments"][0]
    assert vapt["code"] == "VAPT-0001" and "frequency_value" not in vapt and "next_due_date" not in vapt  # the frequency is the application's
    assert item["vapt_frequency"] == {"value": 6, "unit": "month"}
    assert {f["code"] for f in item["findings"]} == {"VULN-0001", "VULN-0002"}
    open_finding = next(f for f in item["findings"] if f["severity"] == "high")
    assert open_finding["open"] is True and open_finding["affected_asset_name"] == w.asset.name and open_finding["vapt_code"] == "VAPT-0001"
    summary = item["security_summary"]
    last = local_today() - timedelta(days=30)
    assert summary["assessments"] == 1 and summary["last_vapt_date"] == str(last)
    assert summary["next_vapt_due"] == str(sl.add_months(last, 6))  # last test + the application's frequency
    assert summary["open_findings"]["high"] == 1 and summary["open_findings_total"] == 1 and summary["suggested_posture"] == "fail"


def test_include_selects_the_sections(db):
    w = World(db, "A")
    url = f"/external/v1/applications/{_full(db, w).id}"
    c = _client(db, w)
    bare = c.get(url, params={"include": "none"}).json()
    assert not {"assets", "integrations", "vapt_assessments", "findings"} & set(bare)
    assert bare["security_summary"]["open_findings_total"] == 1 and bare["security_summary"]["assessments"] == 1  # still summarised
    some = c.get(url, params={"include": "vapt, findings"}).json()
    assert "vapt_assessments" in some and "findings" in some and "assets" not in some and "integrations" not in some
    assert c.get(url, params={"include": "vapt,bogus"}).status_code == 400
    listed = c.get("/external/v1/applications", params={"include": "none"}).json()["items"][0]  # the list takes include too
    assert not {"assets", "integrations", "vapt_assessments", "findings"} & set(listed) and listed["name"] == "Billing"
    assert c.get("/external/v1/applications", params={"include": "bogus"}).status_code == 400


def test_paging_filters_and_one_application(db):
    w = World(db, "A")
    for number, (name, tier) in enumerate((("Alpha", "tier1"), ("Beta", "tier2"), ("Gamma", "tier2")), start=1):
        _application(db, w, name, number, tier=tier)
    c = _client(db, w)
    first = c.get("/external/v1/applications", params={"limit": 2}).json()
    assert [i["name"] for i in first["items"]] == ["Alpha", "Beta"] and first["total"] == 3 and first["has_more"] is True
    rest = c.get("/external/v1/applications", params={"limit": 2, "skip": 2}).json()
    assert [i["name"] for i in rest["items"]] == ["Gamma"] and rest["has_more"] is False
    assert c.get("/external/v1/applications", params={"limit": 100000}).json()["limit"] == 500
    assert [i["name"] for i in c.get("/external/v1/applications", params={"tier": "tier2"}).json()["items"]] == ["Beta", "Gamma"]
    assert [i["name"] for i in c.get("/external/v1/applications", params={"search": "gam"}).json()["items"]] == ["Gamma"]
    one = c.get(f"/external/v1/applications/{first['items'][0]['id']}")
    assert one.status_code == 200 and one.json()["name"] == "Alpha"
    assert c.get(f"/external/v1/applications/{uuid.uuid4()}").status_code == 404


def test_only_the_keys_tenant_is_returned(db):
    mine, other = World(db, "A"), World(db, "B")
    _full(db, mine)
    theirs = _application(db, other, "Secret", 1)
    c = _client(db, mine)
    data = c.get("/external/v1/applications").json()
    assert data["total"] == 1 and "Secret" not in str(data)
    assert c.get(f"/external/v1/applications/{theirs.id}").status_code == 404
