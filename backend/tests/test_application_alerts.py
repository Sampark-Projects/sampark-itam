"""Application alerts, overview numbers and audit-pack sheets."""
import io
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.database import get_db
from app.models import Application, ApplicationAlertSent, ApplicationAsset, ApplicationFinding, ApplicationVapt
from app.routers import application_alerts, application_hosting, application_security, applications
from app.services import application_alert_logic as alog
from app.services import application_alert_service as svc
from app.services import application_security_logic as sl
from app.services import application_overview, report_service
from app.services.auth import get_current_user
from app.services.notification_service import NotificationService
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

TODAY = date(2026, 11, 17)
APP = {"id": "app1", "status": "production", "ssl_expiry_date": None}


def _finding(n, status="open", sla=TODAY + timedelta(days=30), severity="high", exception=None):
    return {"id": f"f{n}", "code": f"VULN-{n:04d}", "title": f"issue {n}", "severity": severity, "status": status,
            "sla_due_date": sla, "exception_valid_until": exception}


def _kinds(items):
    return sorted((i["kind"], i["threshold"]) for i in items)


# --- pure rules -------------------------------------------------------------------------------

def test_settings_are_cleaned():
    assert alog.clean_settings(True, [7, 90, 30, 30], 3) == {"enabled": True, "lead_days": [90, 30, 7], "finding_warn_days": 3}
    for lead, warn in (([], 3), ([0], 3), ([5000], 3), ([30], -1), ([30], 91), ([30], True), ([1.5], 3)):
        with pytest.raises(alog.AlertInputError):
            alog.clean_settings(True, lead, warn)


def test_ssl_and_vapt_follow_the_lead_times():
    due = lambda ssl=None, vapt=None, **k: alog.due_items({**APP, "ssl_expiry_date": ssl}, [], vapt, [90, 30, 7], 3, TODAY)
    assert due() == []
    assert _kinds(due(ssl=TODAY + timedelta(days=100))) == []  # not yet
    assert _kinds(due(ssl=TODAY + timedelta(days=60))) == [("ssl_expiry", 90)]
    assert _kinds(due(ssl=TODAY + timedelta(days=5))) == [("ssl_expiry", 7)]
    expired = due(ssl=TODAY - timedelta(days=2))
    assert _kinds(expired) == [("ssl_expiry", 0)] and "expired 2 day(s) ago" in expired[0]["text"]
    assert "due today" in due(vapt=TODAY)[0]["text"] and "overdue by 3" in due(vapt=TODAY - timedelta(days=3))[0]["text"]
    assert alog.due_items({**APP, "status": "retired", "ssl_expiry_date": TODAY}, [], TODAY, [30], 3, TODAY) == []


def test_findings_warn_then_become_overdue_and_exceptions_expire():
    items = alog.due_items(APP, [_finding(1, sla=TODAY + timedelta(days=3)), _finding(2, sla=TODAY + timedelta(days=4)),
                                 _finding(3, sla=TODAY - timedelta(days=1)), _finding(4, status="verified_fixed", sla=TODAY - timedelta(days=9)),
                                 _finding(5, status="risk_accepted", exception=TODAY + timedelta(days=20)),
                                 _finding(6, status="risk_accepted", exception=TODAY - timedelta(days=1))], None, [90, 30, 7], 3, TODAY)
    assert sorted((i["ref_id"], i["kind"], i["threshold"]) for i in items) == [
        ("f1", "finding_due", 3), ("f3", "finding_overdue", 0), ("f5", "exception_expiry", 30), ("f6", "exception_expiry", 0)]
    assert [i["text"] for i in items if i["ref_id"] == "f3"] == ["VULN-0003 'issue 3' (high): fix is overdue by 1 day(s)"]


# --- service ----------------------------------------------------------------------------------

def _setup(db, monkeypatch):
    w = World(db)
    boss = w.user(ADMIN_DEFAULT_PERMISSIONS, "boss")
    w.user({**EDITOR_DEFAULT_PERMISSIONS, "applications": 2}, "editor")  # not an administrator: gets nothing
    sent = []
    monkeypatch.setattr(NotificationService, "send_notification", staticmethod(lambda db_, user_id, template, ctx: sent.append((user_id, template, ctx)) or True))
    return w, boss, sent


def _app(db, w, **kw):
    n = db.query(Application).count() + 1
    a = Application(id=uuid.uuid4(), tenant_id=w.tenant.id, number=n, name=f"App {n}", lifecycle_status="production", **kw)
    db.add(a)
    db.commit()
    return a


def _add_finding(db, w, app, n, **kw):
    f = ApplicationFinding(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=app.id, number=n, title=kw.pop("title", f"issue {n}"), severity="high",
                           discovered_on=TODAY - timedelta(days=60), sla_due_date=kw.pop("sla_due_date", TODAY + timedelta(days=30)), **kw)
    db.add(f)
    db.commit()
    return f


def test_one_email_per_application_lists_everything_due_and_each_step_fires_once(db, monkeypatch):
    w, boss, sent = _setup(db, monkeypatch)
    app = _app(db, w, ssl_expiry_date=TODAY + timedelta(days=20), vapt_frequency_value=6, vapt_frequency_unit="month")
    _add_finding(db, w, app, 1, sla_due_date=TODAY - timedelta(days=2), title="<script>alert(1)</script>")
    _add_finding(db, w, app, 2, sla_due_date=TODAY + timedelta(days=60))  # nothing due
    # the last test was 6 months before the date 6 days from now, so the next VAPT (test + 6 months) is due in 6 days
    db.add(ApplicationVapt(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=app.id, number=1,
                           test_date=sl.add_months(TODAY + timedelta(days=6), -6)))
    db.commit()

    first = svc.run_application_alerts(db, w.tenant.id, TODAY)
    assert first["items"] == 3 and first["emails"] == 1 and len(sent) == 1  # the administrator only
    user_id, template, ctx = sent[0]
    assert user_id == boss.id and template == "application_alert" and ctx["application_code"] == "APP-0001"
    assert "SSL certificate expires in 20 day(s)" in ctx["message"] and "Next VAPT is due in 6 day(s)" in ctx["message"]
    assert "overdue by 2" in ctx["message"]
    assert "<script>" not in ctx["message_html"] and "&lt;script&gt;" in ctx["message_html"]  # titles are escaped in the HTML
    assert db.query(ApplicationAlertSent).count() == 3

    again = svc.run_application_alerts(db, w.tenant.id, TODAY)
    assert again["items"] == 0 and len(sent) == 1  # nothing twice
    later = svc.run_application_alerts(db, w.tenant.id, TODAY + timedelta(days=14))  # SSL reaches the 7-day step
    assert later["items"] >= 1 and any("SSL certificate" in s[2]["message"] for s in sent[1:])


def test_disabled_retired_and_no_recipients(db, monkeypatch):
    w, boss, sent = _setup(db, monkeypatch)
    app = _app(db, w, ssl_expiry_date=TODAY)
    retired = _app(db, w, ssl_expiry_date=TODAY)
    retired.lifecycle_status = "retired"
    db.commit()
    svc.save_settings(db, w.tenant.id, False, [30], 3)
    assert svc.run_application_alerts(db, w.tenant.id, TODAY)["skipped_disabled"] == 1 and not sent
    svc.save_settings(db, w.tenant.id, True, [30], 3)
    run = svc.run_application_alerts(db, w.tenant.id, TODAY)
    assert run["items"] == 1 and {s[2]["application_id"] for s in sent} == {str(app.id)}  # the retired one is silent

    other = World(db, "B")  # a tenant with nobody who administers the section
    other.user({**EDITOR_DEFAULT_PERMISSIONS, "applications": 2}, "editor")
    _app(db, other, ssl_expiry_date=TODAY)
    quiet = svc.run_application_alerts(db, other.tenant.id, TODAY)
    assert quiet["no_recipients"] == 1 and quiet["emails"] == 0
    assert db.query(ApplicationAlertSent).filter(ApplicationAlertSent.tenant_id == other.tenant.id).count() == 0  # it will go out later


# --- API --------------------------------------------------------------------------------------

def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (applications, application_hosting, application_security, application_alerts):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def test_alert_settings_and_run_now(db, monkeypatch):
    w, boss, sent = _setup(db, monkeypatch)
    admin = _client(db, boss)
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS, "applications": 2}, "e2"))
    viewer = _client(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "applications": 1}, "v"))
    assert admin.get("/application-alerts/settings").json() == {"enabled": True, "lead_days": [90, 30, 7], "finding_warn_days": 3}
    assert viewer.get("/application-alerts/settings").status_code == 200
    body = {"enabled": True, "lead_days": [60, 14], "finding_warn_days": 5}
    assert editor.put("/application-alerts/settings", json=body).status_code == 403 and editor.post("/application-alerts/run").status_code == 403
    saved = admin.put("/application-alerts/settings", json=body)
    assert saved.status_code == 200 and saved.json()["lead_days"] == [60, 14] and saved.json()["finding_warn_days"] == 5
    assert admin.put("/application-alerts/settings", json={**body, "lead_days": [0]}).status_code == 400
    assert admin.put("/application-alerts/settings", json={**body, "lead_days": []}).status_code == 422
    _app(db, w, ssl_expiry_date=TODAY + timedelta(days=10))
    ran = admin.post("/application-alerts/run").json()
    assert ran["items"] in (0, 1)  # depends on the real date; the structure is what matters here
    assert set(ran) == {"checked", "items", "emails", "no_recipients", "skipped_disabled"}


def test_overview_numbers_and_tenant_isolation(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    today = date.today()
    a = _app(db, w, tier="tier1", ssl_expiry_date=today - timedelta(days=1), vapt_frequency_value=6, vapt_frequency_unit="month")
    b = _app(db, w, tier="tier2", ssl_expiry_date=today + timedelta(days=10))
    _app(db, w)  # no tier, no assets
    db.add(ApplicationAsset(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=a.id, asset_id=w.asset.id, role="web"))
    db.add(ApplicationVapt(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=a.id, number=1, test_date=today - timedelta(days=300)))  # + 6 months: overdue
    for n, (severity, status, sla) in enumerate((("critical", "open", today - timedelta(days=1)), ("high", "patch_assigned", today + timedelta(days=9)),
                                                 ("high", "verified_fixed", today - timedelta(days=9))), start=1):
        f = ApplicationFinding(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=a.id, number=n, title="x", severity=severity, remediation_status=status,
                               discovered_on=today - timedelta(days=60), sla_due_date=sla, retest_date=today if status == "verified_fixed" else None,
                               retest_result="passed" if status == "verified_fixed" else None)
        db.add(f)
    db.commit()
    o = c.get("/applications/overview").json()
    assert o["total"] == 3 and o["by_tier"]["tier1"] == 1 and o["by_tier"]["tier2"] == 1 and o["by_tier"].get("unrated") == 1
    assert o["without_assets"] == 2 and o["ssl"] == {"expired": 1, "expiring": 1}
    assert o["vapt"] == {"never_tested": 2, "overdue": 1}
    assert o["findings"]["open"]["critical"] == 1 and o["findings"]["open"]["high"] == 1 and o["findings"]["open_total"] == 2 and o["findings"]["overdue"] == 1
    assert _client(db, World(db, "B").user(ADMIN_DEFAULT_PERMISSIONS)).get("/applications/overview").json()["total"] == 0


def test_audit_pack_gets_application_sheets_only_when_the_register_is_used(db):
    w = World(db)
    user = w.user(ADMIN_DEFAULT_PERMISSIONS)
    names = lambda: load_workbook(io.BytesIO(report_service.build_audit_pack(db, w.tenant.id, user, None, 90))).sheetnames
    assert "Applications" not in names()
    a = _app(db, w, tier="tier1", primary_url="https://corp.com")
    db.add(ApplicationAsset(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=a.id, asset_id=w.asset.id, role="web", environment="production"))
    _add_finding(db, w, a, 1, title="Outdated OpenSSL", sla_due_date=date.today() - timedelta(days=1))
    sheets = names()
    for title in ("Applications", "Application assets", "Application integrations", "VAPT", "Application findings"):
        assert title in sheets
    wb = load_workbook(io.BytesIO(report_service.build_audit_pack(db, w.tenant.id, user, None, 90)))
    rows = list(wb["Applications"].iter_rows(values_only=True))
    assert rows[1][0] == "APP-0001" and rows[1][18] == 1 and rows[1][20] == 1  # one linked asset, one open high finding
    assert [r[6] for r in wb["Application findings"].iter_rows(min_row=2, values_only=True)] == ["Outdated OpenSSL"]
